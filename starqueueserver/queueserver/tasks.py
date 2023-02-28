from db import dbobj
import asyncio
import coloredlogs
import json
import logging
import traceback
import definitions

db_trafficcop_queues = {}

logger = logging.getLogger('starqueue')
coloredlogs.install(level=definitions.LOGLEVEL, logger=logger)
logger.setLevel(definitions.LOGLEVEL)

async def task_MessageRetentionPeriodTidyupTask():
    delay = 600  # 10 minutes
    while True:
        await asyncio.sleep(delay)
        logger.debug(f'doing queue tidyup MessageRetentionPeriodTidyupTask.....')
        try:
            await dbobj.MessageRetentionPeriodTidyupTask()
        except Exception as e:
            logger.critical(f'task_MessageRetentionPeriodTidyupTask ERROR {repr(e)}')
            traceback.print_stack()

async def task_MaxReceivesExceededTidyupTask():
    delay = 60  # 1 minute
    while True:
        await asyncio.sleep(delay)
        try:
            logger.debug(f'doing queue tidyup task_MaxReceivesExceededTidyupTask.....')
            await dbobj.MaxReceivesExceededTidyupTask()
        except Exception as e:
            logger.critical(f'task_MaxReceivesExceededTidyupTask ERROR {repr(e)}')
            traceback.print_stack()

async def task_list_coroutines():
    global db_trafficcop_queues
    while True:
        await asyncio.sleep(5)
        print(f'there are: {len(asyncio.all_tasks())} tasks running:')
        for task in asyncio.all_tasks():
            print(f'name: {task.get_name()} coro: {task.get_coro()}')
        print(f'the database is being polled for these queues:')
        # queues_being_polled = [f'{x['AccountId']}/{x['QueueName']}' for x in db_trafficcop_queues.items()]
        print(json.dumps(db_trafficcop_queues, indent=4, default=lambda o: '<not serializable>'))

async def task_shutdown(loop, signal=None):
    '''MessageRetentionPeriodTidyupTask tasks tied to the service's shutdown.'''
    if signal:
        logger.debug(f'Received exit signal {signal.name}...')
    logger.debug('Closing database connections')
    # todo close connections
    tasks = [t for t in asyncio.all_tasks() if t is not
             asyncio.current_task()]
    [task.cancel() for task in tasks]
    logger.debug(f'Cancelling {len(tasks)} outstanding tasks')
    await asyncio.gather(*tasks, return_exceptions=True)
    logger.debug(f'Flushing metrics')
    loop.stop()

