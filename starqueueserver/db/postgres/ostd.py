import logging
import arrow
import copy
import asyncpg
import asyncio
from db.loadconfig import load
import traceback
import datetime

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

DB_USERNAME, DB_HOST, DB_PORT, DB_PASSWORD, DB_DATABASENAME, DB_TYPE = load()

class DatabaseQueue():

    def __init__(self):
        self.db_type = 'postgres'
        self.MaxReceivesInfoForAllQueues = {}  # contains {accountid: {queuename: (int)MaxReceives}}
        self.pool = None

    async def get_pool(self):
        if not self.pool:
            logger.debug('There is no self.pool, creating')
            await self.create_pool(DB_USERNAME, DB_HOST, DB_PORT, DB_PASSWORD, DB_DATABASENAME)

    async def create_pool(self, DB_USERNAME, DB_HOST, DB_PORT, DB_PASSWORD, DB_DATABASENAME):
        logger.debug(
            f'DB_USERNAME: {DB_USERNAME}, DB_HOST: {DB_HOST}, DB_PORT: {DB_PORT}, DB_DATABASENAME: {DB_DATABASENAME}')
        try:
            self.pool = await asyncpg.create_pool(
                host=DB_HOST,
                port=DB_PORT,
                user=DB_USERNAME,
                password=DB_PASSWORD,
                database=DB_DATABASENAME,
                max_size=20,
            )
            logger.debug('created: ', self.pool)
        except Exception as e:
            logger.debug(repr(e), traceback.format_exc())
        logger.debug('here it is: ', self.pool)
        logger.debug(f'initialising {self.db_type} database connection complete')

    async def shutdown(self):
        await self.pool.close()

    async def CountWaitingMessagesMultiAccount(self, accountids):
        logger.info('STD CountWaitingMessagesMultiAccount')
        # the purpose of this function is to count the number of messages in the queue, but only up to a limit
        # this is used by the polling mechanism which needs to know how many messages are waiting, but it is
        # interested only up to the number of inbound client requests waiting, thus the LIMIT
        await self.get_pool()
        async with self.pool.acquire() as connection:
            sql = '''\
            SELECT foo.queuename, foo.accountid, count(*) AS count
            FROM (SELECT queuename, accountid::text
                              FROM message_queue
                              WHERE deleted = false
                              AND accountid = any($1::uuid[])
                              AND visibilitytimeout < now()
                              ) as foo
            GROUP BY queuename, accountid
            ;'''
            params = (
                accountids,
            )
            try:
                #result = await connection.fetchrow(sql, *params)
                result = await connection.fetch(sql, *params)
                #return result['count']
                return result
            except Exception as e:
                logger.debug(f"CountWaitingMessagesMultiAccount FAILED!! {repr(e)}")


    async def CountWaitingMessagesInQueue(self, AccountId, QueueName):
        logger.info('STD CountWaitingMessagesInQueue')
        # the purpose of this function is to count the number of messages in the queue, but only up to a limit
        # this is used by the polling mechanism which needs to know how many messages are waiting, but it is
        # interested only up to the number of inbound client requests waiting, thus the LIMIT
        await self.get_pool()
        async with self.pool.acquire() as connection:
            sql = '''\
                SELECT COUNT(1) 
                FROM (
                  SELECT 1
                  FROM message_queue
                  WHERE accountid = $1
                  AND queuename = $2
                ) AS temp
                ;'''
            params = (
                AccountId,
                QueueName,
            )
            try:
                result = await connection.fetchrow(sql, *params)
                return result['count']
            except Exception as e:
                logger.debug(f"CountWaitingMessagesInQueue FAILED!! {repr(e)}")

    async def MessageDelete(self, api_request_data):
        logger.debug('STD MessageDelete')
        # it would be more efficient to issue a single SQL statement but it's more simple to reuse MessageDelete
        for item in api_request_data['ReceiptHandles']:
            await self.MessageDeleteSingle({'ReceiptHandle': item})
        response_data = {"MessageDeleteResult": {}}
        return response_data

    async def MessageDeleteSingle(self, api_request_data):
        logger.debug('STD MessageDeleteSingle')
        await self.get_pool()
        async with self.pool.acquire() as connection:
            tx = connection.transaction()
            await tx.start()
            sql = '''DELETE FROM message_queue WHERE receipthandle=$1;'''
            try:
                await connection.fetchrow(sql, api_request_data['ReceiptHandle'])
                await tx.commit()
            except Exception as e:
                logger.debug(f"MessageDelete ROLLBACK TRANSACTION {repr(e)}")
                await tx.ROLLBACK()

            response_data = {"MessageDeleteResult": {}}
            return response_data

    async def QueueClear(self, api_request_data):
        logger.debug('STD QueueClear')
        await self.get_pool()
        async with self.pool.acquire() as connection:
            tx = connection.transaction()
            await tx.start()
            sql = f'''\
            DELETE FROM message_queue 
            WHERE accountid = $1 
            AND queuename = $2 
            ;'''
            params = (
                api_request_data['accountid'],
                api_request_data['queuename'],
            )
            try:
                result = await connection.fetchrow(sql, *params)
                await tx.commit()
            except Exception as e:
                logger.debug(f"QueueClear ROLLBACK TRANSACTION {repr(e)}")
                await tx.ROLLBACK()

            response_data = {"QueueClearResult": {}}
            return response_data

    async def QueuesList(self, api_request_data):
        logger.debug('STD QueuesList')
        await self.get_pool()
        async with self.pool.acquire() as connection:
            sql = f'''\
            SELECT accountid, queuename, count(1)
            FROM message_queue
            GROUP BY accountid, queuename
            LIMIT 10000
            ;'''
            result = await connection.fetch(sql)
            queues = [
                {'AccountId': str(item["accountid"]), 'QueueName': item["queuename"], 'Count': item["count"]} for item
                in
                result
            ]
            response_data = {"QueuesListResult": queues}
            return response_data

    async def MaxReceivesExceededTidyupTask(self):
        logger.debug('STD MaxReceivesExceededTidyupTask')
        '''
        deletes messages that have been received more times than permitted by MaxReceives

        this function is run by the server every N seconds

        DatabaseQueue.MaxReceives holds the details of the queues and the MaxReceives value to apply

        DatabaseQueue.MaxReceives is updated with each inbound request by MessageReceive

        DatabaseQueue.MaxReceives is pruned of values each time this function runs
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
            tx = connection.transaction()
            await tx.start()
            sql = f'''\
                DELETE
                  FROM message_queue
                  WHERE queuename = $1
                  AND deleted = false
                  AND accountid = $2
                  AND visibilitytimeout < NOW()
                  AND approximatereceivecount >= $3
                ;'''
            params = (
                str(queuename),
                str(accountid),
                int(MaxReceives),
            )
            try:
                result = await connection.fetchrow(sql, *params)
                await tx.commit()
            except Exception as e:
                await tx.rollback()
                logger.critical(f"MaxReceivesExceededMessageDeletesFromQueue ROLLBACK {repr(e)}")

    async def MessageRetentionPeriodTidyupTask(self):
        logger.debug('STD MessageRetentionPeriodTidyupTask')
        await self.get_pool()
        async with self.pool.acquire() as connection:
            tx = connection.transaction()
            await tx.start()
            sql = f'''DELETE FROM message_queue WHERE messageretentionperiod < now();'''
            try:
                result = await connection.fetchrow(sql)
                await tx.commit()
            except Exception as e:
                logger.critical(
                    f"STD MessageRetentionPeriodTidyupTask UNKNOWN ERROR DELETING messageretentionperiod ROLLBACK!! {repr(e)}")
                await tx.rollback()

    async def NotificationListen(self, callback):
        logger.debug('STD NotificationListen')

        handler = lambda *args: loop.create_task(self.NotificationHandler(args, callback))
        reconnect_delay  = 0
        conn_check_timeout = 5
        conn_check_interval = 10
        while True:
            try:
                connection = await asyncpg.connect(
                    user=DB_USERNAME,
                    host=DB_HOST,
                    port=DB_PORT,
                    password=DB_PASSWORD,
                    database=DB_DATABASENAME,
                )
                loop = asyncio.get_running_loop()
                await connection.add_listener('message_queue', handler)
                while True:
                    await asyncio.sleep(conn_check_interval)
                    await connection.execute('select 1', timeout=conn_check_timeout)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.debug(repr(e), traceback.format_exc())
                # Probably lost connection, reconnect
                pass
            finally:
                try:
                    await connection.remove_listener('message_queue', handler)
                except Exception as e:
                    logger.debug(repr(e), traceback.format_exc())
                    pass
            if reconnect_delay > 0:
                await asyncio.sleep(reconnect_delay)

    async def NotificationHandler(self, args, callback):
        logger.debug('STD NotificationHandler')
        '''
        callback (callable) –
        A callable receiving the following arguments:
        connection: a Connection the callback is registered with;
        pid: PID of the Postgres server that sent the notification;
        channel: name of the channel the notification was sent to;
        payload: the payload.
        '''
        await callback()

    async def MessageReceive(self, api_request_data):
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
        # update DatabaseQueue.MaxReceives - this defines threshhold for the MaxReceives tidyup task
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
            tx = connection.transaction()
            await tx.start()
            queuename = api_request_data['queuename']
            accountid = api_request_data['accountid']
            VisibilityTimeout = api_request_data['VisibilityTimeout']
            date_sort_order = 'ASC'
            sql = f'''\
            UPDATE message_queue
            SET 
                visibilitytimeout = CURRENT_TIMESTAMP + $1 * interval '1 second', 
                receipthandle = uuid_generate_v4(),
                approximatefirstreceivetimestamp =  COALESCE(approximatefirstreceivetimestamp, now()),
                approximatereceivecount = approximatereceivecount + 1 
            WHERE messageid = (
              SELECT messageid
              FROM message_queue
              WHERE queuename = $2
              AND accountid = $3
              AND deleted = false
              AND visibilitytimeout < now()
              AND approximatereceivecount < $4
              ORDER BY senttimestamp {date_sort_order}
              FOR UPDATE SKIP LOCKED
              LIMIT 1
            )
            RETURNING 
                accountid,
                approximatefirstreceivetimestamp,
                approximatereceivecount,
                md5ofmessagebody,
                messagebody,
                messageid,
                queuename,
                receipthandle,
                senttimestamp,
                sequencenumber
                ;'''
            params = (
                VisibilityTimeout,
                str(queuename),
                str(accountid),
                api_request_data['MaxReceives'],
            )
            try:
                result = await connection.fetchrow(sql, *params)
                if (result == []) or (not result):
                    raise NoMessagesAvailableException('Situation normal, no messages available.')
                message_data = {
                    'AccountId': str(result['accountid']),
                    'ApproximateFirstReceiveTimestamp': arrow.get(
                        result['approximatefirstreceivetimestamp']).isoformat(),
                    'ApproximateReceiveCount': result['approximatereceivecount'],
                    'MD5OfMessageBody': result['md5ofmessagebody'],
                    'MessageBody': result['messagebody'],
                    'MessageId': str(result['messageid']),
                    'QueueName': result['queuename'],
                    'ReceiptHandle': str(result['receipthandle']),
                    'SentTimestamp': arrow.get(result['senttimestamp']).isoformat(),
                }
                await tx.commit()
                return message_data
            except NoMessagesAvailableException as e:
                # normal situation, no messages found
                await tx.rollback()
            except Exception as e:
                logger.critical(f"MessageReceive UNKNOWN ERROR ROLLBACK TRANSACTION {repr(e)}")
                await tx.rollback()

    async def MessageSend(self, api_request_data):
        logger.debug('STD MessageSend')
        VisibilityTimeout = api_request_data['VisibilityTimeout']
        MessageRetentionPeriod = api_request_data['MessageRetentionPeriod']
        await self.get_pool()
        async with self.pool.acquire() as connection:
            tx = connection.transaction()
            await tx.start()

            sql = f'''\
            INSERT INTO message_queue 
            (accountid, 
            queuename, 
            messagebody, 
            visibilitytimeout, 
            messageretentionperiod, 
            md5ofmessagebody) 
            VALUES (
                $1, 
                $2, 
                $3, 
                CURRENT_TIMESTAMP + $4 * interval '1 second', 
                CURRENT_TIMESTAMP + $5 * interval '1 second', 
                $6) 
            RETURNING messageid, md5ofmessagebody, sequencenumber
            ;'''
            params = (
                sql,
                str(api_request_data['accountid']),
                api_request_data['queuename'],
                api_request_data['MessageBody'],
                VisibilityTimeout,
                MessageRetentionPeriod,
                api_request_data['MD5OfMessageBody'],
            )
            try:
                result = await connection.fetchrow(*params)
                await tx.commit()
            except Exception as e:
                logger.critical(f"UNKNOWN DATABASE ERROR IN MESSAGESEND {repr(e)}")
                await tx.rollback()
                response_data = {
                    "MessageSendResult": {
                        "Error": {
                            "Code": "UnknownError",
                            "Message": f"UNKNOWN DATABASE ERROR IN MESSAGESEND",
                        },
                    },
                }
                return response_data

            response_data = {
                "MessageSendResult": {
                    "MessageId": str(result['messageid']),
                    "MD5OfMessageBody": result['md5ofmessagebody'],
                },
            }
            return response_data

    async def GetAccountPasswordHash(self, api_request_data):
        logger.debug('STD GetAccountPasswordHash')
        await self.get_pool()
        async with self.pool.acquire() as connection:
            sql = f'''\
              SELECT accountpasswordhash
              FROM useraccounts
              WHERE accountid = $1
            ;'''
            params = (
                sql,
                str(api_request_data['accountid']),
            )
            return await connection.fetchrow(*params)


    async def GetAccountMessages(self, api_request_data):
        logger.debug('STD GetAccountPasswordHash')
        await self.get_pool()
        async with self.pool.acquire() as connection:
            sql = f'''\
              SELECT accountpasswordhash
              FROM useraccounts
              WHERE accountid = $1
            ;'''
            params = (
                sql,
                str(api_request_data['accountid']),
            )
            return await connection.fetchrow(*params)


    async def AccountCreate(self, api_request_data):
        logger.debug('STD AccountCreate')
        await self.get_pool()
        async with self.pool.acquire() as connection:
            tx = connection.transaction()
            await tx.start()
            sql = f'''\
            INSERT INTO useraccounts 
            (accountid, 
            emailaddress, 
            createdbyipaddress, 
            accountpasswordhash) 
            VALUES (
                $1, 
                $2, 
                $3, 
                $4
                ) 
            ;'''
            params = (
                sql,
                str(api_request_data['accountid']),
                api_request_data['EmailAddress'],
                api_request_data['ipaddress'],
                api_request_data['AccountPasswordHash'],
            )
            try:
                result = await connection.fetchrow(*params)
                await tx.commit()
            except Exception as e:
                logger.critical(f"UNKNOWN DATABASE ERROR IN AccountCreate {repr(e)}")
                await tx.rollback()
                response_data = {
                    "MessageSendResult": {
                        "Error": {
                            "Code": "UnknownError",
                            "Message": f"UNKNOWN DATABASE ERROR IN AccountCreate",
                        },
                    },
                }
                return response_data

            response_data = {
                "AccountCreateResult": {
                },
            }
            return response_data


    async def AccountPasswordChange(self, api_request_data):
        logger.debug('STD AccountPasswordChange')
        await self.get_pool()
        async with self.pool.acquire() as connection:
            tx = connection.transaction()
            await tx.start()
            sql = f'''\
            UPDATE useraccounts 
            SET accountpasswordhash = $1
            WHERE accountid = $2
            ;'''
            params = (
                sql,
                api_request_data['AccountPasswordNew'],
                str(api_request_data['accountid']),
            )
            try:
                result = await connection.fetchrow(*params)
                await tx.commit()
            except Exception as e:
                logger.critical(f"UNKNOWN DATABASE ERROR IN AccountPasswordChange {repr(e)}")
                await tx.rollback()
                response_data = {
                    "MessageSendResult": {
                        "Error": {
                            "Code": "UnknownError",
                            "Message": f"UNKNOWN DATABASE ERROR IN AccountPasswordChange",
                        },
                    },
                }
                return response_data

            response_data = {
                "AccountPasswordChangeResult": {
                },
            }
            return response_data


    async def AccountIncrementMessagesSentCount(self, api_request_data):
        logger.debug('STD AccountIncrementMessagesSentCount')
        await self.get_pool()
        async with self.pool.acquire() as connection:
            try:
                # increment for accountid
                sql = f'''\
                    UPDATE useraccounts 
                    SET messagessentcount = messagessentcount + 1,
                    lastmessagesent = CURRENT_TIMESTAMP 
                    WHERE accountid = $1
                ;'''
                await connection.execute(sql, str(api_request_data['accountid']))
            except Exception as e:
                logger.critical(repr(e), traceback.format_exc())

            try:
                # increment for queuename

                sql = f'''\
                INSERT INTO queuemetadata 
                (accountid, 
                queuename, 
                yearnumber, 
                monthnumber, 
                messagessentcount, 
                lastmessagesent) 
                VALUES (
                    $1, 
                    $2, 
                    EXTRACT(YEAR FROM CURRENT_TIMESTAMP), 
                    EXTRACT(MONTH FROM CURRENT_TIMESTAMP), 
                    1, 
                    CURRENT_TIMESTAMP
                    ) 
                ON CONFLICT (accountid, queuename, yearnumber, monthnumber) 
                DO 
                   UPDATE 
                   SET 
                   messagessentcount = queuemetadata.messagessentcount + 1,
                   lastmessagesent = CURRENT_TIMESTAMP
                   ;
                ;'''

                await connection.execute(
                    sql,
                    str(api_request_data['accountid']),
                    api_request_data['queuename']
                )
            except Exception as e:
                logger.critical(repr(e), traceback.format_exc())


