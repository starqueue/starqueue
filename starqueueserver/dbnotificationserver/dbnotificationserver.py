import sys
import os

# allows us to run this from the project root and still find the db module
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db import dbobj
import asyncio
import os, stat
import logging
import coloredlogs
from definitions import LOGLEVEL, SOCKETFILE, PORTNUMFILE, LONGPOLLSECONDSMAX
import socket
import platform
import signal
import time
import traceback

maxeverything = 1000
enable_db_polling = True
enable_db_notifier = True
if enable_db_notifier:
    from notify_postgres import notification_listen_task

logger = logging.getLogger('dbnotificationserver')
coloredlogs.install(level=LOGLEVEL, logger=logger)
logger.setLevel(LOGLEVEL)

'''
clients connect via a socket to this server and say what accountid/queuename they are waiting on
the client gets the appropriate queue from db_trafficcop_queues keyed on accountid/queuename
if a queue does not exist for accountid/queuename then it is created
the client waits on the queue
if the client gets a message from the queue then it is told and the connection dropped
if the available time runs out, the connection dropped
in all cases, the long polling timeout is driven by the client, but this server has timeouts too just in case
there is no guarantee that the client will actually get a message after it has been notified that one is available
a client may connect to this server and wait multiple times during it's long polling timeout period
this might occur if it is told that a message might be availble but fails to get one

the database is polled once for each accountid/queuename that is being waited on
the number of available messages in the database is COUNTed but only up to the number of clients waiting (LIMIT)
when the COUNT is received the size of the queue is adjusted up or down to exactly match the COUNT

if the database has a notification trigger service then this server also listens on that for table updates
if the table was updated then the database poll/COUNT mechanism is immediately triggered by reducing its timeout to 0 

when no clients are listening on a queue anymore then that queue is deleted from the dict of queues
'''

# a dict of queues, keyed on accountid/queuename
db_trafficcop_queues = {}


async def count_workers(queue):
    while True:
        logger.debug('.', end='', flush=True)
        logger.debug(len(queue._getters), end='', flush=True)
        await asyncio.sleep(1)


def db_trafficcop_queue_purge(accountid, queuename):
    db_trafficcop_queue = db_trafficcop_queues_get(accountid, queuename)
    if not db_trafficcop_queue:
        return
    while not db_trafficcop_queue.empty():
        try:
            db_trafficcop_queue.get_nowait()
            db_trafficcop_queue.task_done()
        except asyncio.QueueEmpty:
            break
        except Exception as e:
            logger.critical(f'UNKNOWN ERROR in db_trafficcop_queue_purge!! {repr(e)}')
            break
        continue


def db_trafficcop_queue_delete_one_item(accountid, queuename):
    db_trafficcop_queue = db_trafficcop_queues_get(accountid, queuename)
    if not db_trafficcop_queue:
        return
    try:
        db_trafficcop_queue.get_nowait()
        db_trafficcop_queue.task_done()
    except Exception as e:
        pass

def db_trafficcop_queues_addqueue(accountid, queuename):
    global db_trafficcop_queues
    db_trafficcop_queue = db_trafficcop_queues_get(accountid, queuename)
    if not db_trafficcop_queue:
        accountids = list(db_trafficcop_queues.keys())
        if accountid not in accountids:
            db_trafficcop_queues[accountid] = {}
        db_trafficcop_queues[accountid][queuename] = asyncio.Queue(maxsize=maxeverything)
    return db_trafficcop_queues[accountid][queuename]


def db_trafficcop_queues_get(accountid, queuename):
    try:
        return db_trafficcop_queues[accountid][queuename]
    except:
        return None

async def db_message_poll():
    # this runs every second.
    # in an ideal world it would not be needed .... the Postgres notification trigger should be enough.
    # but to cautious, we run servce_queues every second
    db_poll_interval = 1 # second
    sleeptime_if_nothing_to_do = 1 # 1 second
    while True:
        accountids = list(db_trafficcop_queues.keys())
        logger.debug('polling...')
        if len(accountids) == 0:
            await asyncio.sleep(sleeptime_if_nothing_to_do)
            # don't do anything if no one is listening
            continue
        await service_queues()
        await asyncio.sleep(db_poll_interval)


async def db_message_trigger(db_trigger_event):
    while True:
        # this gets run by the code that monitors the database for update events on the message_queue table
        await db_trigger_event.wait()
        logger.debug('GOT AN EVENT TRIGGER FROM DB')
        await service_queues()
        db_trigger_event.clear()

async def service_queues():
    logger.debug('service_queues')
    # this is run either by the database notifying that a message has arrived, or is run every second
    # it continuously services waiting clients until there are none waiting
    await prune_empty_internal_queues()
    accountids = list(db_trafficcop_queues.keys())
    # process 1000 at a time
    chunk_size = 1000
    # LISTEN UP! Notice this is not asking for specific queuenames - it's just getting all for each accountid
    for i in range(0, len(accountids), chunk_size):
        chunk_of_accountids = accountids[i:i + chunk_size]
        count_of_waiting_messages_in_db = await dbobj.CountWaitingMessagesMultiAccount(chunk_of_accountids)
        #logger.debug('count_of_waiting_messages_in_db', count_of_waiting_messages_in_db)
        for item in count_of_waiting_messages_in_db:
            if item['accountid'] in accountids:
                await db_trafficcop_queue_update(item['accountid'], item['queuename'], item['count'])

async def prune_empty_internal_queues():
    accountids = list(db_trafficcop_queues.keys())
    for accountid in accountids:
        queuenames = list(db_trafficcop_queues[accountid].keys())
        for queuename in queuenames:
            db_trafficcop_queue_delete_if_empty(accountid, queuename)

def db_trafficcop_queue_delete_if_empty(accountid, queuename):
    db_trafficcop_queue = db_trafficcop_queues_get(accountid, queuename)
    if not db_trafficcop_queue:
        return
    number_of_waiting_requests = len(db_trafficcop_queue._getters)  # undocumented in Python
    if number_of_waiting_requests == 0:
        # delete the queue because no clients are listening
        # remove all the messages
        db_trafficcop_queue_purge(accountid, queuename)
        # delete the queue object from the dict of queues
        db_trafficcop_queues[accountid].pop(queuename, None)
        # and if there are no more queues under that accountid then remove the accountid too
        if not bool(db_trafficcop_queues[accountid]):  # use bool to determine if dict empty
            db_trafficcop_queues.pop(accountid, None)


async def db_trafficcop_queue_adjust_size_to_exactly(accountid, queuename, targetsize):
    # checks the database for number of messages in a given accountid/queuename and updates the internal queues
    db_trafficcop_queue = db_trafficcop_queues_get(accountid, queuename)
    if not db_trafficcop_queue:
        return
    qsize = db_trafficcop_queue.qsize()
    # if queue bigger, remove queue items until same size
    while qsize > targetsize:
        db_trafficcop_queue_delete_one_item(accountid, queuename)
        qsize = db_trafficcop_queue.qsize()
    # if queue smaller, add queue items until same size
    qsize = db_trafficcop_queue.qsize()
    # if queue bigger, remove queue items until same size
    while qsize < targetsize:
        db_trafficcop_queue.put_nowait(True)
        qsize = db_trafficcop_queue.qsize()
    '''
    logger.debug('db_trafficcop_queue.get 1: ')
    qsize = db_trafficcop_queue.qsize()
    logger.debug('qsize: ', qsize)
    await db_trafficcop_queue.get()
    qsize = db_trafficcop_queue.qsize()
    logger.debug('qsize: ', qsize)
    await db_trafficcop_queue.task_done()
    qsize = db_trafficcop_queue.qsize()
    logger.debug('qsize: ', qsize)
    logger.debug('db_trafficcop_queue.get 2: ')
    '''

async def db_trafficcop_queue_update(accountid, queuename, count_of_waiting_messages_in_db):
    # checks the database for number of messages in a given accountid/queuename and updates the internal queues
    db_trafficcop_queue_delete_if_empty(accountid, queuename)
    db_trafficcop_queue = db_trafficcop_queues_get(accountid, queuename)
    if not db_trafficcop_queue:
        return
    number_of_waiting_requests = len(db_trafficcop_queue._getters)  # undocumented in Python
    # the length of the queue should be equal to the number of waiting clients/socket connections
    # notice that we only ask the database for a count up to the number of waiting clients/socket connections
    # there is no value in knowing any higher number
    await db_trafficcop_queue_adjust_size_to_exactly(accountid, queuename,
                                               min(count_of_waiting_messages_in_db, number_of_waiting_requests))

async def db_trafficcop_queue_wait(accountid, queuename):
    # clients wait on this function after connecting
    db_trafficcop_queue = db_trafficcop_queues_get(accountid, queuename)
    if not db_trafficcop_queue:
        db_trafficcop_queue = db_trafficcop_queues_addqueue(accountid, queuename)
    try:
        # timeout should actually always come from the client dropping the connection, but just in case...
        await asyncio.wait_for(db_trafficcop_queue.get(), LONGPOLLSECONDSMAX)
        # a message is/might be available, so tell the client
        return True
    except asyncio.TimeoutError:
        return None
    except Exception as e:
        logger.critical(f'UNKNOWN ERROR WAITING ON INTERNAL QUEUE!! {repr(e)}')
        return None


async def handle_client(reader, writer):
    # no client should ever wait longer than LONGPOLLSECONDSMAX
    try:
        # received = await asyncio.wait_for(reader.readline(), timeout=LONGPOLLSECONDSMAX)
        received = await reader.readuntil()
        received = received.decode().strip()
        if received == 'HELLOSERVER':
            # the connection starts with the client saying HELLO, which we reply to
            # reply with HELLO to let the client know they are connected
            writer.write('HELLOCLIENT\n'.encode())
            await writer.drain()
        received = await reader.readuntil()
        received = received.decode().strip()
        accountid, _, queuename = received.partition('/')
        #logger.debug(f'received: {accountid}/{queuename}')
        start = time.monotonic()
        result = await db_trafficcop_queue_wait(accountid, queuename)
        ######################await db_trafficcop_queue_update(accountid, queuename)
        logger.debug(f'elapsed: {time.monotonic() - start}')
        if result:
            # messages are available, tell the client and drop the connection
            writer.write('MESSAGEAVAILABLE\n'.encode())
            await writer.drain()
            logger.debug('sent: MESSAGEAVAILABLE')
        else:
            writer.write('TIMEOUTSERVERDROPPINGCONNECTION\n'.encode())
            await writer.drain()
            logger.debug('sent: DROPPINGCONNECTION')
    except Exception as e:
        logger.debug(repr(e), traceback.format_exc())
    finally:
        # no valid data from client
        logger.debug('dropped client connection')
        writer.close()


def remove_socketfile():
    try:
        if os.path.exists(SOCKETFILE):
            os.remove(SOCKETFILE)
    except PermissionError:
        logger.debug(f'Permissions error! Failed to remove {SOCKETFILE}')
    except Exception as e:
        logger.debug(f'Failed to remove {repr(e)} {SOCKETFILE}')


def find_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        portnum = s.getsockname()[1]
        with open(PORTNUMFILE, 'wb') as f:
            f.write('%d' % portnum)
        return portnum


async def dbnotificationserver_start():
    retry_delay_seconds = 5
    while True:
        if platform.system() == 'Windows':
            # Windows returns an Attribute error because there is no open_unix_connection
            host = '127.0.0.1'
            port = find_free_port()
            logger.debug(f'Trying to start dbnotificationserver on {host} {port} ....')
            try:
                server = await asyncio.start_server(handle_client, host, port)
                logger.debug(f'Started dbnotificationserver {host} {port} ....')
                return server
            except Exception as e:
                logger.debug(f'Failed to  start dbnotificationserver on {host} {port} ....{repr(e)}')
                await asyncio.sleep(retry_delay_seconds)
                continue
        else:
            # must be a Unix system
            try:
                logger.debug(f'Trying to start dbnotificationserver on unix socket: {SOCKETFILE}')
                remove_socketfile()
                server = await asyncio.start_unix_server(handle_client, path=SOCKETFILE)
                os.chmod(SOCKETFILE, 0o666)
                logger.debug(f'Started dbnotificationserver {SOCKETFILE} ....')
                return server
            except Exception as e:
                logger.debug(
                    f'Retrying start of dbnotificationserver in {retry_delay_seconds} seconds on unix socket: {SOCKETFILE} {repr(e)}')
                await asyncio.sleep(retry_delay_seconds)
                continue


async def count_queues():
    all_queues = []
    for accountid in db_trafficcop_queues.keys():
        for queuename in db_trafficcop_queues[accountid].keys():
            getters = len(db_trafficcop_queues[accountid][queuename]._getters)
            qsize = db_trafficcop_queues[accountid][queuename].qsize()
            all_queues.append(f'{accountid}/{queuename}/getters:{getters}/qsize:{qsize}')
    return len(all_queues)

async def task_list_coroutines():
    global db_trafficcop_queues
    while True:
        await asyncio.sleep(5)
        logger.debug(f'there are: {len(asyncio.all_tasks())} tasks running:')
        # for task in asyncio.all_tasks():
        #    logger.debug(f'name: {task.get_name()} coro: {task.get_coro()}')
        logger.debug(f'Clients waiting on {await count_queues()} queues.')
        # queues_being_polled = [f'{x['AccountId']}/{x['QueueName']}' for x in db_trafficcop_queues.items()]
        # logger.debug(json.dumps(db_trafficcop_queues, indent=4, default=lambda o: '<not serializable>'))
        '''
        for key in db_trafficcop_queues.keys():
            for item in db_trafficcop_queues[key].keys():
                logger.debug(f'{key}/{item}')
        '''


async def task_shutdown(loop, signal=None):
    if signal:
        logger.debug(f'Received exit signal {signal.name}...')
    logger.debug('Closing database connections')
    tasks = [t for t in asyncio.all_tasks() if t is not
             asyncio.current_task()]
    [task.cancel() for task in tasks]
    logger.debug(f'Cancelling {len(tasks)} outstanding tasks')
    await asyncio.gather(*tasks, return_exceptions=True)
    logger.debug(f'Flushing metrics')
    loop.stop()


def handle_exception(loop, context):
    # ref https://www.roguelynn.com/words/asyncio-exception-handling/
    # ref https://docs.python.org/3/library/asyncio-dev.html#detect-never-retrieved-exceptions
    # ref https://docs.python.org/3/library/asyncio-eventloop.html#asyncio.loop.set_exception_handler

    # context['message'] will always be there; but context['exception'] must not
    msg = context.get('exception', context['message'])
    logging.error(f'Caught exception: {msg}')
    logger.debug('Shutting down...')
    task = asyncio.create_task(task_shutdown(loop))
    task.set_name('task: task_shutdown')


def setup_signals():
    logger.debug('setup_signals')
    # ref https://www.roguelynn.com/words/asyncio-exception-handling/
    # ref https://docs.python.org/3/library/asyncio-dev.html#detect-never-retrieved-exceptions
    # ref https://docs.python.org/3/library/asyncio-eventloop.html#asyncio.loop.set_exception_handler
    # May want to catch other signals too
    loop = asyncio.get_event_loop()
    signals = (signal.SIGHUP, signal.SIGTERM, signal.SIGINT)
    for s in signals:
        loop.add_signal_handler(
            s, lambda s=s: asyncio.create_task(task_shutdown(loop, signal=s)))
    loop.set_exception_handler(handle_exception)


async def startup():
    logger.debug(f'Notifier startup...')
    await dbobj.get_pool()
    loop = asyncio.get_event_loop()
    task = loop.create_task(task_list_coroutines())
    task.set_name('task: task_list_coroutines')
    if enable_db_polling:
        task = loop.create_task(db_message_poll())
        task.set_name(f'task: db_message_poll')
    db_trigger_event = asyncio.Event()
    if enable_db_notifier:
        task = loop.create_task(db_message_trigger(db_trigger_event))
        task.set_name(f'task: db_message_trigger')
        async def callback():
            db_trigger_event.set()
        # the notification_listen_task listens for notifications from the database that a new message has arrived
        loop.create_task(notification_listen_task(callback))
    setup_signals()
    server = await dbnotificationserver_start()
    async with server:
        await server.serve_forever()
    loop.run_forever()


asyncio.run(startup())
