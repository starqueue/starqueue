from pymysql.err import (IntegrityError)
import logging
import arrow
import uuid
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
    db_type = 'mysql'

    def __init__(self):
        await encryptionobj.start()
        super().__init__()

    async def MessageChangeVisibility(self, api_request_data):
        logger.debug('PRO MessageChangeVisibility')
        for item in api_request_data['ReceiptHandles']:
            await self.MessageChangeVisibilitySingle(
                {'ReceiptHandle': item, 'VisibilityTimeout': api_request_data['VisibilityTimeout']})
        response_data = {"MessageChangeVisibilityResult": {}}
        return response_data

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
                # UUID must be string form at this point
                ReceiptHandle = str(api_request_data['ReceiptHandle'])

                sql = f'''\
                UPDATE message_queue
                SET visibilitytimeout = DATE_ADD(NOW(6), INTERVAL %s SECOND) 
                WHERE receipthandle = UUID_TO_BIN(%s) 
                AND messagededuplicationid IS NULL 
                AND visibilitytimeout > now()
                ;'''
                params = (
                    VisibilityTimeout,
                    ReceiptHandle,
                )
                try:
                    await cursor.execute('START TRANSACTION')
                    # print(cursor.mogrify(sql, (VisibilityTimeout, ReceiptHandle,)))
                    await cursor.execute(sql, params)
                    await cursor.execute('COMMIT')
                except Exception as e:
                    await cursor.execute('ROLLBACK')
                    logger.critical = f"MessageChangeVisibility ROLLBACK {repr(e)}"

    async def MessageDelete(self, api_request_data):
        logger.debug('PRO MessageDelete')
        # a single SQL statement would more be efficient but it's simpler to repeat MessageDeleteSingle
        for item in api_request_data['ReceiptHandles']:
            await self.MessageDeleteSingle({'ReceiptHandle': item})
        response_data = {"MessageDeleteResult": {}}
        return response_data

    async def MessageDeleteSingle(self, api_request_data):
        logger.debug('PRO MessageDelete')
        await self.get_pool()
        async with self.pool.acquire() as connection:
            async with connection.cursor() as cursor:
                try:
                    await cursor.execute('START TRANSACTION')
                    # UUID must be string form at this point
                    ReceiptHandle = str(api_request_data['ReceiptHandle'])

                    # delete the message, BUT only if the messagededuplicationid column is empty (either NULL or empty string)
                    sql = '''\
                    DELETE FROM message_queue 
                    WHERE coalesce(messagededuplicationid, '') = '' 
                    AND receipthandle=UUID_TO_BIN(%s)
                    ;'''
                    params = (
                        ReceiptHandle,
                    )
                    result = await cursor.execute(sql, params)

                    # messages that have a messagededuplicationid are not deleted, instead their deleted flag is set to 1
                    # so they cannot be received again.
                    # they remain in the queue to enforce the deduplicationid until their messagededuplicationtimeperiod
                    # is over, at which point the Python tidyup task will delete the message
                    messageretentionperiod = 600  # 600 seconds = 10 minutes
                    sql = f'''\
                    UPDATE message_queue 
                    SET 
                        messagebody = '',
                        messageretentionperiod = DATE_ADD(NOW(6), INTERVAL %s SECOND),
                        deleted = 1
                    WHERE receipthandle=UUID_TO_BIN(%s)
                    ;'''
                    params = (
                        messageretentionperiod,
                        ReceiptHandle,
                    )
                    result = await cursor.execute(sql, params)
                    await cursor.execute('COMMIT')
                except Exception as e:
                    await cursor.execute('ROLLBACK')
                    logger.critical(f"MessageDelete ROLLBACK {repr(e)}")
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

    async def MaxReceivesExceededSendToDeadLetterQueue(self, accountid, queuename, MaxReceives, DeadLetterQueueName):
        print('PRO MaxReceivesExceededSendToDeadLetterQueue')
        '''
        This changes for queuename for all messages that exceed MaxReceives to the specified DeadLetterQueueName 
        '''
        await self.get_pool()
        async with self.pool.acquire() as connection:
            async with connection.cursor() as cursor:
                sql = '''\
                  UPDATE message_queue 
                  SET 
                    queuename = %s, 
                    approximatereceivecount = 0, 
                    messagededuplicationid = NULL,  
                    receipthandle = NULL  
                  WHERE queuename = %s
                  AND deleted = 0
                  AND accountid = %s
                  AND visibilitytimeout < NOW()
                  AND approximatereceivecount >= %s
                  ;'''
                params = (
                    DeadLetterQueueName,
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
                if api_request_data['queuename'].endswith('_lifo'):
                    date_sort_order = 'DESC'
                else:
                    date_sort_order = 'ASC'
                sql = f'''\
                  SELECT 
                    accountid,
                    approximatefirstreceivetimestamp,
                    approximatereceivecount,
                    md5ofmessagebody,
                    messagebody,
                    messagededuplicationid,
                    BIN_TO_UUID(messageid),
                    priority,
                    queuename,
                    senttimestamp,
                    sequencenumber
                  FROM message_queue
                  WHERE queuename = %s
                  AND accountid = %s
                  AND deleted = 0
                  AND visibilitytimeout < NOW()
                  AND approximatereceivecount < %s
                  ORDER BY priority,
                  senttimestamp {date_sort_order}
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
                    message_data['MessageDeduplicationId'], \
                    message_data['MessageId'], \
                    message_data['Priority'], \
                    message_data['QueueName'], \
                    message_data['SentTimestamp'] = result

                    #decrypt messagebody
                    message_data['MessageBody'] = await encryptionobj.decrypt(message_data['MessageBody'])

                    # do some transformations
                    message_data['MessageDeduplicationId'] = message_data['MessageDeduplicationId'] or ''
                    message_data['AccountId'] = str(message_data['AccountId'])
                    message_data['MessageId'] = str(message_data['MessageId'])
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
                # notice in this SQL we insert NULL if there is MessageDeduplicationTimePeriod == None (explicit comparison)
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
                VALUES (
                    %s, 
                    %s, 
                    %s, 
                    %s, 
                    DATE_ADD(NOW(6), INTERVAL %s SECOND), 
                    DATE_ADD(NOW(6), INTERVAL %s SECOND), 
                    {'%s' if (MessageDeduplicationId == None) else 'DATE_ADD(NOW(6), INTERVAL %s SECOND)'}, 
                    %s, 
                    %s)
                ;'''

                params = (
                    api_request_data['accountid'],
                    api_request_data['queuename'],
                    api_request_data['MessageBody'],
                    api_request_data['Priority'],
                    VisibilityTimeout,
                    MessageRetentionPeriod,
                    None if (MessageDeduplicationId == None) else MessageDeduplicationTimePeriod,
                    api_request_data['MessageDeduplicationId'],
                    api_request_data['MD5OfMessageBody'],
                )
                try:
                    await cursor.execute('START TRANSACTION')
                    await cursor.execute(sql, params)
                    result = await cursor.fetchall()
                except IntegrityError as e:
                    await cursor.execute('ROLLBACK')
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

                # MySQL returns only the id of the created record, so a second query is required to return values
                sql = f'''\
                SELECT BIN_TO_UUID(messageid), md5ofmessagebody, sequencenumber 
                FROM message_queue
                WHERE sequencenumber = %s
                ;'''
                lastrowid = cursor.lastrowid

                try:
                    await cursor.execute(sql, (lastrowid,))
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
                                "Message": f"Unknown error",
                            },
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
