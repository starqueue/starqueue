import logging
import arrow
import uuid
import copy
import asyncio
import aioodbc
from ..loadconfig import load

logger = logging.getLogger('starqueue')

class NoMessagesAvailableException(Exception):
    pass

__all__ = [
    'DatabaseQueue',
]

################################################################################
### IMPORTANT!!!!
### We only EVER use the database clock for dates and times.
### Everything about this system is date and time driven so it is important that a single clock is used.
### NEVER use Python datetime for setting dates/times in records - push it into the database.
###
### You will be vaporised by invading aliens if you disobey!
###
################################################################################

class DatabaseQueue():

    def __init__(self):
        self.db_type = 'sqlserver'
        self.MaxReceivesInfoForAllQueues = {}  # contains {accountid: {queuename: (int)MaxReceives}}
        self.pool = None

    async def get_pool(self):
        if not self.pool:
            DB_USERNAME, DB_HOST, DB_PORT, DB_PASSWORD, DB_DATABASENAME, DB_TYPE = load()
            await self.create_pool(DB_USERNAME, DB_HOST, DB_PORT, DB_PASSWORD, DB_DATABASENAME)

    async def create_pool(self, DB_USERNAME, DB_HOST, DB_PORT, DB_PASSWORD, DB_DATABASENAME):
        print(f'initialising {self.db_type} database connection')
        print(
            f'DB_USERNAME: {DB_USERNAME}, DB_HOST: {DB_HOST}, DB_PORT: {DB_PORT}, DB_DATABASENAME: {DB_DATABASENAME}')

        # notice the double braces
        dsn = f'Driver={{ODBC Driver 17 for SQL Server}};Server={DB_HOST};UID={DB_USERNAME};PWD={DB_PASSWORD};Database={DB_DATABASENAME}'
        loop = asyncio.get_running_loop()
        self.pool = await aioodbc.create_pool(dsn=dsn, loop=loop, autocommit=False)
        print(f'initialising {self.db_type} database connection complete')

    async def shutdown(self):
        await self.pool.close()
        await self.pool.wait_closed()

    async def CountWaitingMessagesInQueue(self, max_to_count, AccountId, QueueName):
        print('STD CountWaitingMessagesInQueue')
        # the purpose of this function is to count the number of messages in the queue, but only up to a limit
        # this is used by the polling mechanism which needs to know how many messages are waiting, but it is
        # interested only up to the number of inbound client requests waiting, thus the LIMIT
        await self.get_pool()
        async with self.pool.acquire() as connection:
            async with connection.cursor() as cursor:
                sql = '''\
                    SELECT COUNT(*) as count
                    FROM (
                      SELECT TOP(?) 
                      1 as foo
                      FROM message_queue
                      WHERE queuename = ?
                      AND accountid = ?
                      AND deleted = 0
                      AND visibilitytimeout < SYSUTCDATETIME()
                    ) as temp
                    ;'''
                params = (
                    max_to_count,
                    str(QueueName),
                    str(AccountId),
                )
                try:
                    await cursor.execute(sql, params)
                    result = await cursor.fetchone()
                    return int(result.count)
                except Exception as e:
                    print(f"CountWaitingMessagesInQueue FAILED!! {repr(e)}")

    async def MessageDelete(self, api_request_data):
        print('STD MessageDelete')
        # it would be more efficient to issue a single SQL statement but it's more simple to reuse MessageDelete
        for item in api_request_data['ReceiptHandles']:
            await self.MessageDeleteSingle({'ReceiptHandle': item})
        response_data = {"MessageDeleteResult": {}}
        return response_data

    async def MessageDeleteSingle(self, api_request_data):
        print('STD MessageDeleteSingle')
        await self.get_pool()
        async with self.pool.acquire() as connection:
            async with connection.cursor() as cursor:
                sql = '''\
                DELETE FROM message_queue 
                WHERE receipthandle = ?'''
                params = (
                    api_request_data['ReceiptHandle'],
                )
                try:
                    await cursor.execute('BEGIN TRANSACTION')
                    result = await connection.fetchrow(sql, params)
                    await cursor.execute('COMMIT TRANSACTION')
                except Exception as e:
                    await cursor.execute('ROLLBACK TRANSACTION')
                    print(f"MessageDelete ROLLBACK TRANSACTION {repr(e)}")
            response_data = {"MessageDeleteResult": {}}
            return response_data

    async def QueueClear(self, api_request_data):
        print('STD QueueClear')
        await self.get_pool()
        async with self.pool.acquire() as connection:
            async with connection.cursor() as cursor:
                sql = f'''\
                DELETE FROM message_queue 
                WHERE accountid = ? 
                AND queuename = ? 
                '''
                params = (
                    api_request_data['accountid'],
                    api_request_data['queuename'],
                )
                try:
                    await cursor.execute('BEGIN TRANSACTION')
                    await cursor.execute(sql, params)
                    await cursor.execute('COMMIT TRANSACTION')
                except Exception as e:
                    await cursor.execute('ROLLBACK TRANSACTION')
                    print(f"QueueClear ROLLBACK TRANSACTION {repr(e)}")
            response_data = {"QueueClearResponse": {}}
            return response_data

    async def QueuesList(self, api_request_data):
        print('STD QueuesList')
        await self.get_pool()
        async with self.pool.acquire() as connection:
            async with connection.cursor() as cursor:
                try:
                    sql = f'''\
                    SELECT TOP 10000 accountid, queuename, count(1) as messagecount
                    FROM message_queue
                    GROUP BY accountid, queuename'''
                    await cursor.execute(sql)
                    result = await cursor.fetchall()
                    queues = [{'AccountId': str(item.accountid), 'QueueName': item.queuename, 'Count': item.messagecount} for
                              item in result]
                except Exception as e:
                    print(f"QueuesList FAILED!! {repr(e)}")
            response_data = {"QueuesListResult": queues}
            return response_data


    async def MaxReceivesExceededTidyupTask(self):
        print('STD MaxReceivesExceededTidyupTask')
        '''
        deletes messages that have been received more times than permitted by MaxReceives

        this function is run by the server every N seconds

        self.MaxReceivesInfoForAllQueues holds the details of the queues and the MaxReceives value to apply

        self.MaxReceivesInfoForAllQueues is updated with each inbound request by MessageReceive

        self.MaxReceivesInfoForAllQueues is pruned of values each time this function runs
        '''
        # we copy it because we will be mutating the original
        copy_MaxReceivesInfoForAllQueues = copy.deepcopy(self.MaxReceivesInfoForAllQueues)
        for accountid in copy_MaxReceivesInfoForAllQueues.keys():
            for queuename in copy_MaxReceivesInfoForAllQueues[accountid].keys():
                item = copy_MaxReceivesInfoForAllQueues[accountid][queuename]
                MaxReceives = item['MaxReceives']

                # remove queue from the MaxReceives - this prevents memory leak for large variety of queuenames
                # we do this BEFORE carrying out the deletions
                del self.MaxReceivesInfoForAllQueues[accountid][queuename]
                # and if no queue names left under the 'accountid' key then remove that too
                if not bool(self.MaxReceivesInfoForAllQueues[accountid]):
                    del self.MaxReceivesInfoForAllQueues[accountid]

                await self.MaxReceivesExceededMessageDeletesFromQueue(accountid, queuename, MaxReceives)

    async def MaxReceivesExceededMessageDeletesFromQueue(self, accountid, queuename, MaxReceives):
        print('STD MaxReceivesExceededMessageDeletesFromQueue')
        await self.get_pool()
        async with self.pool.acquire() as connection:
            async with connection.cursor() as cursor:
                sql = f'''\
                DELETE
                  FROM message_queue
                  WHERE queuename = ?
                  AND deleted = 0
                  AND accountid = ?
                  AND visibilitytimeout < SYSUTCDATETIME()
                  AND approximatereceivecount >= ?
                  ;'''
                params = (
                    str(queuename),
                    str(accountid),
                    int(MaxReceives),
                )
                try:
                    await cursor.execute('BEGIN TRANSACTION')
                    await cursor.execute(sql, params)
                    await cursor.execute('COMMIT TRANSACTION')
                except Exception as e:
                    await cursor.execute('ROLLBACK TRANSACTION')
                    logger.critical(f'MaxReceivesExceededMessageDeletesFromQueue: ROLLBACK {repr(e)}')

    async def MessageRetentionPeriodTidyupTask(self):
        print('STD MessageRetentionPeriodTidyupTask')
        await self.get_pool()
        async with self.pool.acquire() as connection:
            async with connection.cursor() as cursor:
                sql = f'''DELETE FROM message_queue WHERE messageretentionperiod < SYSUTCDATETIME();'''
                try:
                    await cursor.execute('BEGIN TRANSACTION')
                    result = await connection.fetchrow(sql)
                    await cursor.execute('COMMIT TRANSACTION')
                except Exception as e:
                    await cursor.execute('ROLLBACK TRANSACTION')
                    print(f"MessageRetentionPeriodTidyupTask ROLLBACK TRANSACTION {repr(e)}")


    async def MessageReceive(self, api_request_data):
        print('STD MessageReceive')
        messages = []
        # update DatabaseQueue.MaxReceives - this defines threshhold for the MaxReceives tidyup task
        x = {api_request_data['accountid']: {api_request_data['queuename']: api_request_data['MaxReceives']}}
        self.MaxReceivesInfoForAllQueues.update(x)
        max_messages_to_receive = api_request_data['MaxNumberOfMessages']
        while len(messages) < max_messages_to_receive:
            message = await self.MessageReceiveSingle(api_request_data)
            if not message:
                # we read messages until no more are available or reached max_messages_to_receive, then return what we got.
                break
            messages.append(message)
        response_data = {"MessageReceiveResult": messages}
        return response_data

    async def MessageReceiveSingle(self, api_request_data):
        print('STD MessageReceiveSingle')
        # update self.MaxReceivesInfoForAllQueues - this defines threshhold for the MaxReceives tidyup task
        x = {
            api_request_data['accountid']: {
                api_request_data['queuename']: {
                    'MaxReceives': api_request_data['MaxReceives'],
                }
            }
        }
        self.MaxReceivesInfoForAllQueues.update(x)

        await self.get_pool()
        async with self.pool.acquire() as connection:
            async with connection.cursor() as cursor:
                queuename = api_request_data['queuename']
                accountid = api_request_data['accountid']
                VisibilityTimeout = api_request_data['VisibilityTimeout']
                date_sort_order = 'ASC'
                sql = f'''\
                UPDATE message_queue WITH (READPAST) 
                SET 
                    visibilitytimeout = DATEADD(second, ?, CURRENT_TIMESTAMP), 
                    receipthandle = newid(),
                    approximatefirstreceivetimestamp =  COALESCE(approximatefirstreceivetimestamp, SYSUTCDATETIME()),
                    approximatereceivecount = approximatereceivecount + 1 
                OUTPUT 
                    INSERTED.accountid,
                    INSERTED.approximatefirstreceivetimestamp,
                    INSERTED.approximatereceivecount,
                    INSERTED.md5ofmessagebody,
                    INSERTED.messagebody,
                    INSERTED.messageid,
                    INSERTED.queuename,
                    INSERTED.receipthandle,
                    INSERTED.senttimestamp,
                    INSERTED.sequencenumber
                WHERE messageid = (
                  SELECT TOP 1 messageid
                  FROM message_queue
                  WHERE queuename = ?
                  AND accountid = ?
                  AND deleted = 0
                  AND visibilitytimeout < SYSUTCDATETIME()
                  AND approximatereceivecount < ?
                  ORDER BY senttimestamp {date_sort_order}
                )'''
                params = (
                    VisibilityTimeout,
                    str(queuename),
                    str(accountid),
                    api_request_data['MaxReceives'],
                )
                try:
                    await cursor.execute('BEGIN TRANSACTION')
                    await cursor.execute(sql, params)
                    result = await cursor.fetchone()
                    if (result == []) or (not result):
                        raise NoMessagesAvailableException('Situation normal, no messages available.')
                    message_data = {}
                    message_data['AccountId'] = result.accountid
                    message_data['ApproximateFirstReceiveTimestamp'] = result.approximatefirstreceivetimestamp
                    message_data['ApproximateReceiveCount'] = result.approximatereceivecount
                    message_data['MD5OfMessageBody'] = result.md5ofmessagebody
                    message_data['MessageBody'] = result.messagebody
                    message_data['MessageId'] = result.messageid
                    message_data['QueueName'] = result.queuename
                    message_data['ReceiptHandle'] = result.receipthandle
                    message_data['SentTimestamp'] = result.senttimestamp
                    # do some transformations
                    message_data['ApproximateFirstReceiveTimestamp'] = arrow.get(
                        message_data['ApproximateFirstReceiveTimestamp']).isoformat()
                    message_data['MessageDeduplicationId'] = message_data['MessageDeduplicationId'] or ''
                    message_data['MessageId'] = str(message_data['MessageId'])
                    message_data['AccountId'] = str(message_data['AccountId'])
                    message_data['ReceiptHandle'] = str(message_data['ReceiptHandle'])
                    message_data['SentTimestamp'] = arrow.get(message_data['SentTimestamp']).isoformat()
                    await cursor.execute('COMMIT TRANSACTION')
                    return message_data
                except NoMessagesAvailableException as e:
                    # normal situation, no messages found
                    await cursor.execute('ROLLBACK TRANSACTION')
                except Exception as e:
                    logger.critical(f"MessageReceive UNKNOWN ERROR ROLLBACK TRANSACTION {repr(e)}")
                    await cursor.execute('ROLLBACK TRANSACTION')

    async def MessageSend(self, api_request_data):
        print('STD MessageSend')
        VisibilityTimeout = api_request_data['VisibilityTimeout']
        MessageRetentionPeriod = api_request_data['MessageRetentionPeriod']
        await self.get_pool()
        async with self.pool.acquire() as connection:
            async with connection.cursor() as cursor:
                sql = f'''\
                INSERT INTO message_queue 
                (accountid, 
                queuename, 
                messagebody, 
                visibilitytimeout, 
                messageretentionperiod, 
                md5ofmessagebody) 
                OUTPUT INSERTED.messageid, INSERTED.md5ofmessagebody, INSERTED.sequencenumber
                VALUES (
                    ?, 
                    ?, 
                    ?, 
                    DATEADD(second, ?, CURRENT_TIMESTAMP), 
                    DATEADD(second, ?, CURRENT_TIMESTAMP), 
                    ?)'''
                params = (
                    str(api_request_data['accountid']),
                    api_request_data['queuename'],
                    api_request_data['MessageBody'],
                    VisibilityTimeout,
                    MessageRetentionPeriod,
                    api_request_data['MD5OfMessageBody'],
                )
                try:
                    await cursor.execute('BEGIN TRANSACTION')
                    await cursor.execute(sql, params)
                    result = await cursor.fetchone()
                    print(result)
                    await cursor.execute('COMMIT')
                    '''
                    TODO WHERE IS THE CORRECT EXCEPTION FOR THIS?
                    except asyncpg.exceptions.UniqueViolationError:
                        await cursor.execute('ROLLBACK TRANSACTION')
                        response_data = {
                            "MessageSendResult": {
                                "Error": {
                                    "Type": "Sender",
                                    "Code": "DuplicateMessage",
                                    "Message": f"Duplicate message. MessageDeduplicationId is: {data['MessageDeduplicationId']}",
                                }
                            }
                        }
                        return response_data
                    '''
                except Exception as e:
                    logger.critical(f"UNKNOWN DATABASE ERROR IN MESSAGESEND {repr(e)}")
                    await cursor.execute('ROLLBACK TRANSACTION')
                    response_data = {
                        "MessageSendResult": {
                            "Error": {
                                        "Code": "UnknownError",
                                "Message": f"Unknown error",
                            },
                        }
                    }
                    return response_data

                response_data = {
                        "MessageSendResult": {
                            "MessageId": str(result.messageid),
                            "MD5OfMessageBody": result.md5ofmessagebody
                        },
                }
                return response_data

