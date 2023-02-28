from definitions import LOGLEVEL, SOCKETFILE, PORTNUMFILE, LONGPOLLSECONDSMAX

from queueserver.auth import authobj
from queueserver.clean_request import clean_request
from starlette.endpoints import HTTPEndpoint
from starlette.responses import JSONResponse
import logging
import time
import asyncio
import platform
import os
import stat
from db import dbobj
from queueserver.clean_action import MessageReceive
from starlette.exceptions import HTTPException
import traceback

logger = logging.getLogger('starqueue')
logger.debug('MessageReceive std')


def load_portnumfile():
    try:
        with open(PORTNUMFILE, 'wb') as f:
            portnum = f.readline()
            return int(portnum.strip())
    except:
        logger.debug(f'Failed to get port number from {PORTNUMFILE}')
        return None

def is_socketfile_valid():
    try:
        #if os.path.exists(SOCKETFILE):
        #    print(f'Socket file {SOCKETFILE} exists....')
        mode = os.stat(SOCKETFILE).st_mode
        if stat.S_ISSOCK(mode):
            return True
    except Exception as e:
        logger.debug(f'Not a valid socket: {SOCKETFILE}')

async def dbnotificationserver_connect():
    logger.debug('Connecting to dbnotificationserver....')
    retry_delay_seconds = 5
    attempts = 0
    max_attempts = 4
    while True:
        try:
            if platform.system() == 'Windows':
                # Windows will be using tcp sockets, Linux will be unix sockets
                host = '127.0.0.1'  # yes hardcoded it should never be anywhere but local
                port = load_portnumfile()
                if not port:
                    attempts += 1
                    if attempts > max_attempts:
                        raise Exception()
                    logger.debug(f'Trying again after failure to get port number from {PORTNUMFILE}')
                    await asyncio.sleep(retry_delay_seconds)
                    continue
                reader, writer = await asyncio.open_connection(host, port)
                logger.debug(f'Connected to dbnotificationserver on {host} : {port}')
                return reader, writer
            else:
                if not is_socketfile_valid():
                    attempts += 1
                    if attempts > max_attempts:
                        raise Exception()
                    logger.debug(f'Trying again because socket file was not valid {SOCKETFILE}')
                    await asyncio.sleep(retry_delay_seconds)
                    continue
                reader, writer = await asyncio.open_unix_connection(SOCKETFILE)
                logger.debug(f'Connected to dbnotificationserver {SOCKETFILE}')
                return reader, writer
        except Exception as e:
            logger.debug(f'Failed to connect.... {repr(e)}')
            raise
            #await asyncio.sleep(retry_delay_seconds)

async def dbnotificationserver_longpoll(longpoll_seconds_remaining, accountid, queuename):
    logger.debug('Connecting to dbnotificationserver....')
    print('------------------')
    print('started connection')
    retry_delay_seconds = 2
    writer = None
    try:
        attempts = 0
        max_attempts = 4
        while True:
            try:
                reader, writer = await dbnotificationserver_connect()
                break
            except Exception as e:
                attempts += 1
                if attempts > max_attempts:
                    raise HTTPException(400, detail=f'back end error unable to connect to notifier')
                await asyncio.sleep(retry_delay_seconds)

        # tell the notification server which queue we are waiting on
        writer.write(f'HELLOSERVER\n'.encode())
        await writer.drain()
        received = await reader.readuntil()
        received = received.decode().strip()
        if received == 'HELLOCLIENT':
            message = f'{accountid}/{queuename}\n'.encode()
            writer.write(message)
            await writer.drain()
            print(f'sent {message}')
        received = await reader.readuntil()
        received = received.decode().strip()
        print(f'got a message from dbnotificationserver: {received}')
        if received == 'MESSAGEAVAILABLE':
            return True
        else:
            print('no MESSAGEAVAILABLE')
            pass
    except asyncio.IncompleteReadError as e:
        print(repr(e), traceback.format_exc())
    except Exception as e:
        print(repr(e), traceback.format_exc())
        # TODO ALERT SYSTEM ADMIN
        raise HTTPException(400, detail=f'back end error unable to connect to notifier')
    finally:
        # it is not necessary to await writer.wait_close() unless do not want to proceeed until it is closed.
        # https://github.com/aio-libs/aioredis/issues/707#issuecomment-688488084
        try:
            if writer:
                writer.close()
                print('client closed connection')
                print('------------------')
        except Exception as e:
            logger.debug(f'writer.close failed {repr(e)}')
            pass

class EndpointMessageReceive(HTTPEndpoint):
    async def post(self, request):
        #try:
        logger.debug('EndpointMessageReceive')
        await authobj.authenticate_request(request)
        '''
        inbound requests:

        loop:
            ask the database for a message
            if got a message, return it
            if the timeout has expired, return 'no messages' response to client
            if no message is available:
                start listening to the poll queue, with a timeout equal to the remaining seconds
                if the internal queue says a message is available then start the loop again
                if got no message, then go back to waiting on the queue
        '''
        data_to_clean = await clean_request.clean(request, MessageReceive.required_fields, MessageReceive.optional_fields)

        '''
        await authobj.verify_jwt_rs256(
            data_to_clean['accountid'],
            data_to_clean['AuthToken']
        )
        '''

        action = MessageReceive()
        api_request_data = await action.clean(data_to_clean)
        start_time_seconds = time.monotonic()
        while True:
            result = await dbobj.MessageReceive(api_request_data)  # immediately hit the db when request comes in
            request_seconds_elapsed = time.monotonic() - start_time_seconds
            longpoll_seconds_remaining = LONGPOLLSECONDSMAX - request_seconds_elapsed
            try:
                # if we succeeded in getting messages then return the response to the client
                if len(result['MessageReceiveResult']) > 0:
                    return JSONResponse(result, status_code=200)
                    # pass
            except:
                pass
            if longpoll_seconds_remaining <= 0:
                # if the request has gone for more than LONGPOLLSECONDSMAX then the (empty) response must be sent back
                print(result)
                return JSONResponse(result, status_code=200)
            # _ = None

            await dbnotificationserver_longpoll(longpoll_seconds_remaining, api_request_data['accountid'],
                                                api_request_data['queuename'])
            '''
            db_trafficcop_queue = db_trafficcop_queue_get(api_request_data['accountid'], api_request_data['queuename'])
            try:
                #_ = await asyncio.wait_for(db_trafficcop_queue.get(), longpoll_seconds_remaining)
                await asyncio.wait_for(db_trafficcop_queue.get(), longpoll_seconds_remaining)
                # got a message, so try to read from database
                raise MessageIsAvailableException('Internal queue says message is available in database.')
            except asyncio.TimeoutError:
                # outta time, return the previous response to the client, which contains no messages
                return JSONResponse(result, status_code=200)
            except MessageIsAvailableException:
                pass
            except Exception as e:
                logger.critical(f'UNKNOWN ERROR WAITING ON INTERNAL QUEUE!! {repr(e)}')
                # not really sure  how toi handle this, lets return no messages
                return JSONResponse(result, status_code=200)
            #finally:
            #    if _:
            #        db_trafficcop_queue.task_done()
            '''

        """
        except Exception as e:
            print(F'TOP LEVEL ERROR {repr(e)}')
            traceback.print_tb(e.__traceback__)
            response_data = {
                "MessageReceiveResult": {
                    "Error": {
                        "Code": "UnknownError",
                        "Message": repr(e),
                    },
                },
            }
            return JSONResponse(response_data, status_code=400)
        """


