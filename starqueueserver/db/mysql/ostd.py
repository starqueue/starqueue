import logging
import arrow
import uuid
import copy
import asyncio
import traceback
import aiomysql
from ..loadconfig import load
from pymysql.converters import escape_dict, escape_sequence, escape_string
from pymysql.err import (Warning, Error, InterfaceError, DataError,
                         DatabaseError, OperationalError, IntegrityError,
                         InternalError,
                         NotSupportedError, ProgrammingError, MySQLError)

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
        self.db_type = 'mysql'
        self.MaxReceivesInfoForAllQueues = {}  # contains {accountid: {queuename: (int)MaxReceives}}
        self.pool = None

    async def get_pool(self):
        logger.debug('STD get_pool')
        if not self.pool:
            DB_USERNAME, DB_HOST, DB_PORT, DB_PASSWORD, DB_DATABASENAME, DB_TYPE = load()
            await self.create_pool(DB_USERNAME, DB_HOST, DB_PORT, DB_PASSWORD, DB_DATABASENAME)

    async def create_pool(self, DB_USERNAME, DB_HOST, DB_PORT, DB_PASSWORD, DB_DATABASENAME):
        logger.debug('STD create_pool')
        logger.debug(f'initialising {self.db_type} database connection')
        logger.debug(
            f'DB_USERNAME: {DB_USERNAME}, DB_HOST: {DB_HOST}, DB_PORT: {DB_PORT}, DB_DATABASENAME: {DB_DATABASENAME}')
        loop = asyncio.get_running_loop()
        try:
            self.pool = await aiomysql.create_pool(host=DB_HOST,
                                              port=int(DB_PORT),
                                              user=DB_USERNAME,
                                              password=DB_PASSWORD,
                                              db='hotqueue',
                                              autocommit=False,
                                              auth_plugin='mysql_native_password',
                                              loop=loop)
        except Exception as e:
            print(vars(e))
            print(repr(e), traceback.format_exc())
        except aiomysql.OperationalError as e:
            print(vars(e))
            print(repr(e), traceback.format_exc())

    async def shutdown(self):
        logger.debug('STD shutdown')
        await self.pool.close()

    async def CountWaitingMessagesInQueue(self, max_to_count, AccountId, QueueName):
        logger.debug('STD CountWaitingMessagesInQueue')
        # the purpose of this function is to count the number of messages in the queue, but only up to a limit
        # this is used by the polling mechanism which needs to know how many messages are waiting, but it is
        # interested only up to the number of inbound client requests waiting, thus the LIMIT
        await self.get_pool()
        async with self.pool.acquire() as connection:
            async with connection.cursor() as cursor:
                sql = '''\
                    SELECT COUNT(1) 
                    FROM (
                      SELECT 1
                      FROM message_queue
                      WHERE queuename = %s
                      AND accountid = %s
                      AND deleted = 0
                      AND visibilitytimeout < NOW()
                      LIMIT %s
                    ) AS temp
                    ;'''
                params = (
                    str(QueueName),
                    str(AccountId),
                    max_to_count,
                )
                try:
                    #foo = cursor.mogrify(sql, params)
                    await cursor.execute(sql, params)
                    result = await cursor.fetchall()
                    return result[0][0]
                except Exception as e:
                    logger.critical(f"CountWaitingMessagesInQueue ERROR {repr(e)}")

    async def MessageDelete(self, api_request_data):
        logger.debug('STD MessageDelete')
        # it would be more efficient to issue a single SQL statement but it's more simple to reuse MessageDeleteSingle
        for item in api_request_data['ReceiptHandles']:
            await self.MessageDelete({'ReceiptHandle': item})
        response_data = {"MessageDeleteResult": {}}
        return response_data

    async def MessageDeleteSingle(self, api_request_data):
        logger.debug('STD MessageDeleteSingle')
        await self.get_pool()
        async with self.pool.acquire() as connection:
            async with connection.cursor() as cursor:
                sql = '''DELETE FROM message_queue WHERE receipthandle=$1;'''
                params = (
                    api_request_data['ReceiptHandle'],
                )
                try:
                    await cursor.execute('START TRANSACTION')
                    result = await connection.fetchrow(sql, params)
                    await cursor.execute('COMMIT')
                except Exception as e:
                    await cursor.execute('ROLLBACK')
                    logger.critical(f'MessageDeleteSingle: ROLLBACK {repr(e)}')
                response_data = {"MessageDeleteResult": {}}
                return response_data

    async def QueueClear(self, api_request_data):
        logger.debug('STD QueueClear')
        await self.get_pool()
        async with self.pool.acquire() as connection:
            async with connection.cursor() as cursor:
                sql = f'''\
                DELETE FROM message_queue 
                WHERE accountid = %s 
                AND queuename = %s 
                ;'''
                params = (api_request_data['accountid'], api_request_data['queuename'],)
                try:
                    await cursor.execute('START TRANSACTION')
                    await cursor.execute(sql, params)
                    await cursor.execute('COMMIT')
                except Exception as e:
                    await cursor.execute('ROLLBACK')
                    logger.critical(f'QueueClear: ROLLBACK {repr(e)}')
                response_data = {"QueueClearResult": {}}
                return response_data

    async def QueuesList(self, api_request_data):
        logger.debug('STD QueuesList')
        await self.get_pool()
        async with self.pool.acquire() as connection:
            async with connection.cursor() as cursor:
                sql = f'''\
                SELECT accountid, queuename, count(1)
                FROM message_queue
                GROUP BY accountid, queuename
                LIMIT 10000
                ;'''
                queues = []
                try:
                    await cursor.execute(sql)
                    result = await cursor.fetchall()
                    queues = [
                        {'AccountId': str(item[0]), 'QueueName': item[1], 'Count': item[2]} for item in result
                    ]
                except Exception as e:
                    logger.critical(f'QueuesList: ERROR {repr(e)}')
                response_data = {"QueuesListResult": queues}
                return response_data

    async def MaxReceivesExceededTidyupTask(self):
        logger.debug('STD MaxReceivesExceededTidyupTask')
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
        logger.debug('STD MaxReceivesExceededMessageDeletesFromQueue')
        await self.get_pool()
        async with self.pool.acquire() as connection:
            async with connection.cursor() as cursor:
                sql = f'''\
                DELETE
                  FROM message_queue
                  WHERE queuename = %s
                  AND deleted = 0
                  AND accountid = %s
                  AND visibilitytimeout < NOW()
                  AND approximatereceivecount >= %s
                  ;'''
                params = (
                    str(queuename),
                    str(accountid),
                    int(MaxReceives),
                )
                try:
                    await cursor.execute('START TRANSACTION')
                    await cursor.execute(sql, params)
                    await cursor.execute('COMMIT')
                except Exception as e:
                    await cursor.execute('ROLLBACK')
                    logger.critical(f'MaxReceivesExceededMessageDeletesFromQueue: ROLLBACK {repr(e)}')

    async def MessageRetentionPeriodTidyupTask(self):
        print('STD MessageRetentionPeriodTidyupTask')
        await self.get_pool()
        async with self.pool.acquire() as connection:
            async with connection.cursor() as cursor:
                sql = f'''DELETE FROM message_queue WHERE messageretentionperiod < NOW();'''
                try:
                    await cursor.execute('START TRANSACTION')
                    result = await connection.fetchrow(sql)
                    await cursor.execute('COMMIT')
                except Exception as e:
                    await cursor.execute('ROLLBACK')
                    logger.critical(f"MessageRetentionPeriodTidyupTask ROLLBACK {repr(e)}")

    async def MessageReceive(self, api_request_data):
        logger.debug('STD MessageReceive')
        messages = []
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
        logger.debug('STD MessageReceiveSingle')
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
                date_sort_order = 'ASC'
                sql = f'''\
                  SELECT 
                    accountid,
                    approximatefirstreceivetimestamp,
                    approximatereceivecount,
                    md5ofmessagebody,
                    messagebody,
                    BIN_TO_UUID(messageid),
                    queuename,
                    senttimestamp,
                    sequencenumber
                  FROM message_queue
                  WHERE queuename = %s
                  AND accountid = %s
                  AND deleted = 0
                  AND visibilitytimeout < NOW()
                  AND approximatereceivecount < %s
                  ORDER BY senttimestamp {date_sort_order}
                  LIMIT 1
                  FOR UPDATE SKIP LOCKED
                ;'''
                params = (
                    str(api_request_data['queuename']),
                    str(api_request_data['accountid']),
                    api_request_data['MaxReceives'],
                )
                try:
                    await cursor.execute('START TRANSACTION')
                    await cursor.execute(sql, params)
                    result = await cursor.fetchone()
                    if (result == []) or (not result):
                        raise NoMessagesAvailableException('Situation normal, no messages available.')

                    # we prepare the message_data here inside the try/except because the receipt handle
                    # is created here and returned to the database here.  Only needed in MySQL.
                    message_data = {}
                    # yuck ugly I don't like numbered list elements
                    message_data['AccountId'], \
                    message_data['ApproximateFirstReceiveTimestamp'], \
                    message_data['ApproximateReceiveCount'], \
                    message_data['MD5OfMessageBody'], \
                    message_data['MessageBody'], \
                    message_data['MessageId'], \
                    message_data['QueueName'], \
                    message_data['SentTimestamp'] = result
                    # do some transformations
                    message_data['MessageId'] = str(message_data['MessageId'])
                    message_data['AccountId'] = str(message_data['AccountId'])
                    # ReceiptHandle is created here and saved back to the database - only in MySQL
                    message_data['ReceiptHandle'] = str(uuid.uuid4())
                    message_data['SentTimestamp'] = arrow.get(message_data['SentTimestamp']).isoformat()
                    # ApproximateReceiveCount is updated here and saved back to the database - only in MySQL
                    message_data['ApproximateReceiveCount'] += 1
                    if not message_data['ApproximateFirstReceiveTimestamp']:
                        # LISTEN UP! This is where "approximate" comes in. The actual date is set on the database server.
                        # we do this to avoid another round trip just to get the field value
                        # this is specific only to MySQL because we needd two SQL statements to receive message
                        message_data['ApproximateFirstReceiveTimestamp'] = arrow.utcnow().isoformat()
                    else:
                        message_data['ApproximateFirstReceiveTimestamp'] = arrow.get(
                            message_data['ApproximateFirstReceiveTimestamp']).isoformat()

                    sql = f'''\
                    UPDATE message_queue
                    SET 
                        visibilitytimeout = DATE_ADD(NOW(6), INTERVAL %s SECOND), 
                        receipthandle = UUID_TO_BIN(%s),
                        approximatefirstreceivetimestamp = COALESCE(approximatefirstreceivetimestamp, NOW(6)),
                        approximatereceivecount = %s
                    WHERE messageid = UUID_TO_BIN(%s)
                    ;'''

                    params = (
                        api_request_data['VisibilityTimeout'],
                        message_data['ReceiptHandle'],
                        message_data['ApproximateReceiveCount'],
                        message_data['MessageId'],
                    )
                    await cursor.execute(sql, params)
                    await cursor.execute('COMMIT')
                    return message_data
                except NoMessagesAvailableException as e:
                    # normal situation, no messages found
                    await cursor.execute('ROLLBACK')
                except Exception as e:
                    await cursor.execute('ROLLBACK')
                    logger.critical(f"MessageReceive ROLLBACK {repr(e)}")

    async def MessageSend(self, api_request_data):
        logger.debug('STD MessageSend')
        VisibilityTimeout = api_request_data['VisibilityTimeout']
        MessageRetentionPeriod = api_request_data['MessageRetentionPeriod']
        await self.get_pool()
        async with self.pool.acquire() as connection:
            # notice in this SQL we insert NULL if there is MessageDeduplicationTimePeriod == None (explicit comparison)
            sql = f'''\
            INSERT INTO message_queue 
            (accountid, 
            queuename, 
            messagebody, 
            visibilitytimeout, 
            messageretentionperiod, 
            md5ofmessagebody) 
            VALUES (
                %s, 
                %s, 
                %s, 
                DATE_ADD(NOW(6), INTERVAL %s SECOND), 
                DATE_ADD(NOW(6), INTERVAL %s SECOND), 
                %s)
            ;'''

            params = (
                api_request_data['accountid'],
                api_request_data['queuename'],
                api_request_data['MessageBody'],
                VisibilityTimeout,
                MessageRetentionPeriod,
                api_request_data['MD5OfMessageBody'],
            )
            async with connection.cursor() as cursor:
                try:
                    await cursor.execute('START TRANSACTION')
                    await cursor.execute(sql, params)
                    result = await cursor.fetchall()
                except Exception as e:
                    logger.critical(f'MessageSend ROLLBACK {repr(e)}')
                    await cursor.execute('ROLLBACK')
                    response_data = {
                        "MessageSendResult": {
                            "Error": {
                                        "Code": "UnknownError",
                                "Message": f"Unknown error",
                            }
                        }
                    }
                    return response_data

                # MySQL returns only the id of the created record, so a second query is required to return values
                sql = f'''\
                SELECT BIN_TO_UUID(messageid), md5ofmessagebody, sequencenumber 
                FROM message_queue
                WHERE sequencenumber = %s
                ;'''
                lastrowid = cursor.lastrowid
                params = (
                    lastrowid,
                )
                try:
                    await cursor.execute(sql, params)
                    result = await cursor.fetchall()
                    messageid, md5ofmessagebody, sequencenumber = result[0]
                    await cursor.execute('COMMIT')
                # except aiomysql.exceptions.UniqueViolationError:
                except Exception as e:
                    await cursor.execute('ROLLBACK')
                    logger.critical(f'MessageSend ROLLBACK {repr(e)}')
                    response_data = {
                        "MessageSendResult": {
                            "Error": {
                                        "Code": "UnknownError",
                                "Message": f"Unknown database error",
                            }
                        }
                    }
                    return response_data

            response_data = {
                    "MessageSendResult": {
                        "MessageId": messageid,
                        "MD5OfMessageBody": md5ofmessagebody,
                    },
            }
            return response_data

