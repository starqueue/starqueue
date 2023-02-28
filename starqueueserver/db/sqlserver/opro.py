import logging
import arrow
import uuid
import traceback
from .ostd import DatabaseQueue as DatabaseQueue_std
import copy
from queueserver.encryption import encryptionobj

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

class DatabaseQueue(DatabaseQueue_std):

    db_type = 'sqlserver'

    def __init__(self):
        await encryptionobj.start()
        super().__init__()


    async def MessageChangeVisibilitySingle(self, api_request_data):
        logger.debug('PRO MessageChangeVisibilitySingle')

        # if the message record has a visibilitytimeout that is in the past, then the message is not in flight

        # it is not possible to change messages that are not in flight, so there is no effect in such case

        # if the receipthandle is not valid for any reason then no record will be found, so there is no effect in that case

        # note that MessageChangeVisibility is calculated from now(), not from the existing visibilitytimeout in the db

        # if the message has a MessageDeduplicationId, MessageChangeVisibility returns successful but has no effect

        await self.get_pool()
        async with self.pool.acquire() as connection:
            async with connection.cursor() as cursor:
                VisibilityTimeout = api_request_data['VisibilityTimeout']
                sql = f'''\
                UPDATE message_queue
                SET visibilitytimeout = DATEADD(second, ?, CURRENT_TIMESTAMP)
                WHERE receipthandle = ? 
                AND messagededuplicationid IS NULL 
                AND visibilitytimeout >  SYSUTCDATETIME()
                '''
                params = (
                    VisibilityTimeout,
                    api_request_data['ReceiptHandle'],
                )
                try:
                    await cursor.execute('BEGIN TRANSACTION')
                    await cursor.execute(sql, params)
                    await cursor.execute('COMMIT TRANSACTION')
                except Exception as e:
                    await cursor.execute('ROLLBACK TRANSACTION')
                    logger.critical(f"MessageChangeVisibilitySingle ROLLBACK TRANSACTION {repr(e)}")

    async def MessageChangeVisibility(self, api_request_data):
        logger.debug('PRO MessageChangeVisibility')
        for item in api_request_data['ReceiptHandles']:
            await self.MessageChangeVisibilitySingle({'ReceiptHandle': item, 'VisibilityTimeout': api_request_data['VisibilityTimeout']})
        response_data = {"MessageChangeVisibilityResult": {}}
        return response_data

    async def MessageDeleteSingle(self, api_request_data):
        logger.debug('PRO MessageDeleteSingle')
        await self.get_pool()
        async with self.pool.acquire() as connection:
            async with connection.cursor() as cursor:
                try:
                    await cursor.execute('BEGIN TRANSACTION')
                    # delete the message, BUT only if the messagededuplicationid column is empty (either NULL or empty string)
                    sql = '''\
                        DELETE FROM message_queue 
                        WHERE coalesce(messagededuplicationid, '') = '' 
                        AND receipthandle = ?'''
                    params = (
                        api_request_data['ReceiptHandle'],
                    )
                    await cursor.execute(sql, params)

                    # messages that have a messagededuplicationid are not deleted, instead their deleted flag is set to 1
                    # so they cannot be received again.
                    # they remain in the queue to enforce the deduplicationid until their messagededuplicationtimeperiod
                    # is over, at which point the Python tidyup task will delete the message
                    messageretentionperiod = 600  # 600 seconds = 10 minutes
                    sql = f'''\
                    UPDATE message_queue 
                    SET 
                        messagebody = '',
                        messageretentionperiod = DATEADD(second, ?, CURRENT_TIMESTAMP),
                        deleted = 1
                    WHERE receipthandle = ?'''
                    params = (
                        messageretentionperiod,
                        api_request_data['ReceiptHandle'],
                    )
                    await cursor.execute(sql, params)
                    await cursor.execute('COMMIT TRANSACTION')
                except Exception as e:
                    await cursor.execute('ROLLBACK TRANSACTION')
                    logger.debug(f"DELETE message ROLLBACK TRANSACTION {repr(e)}")
            response_data = {"MessageDeleteResult": {}}
            return response_data

    async def MessageDelete(self, api_request_data):
        logger.debug('PRO MessageDelete')
        # a single SQL statement would more be efficient but it's simpler to repeat MessageDeleteSingle
        for item in api_request_data['ReceiptHandles']:
            await self.MessageDeleteSingle({'ReceiptHandle': item})
        response_data = {"MessageDeleteResult": {}}
        return response_data

    async def MaxReceivesExceededTidyupTask(self):
        logger.debug('PRO MaxReceivesExceededTidyupTask')
        '''
        deletes messages that have been received more times than permitted by MaxReceives

        this function is run by the server every N seconds

        self.MaxReceivesInfoForAllQueues holds the details of the queues and the MaxReceives value to apply

        self.MaxReceivesInfoForAllQueues is updated with each inbound request by MessageReceive

        self.MaxReceivesInfoForAllQueues is pruned of values each time this function runs
        '''
        # we copy it because we will be mutating the original
        copy_MaxReceivesInfoForAllQueues = copy.deepcopy(self.MaxReceivesInfoForAllQueues)
        try:
            for accountid in copy_MaxReceivesInfoForAllQueues.keys():
                for queuename in copy_MaxReceivesInfoForAllQueues[accountid].keys():
                    item = copy_MaxReceivesInfoForAllQueues[accountid][queuename]
                    MaxReceives = item['MaxReceives']
                    DeadLetterQueueName = item.get('DeadLetterQueueName', None)

                    # remove queue from the MaxReceives - this prevents memory leak for large variety of queuenames
                    # we do this BEFORE carrying out the deletions
                    del self.MaxReceivesInfoForAllQueues[accountid][queuename]
                    # and if no queue names left under the 'accountid' key then remove that too
                    if not bool(self.MaxReceivesInfoForAllQueues[accountid]):
                        del self.MaxReceivesInfoForAllQueues[accountid]

                    if DeadLetterQueueName is None:
                        await self.MaxReceivesExceededMessageDeletesFromQueue(accountid,
                                                                              queuename,
                                                                              MaxReceives)
                    else:
                        await self.MaxReceivesExceededSendToDeadLetterQueue(accountid,
                                                                            queuename,
                                                                            MaxReceives,
                                                                            DeadLetterQueueName)
        except Exception as e:
            print('repr(e)')
            print(repr(e), traceback.format_exc())

    async def MaxReceivesExceededSendToDeadLetterQueue(self, accountid, queuename, MaxReceives, DeadLetterQueueName):
        logger.debug('PRO MaxReceivesExceededSendToDeadLetterQueue')
        '''
        This changes for queuename for all messages that exceed MaxReceives to the specified DeadLetterQueueName 
        '''
        await self.get_pool()
        async with self.pool.acquire() as connection:
            async with connection.cursor() as cursor:
                sql = '''\
                  UPDATE message_queue 
                  SET 
                    queuename = ?, 
                    approximatereceivecount = 0, 
                    messagededuplicationid = NULL,  
                    receipthandle = NULL  
                  WHERE queuename = ?
                  AND deleted = 0
                  AND accountid = ?
                  AND visibilitytimeout < SYSUTCDATETIME()
                  AND approximatereceivecount >= ?
                  ;'''
                params = (
                    DeadLetterQueueName,
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
                    logger.critical(f'MaxReceivesExceededSendToDeadLetterQueue: ROLLBACK {repr(e)}')

    async def MessageReceiveSingle(self, api_request_data):
        logger.debug('PRO MessageReceiveSingle')
        # update self.MaxReceivesInfoForAllQueues - this defines threshhold for the MaxReceives tidyup task
        x = {
            api_request_data['accountid']: {
                api_request_data['queuename']: {
                    'MaxReceives': api_request_data['MaxReceives'],
                    'DeadLetterQueueName': api_request_data['DeadLetterQueueName'],
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
                if queuename.endswith('_lifo'):
                    date_sort_order = 'DESC'
                else:
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
                    INSERTED.messagededuplicationid,
                    INSERTED.messageid,
                    INSERTED.priority,
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
                  ORDER BY priority,
                  senttimestamp {date_sort_order}
                )'''
                params = (
                    VisibilityTimeout,
                    str(queuename),
                    str(accountid),
                    api_request_data['MaxReceives'],
                )
                result = None
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
                    message_data['MessageDeduplicationId'] = result.messagededuplicationid
                    message_data['MessageId'] = result.messageid
                    message_data['Priority'] = result.priority
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

                    # decrypt messagebody
                    message_data['MessageBody'] = await encryptionobj.decrypt(message_data['MessageBody'])

                    await cursor.execute('COMMIT TRANSACTION')
                    return message_data
                except NoMessagesAvailableException as e:
                    # normal situation, no messages found
                    await cursor.execute('ROLLBACK TRANSACTION')
                except Exception as e:
                    logger.critical(f"MessageReceive UNKNOWN ERROR ROLLBACK TRANSACTION {repr(e)}")
                    await cursor.execute('ROLLBACK TRANSACTION')

    async def MessageSend(self, api_request_data):
        logger.debug('PRO MessageSend')
        pro_fields = [
            'MessageDeduplicationId',
            'MessageDeduplicationTimePeriod',
            'Priority',
        ]

        # encrypt the message body
        api_request_data['MessageBody'] = await encryptionobj.encrypt(api_request_data['MessageBody'])

        # it's a pro request if it contains pro_fields
        is_pro_request = bool([x for x in api_request_data.keys() if x in pro_fields])
        if not is_pro_request:
            return await super().MessageSend(api_request_data)

        MessageDeduplicationId = api_request_data['MessageDeduplicationId']
        MessageDeduplicationTimePeriod = api_request_data['MessageDeduplicationTimePeriod']
        VisibilityTimeout = api_request_data['VisibilityTimeout']
        MessageRetentionPeriod = api_request_data['MessageRetentionPeriod']
        await self.get_pool()
        async with self.pool.acquire() as connection:
            async with connection.cursor() as cursor:
                MessageDeduplicationTimePeriod_string = None if (
                            MessageDeduplicationId == None) else MessageDeduplicationTimePeriod
                MessageDeduplicationTimePeriod_value = '?' if (
                            MessageDeduplicationId == None) else "DATEADD(second, ?, CURRENT_TIMESTAMP)"

                sql = f'''\
                INSERT INTO message_queue 
                (accountid, 
                queuename, 
                messagebody, 
                priority, 
                visibilitytimeout, 
                messageretentionperiod, 
                messagededuplicationtimeperiod, 
                messagededuplicationid, 
                md5ofmessagebody) 
                OUTPUT INSERTED.messageid, INSERTED.md5ofmessagebody, INSERTED.sequencenumber
                VALUES (
                    ?, 
                    ?, 
                    ?, 
                    ?, 
                    DATEADD(second, ?, CURRENT_TIMESTAMP), 
                    DATEADD(second, ?, CURRENT_TIMESTAMP), 
                    {MessageDeduplicationTimePeriod_value}, 
                    ?, 
                    ?)'''
                params = (
                    str(api_request_data['accountid']),
                    api_request_data['queuename'],
                    api_request_data['MessageBody'],
                    api_request_data['Priority'],
                    VisibilityTimeout,
                    MessageRetentionPeriod,
                    # this inserts NULL if there is no MessageDeduplicationId
                    MessageDeduplicationTimePeriod_string,
                    api_request_data['MessageDeduplicationId'],
                    api_request_data['MD5OfMessageBody'],
                )
                try:
                    await cursor.execute('BEGIN TRANSACTION')
                    await cursor.execute(sql, params)
                    result = await cursor.fetchone()
                    await cursor.execute('COMMIT')
                    '''
                    TODO REPLACE WITH CORRECT EXCEPTION
                    except asyncpg.exceptions.UniqueViolationError:
                        await cursor.execute('ROLLBACK TRANSACTION')
                        response_data = {
                            "MessageSendResult": {
                                "Error": {
                                    "Type": "Sender",
                                    "Code": "DuplicateMessage",
                                    "Message": f"Duplicate message. MessageDeduplicationId is: {api_request_data['MessageDeduplicationId']}",
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
                                "Message": f"Unknown database error",
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


