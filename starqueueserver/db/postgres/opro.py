import asyncpg
import logging
import uuid
import arrow
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

    db_type = 'postgres'


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
            tx = connection.transaction()
            await tx.start()
            VisibilityTimeout = api_request_data['VisibilityTimeout']
            sql = f'''\
            UPDATE message_queue
            SET visibilitytimeout = CURRENT_TIMESTAMP + $1 * interval '1 second'
            WHERE receipthandle = $2 
            AND messagededuplicationid IS NULL 
            AND visibilitytimeout > now()
            ;'''
            try:
                result = await connection.fetchrow(
                    sql,
                    VisibilityTimeout,
                    api_request_data['ReceiptHandle'],
                )
                await tx.commit()
            except Exception as e:
                logger.critical(f"MessageChangeVisibilitySingle ROLLBACK TRANSACTION {repr(e)}")
                await tx.rollback()

    async def MessageDelete(self, api_request_data):
        logger.debug('PRO MessageDelete')
        # a single SQL statement would more be efficient but it's simpler to repeat MessageDeleteSingle
        for item in api_request_data['ReceiptHandles']:
            await self.MessageDeleteSingle({'ReceiptHandle': item})
        response_data = {"MessageDeleteResult": {}}
        return response_data

    async def MessageDeleteSingle(self, api_request_data):
        logger.debug('PRO MessageDeleteSingle')
        await self.get_pool()
        async with self.pool.acquire() as connection:
            tx = connection.transaction()
            await tx.start()
            try:
                # delete the message, BUT only if the messagededuplicationid column is empty (either NULL or empty string)
                sql = '''\
                DELETE FROM message_queue 
                WHERE coalesce(messagededuplicationid, '') = '' 
                AND receipthandle=$1
                ;'''
                params = (
                    api_request_data['ReceiptHandle'],
                )
                result = await connection.execute(sql, *params)

                # messages that have a messagededuplicationid are not deleted, instead their deleted flag is set to 1
                # so they cannot be received again.
                # they remain in the queue to enforce the deduplicationid until their messagededuplicationtimeperiod
                # is over, at which point the Python tidyup task will delete the message
                messageretentionperiod = 600  # 600 seconds = 10 minutes
                sql = f'''\
                UPDATE message_queue 
                SET 
                    messagebody = '',
                    messageretentionperiod = CURRENT_TIMESTAMP + $1 * interval '1 second',
                    deleted = true
                WHERE receipthandle=$2
                ;'''
                params = (
                    messageretentionperiod,
                    api_request_data['ReceiptHandle']
                )
                result = await connection.fetchrow(sql, *params)
                await tx.commit()
            except Exception as e:
                await tx.rollback()
                logger.debug(f"DELETE message ROLLBACK TRANSACTION {repr(e)}")

            response_data = {"MessageDeleteResult": {}}
            return response_data

    async def MaxReceivesExceededTidyupTask(self):
        logger.debug('PRO MaxReceivesExceededTidyupTask')
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
            tx = connection.transaction()
            await tx.start()
            sql = f'''\
                  UPDATE message_queue 
                  SET 
                    queuename = $1, 
                    approximatereceivecount = 0, 
                    messagededuplicationid = NULL,  
                    receipthandle = NULL  
                  WHERE queuename = $2
                  AND deleted = false
                  AND accountid = $3
                  AND visibilitytimeout < NOW()
                  AND approximatereceivecount >= $4
                ;'''
            params = (
                DeadLetterQueueName,
                str(queuename),
                str(accountid),
                int(MaxReceives),
            )
            try:
                result = await connection.fetchrow(sql, *params)
                await tx.commit()
            except Exception as e:
                await tx.rollback()
                logger.critical(f"DeadLetterQueue ROLLBACK {repr(e)}")

    async def MessageReceiveSingle(self, api_request_data):
        logger.debug('PRO MessageReceiveSingle5')
        # update DatabaseQueue.MaxReceives - this defines threshhold for the MaxReceives tidyup task
        x = {
            api_request_data['accountid']: {
                api_request_data['queuename']: {
                    'MaxReceives': api_request_data['MaxReceives'],
                    'DeadLetterQueueName': api_request_data['DeadLetterQueueName'],
                }
            }
        }
        self.MaxReceivesInfoForAllQueues.update(x)
        logger.debug('PRO MessageReceiveSingle4')

        await self.get_pool()
        async with self.pool.acquire() as connection:
            tx = connection.transaction()
            await tx.start()
            logger.debug('PRO MessageReceiveSingle3')
            queuename = api_request_data['queuename']
            accountid = api_request_data['accountid']
            VisibilityTimeout = api_request_data['VisibilityTimeout']
            if queuename.endswith('_lifo'):
                date_sort_order = 'DESC'
            else:
                date_sort_order = 'ASC'
            logger.debug('PRO MessageReceiveSingle2')
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
              ORDER BY priority,
              senttimestamp {date_sort_order}
              FOR UPDATE SKIP LOCKED
              LIMIT 1
            )
            RETURNING 
                accountid,
                approximatefirstreceivetimestamp,
                approximatereceivecount,
                md5ofmessagebody,
                messagebody,
                messagededuplicationid,
                messageid,
                priority,
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
                logger.debug('PRO MessageReceiveSingleX')
                result = await connection.fetchrow(sql, *params)
                logger.debug('PRO MessageReceiveSingle1')
                if (result == []) or (not result):
                    raise NoMessagesAvailableException('Situation normal, no messages available.')
                message_data = {
                    'AccountId': str(result['accountid']),
                    'ApproximateFirstReceiveTimestamp': arrow.get(
                        result['approximatefirstreceivetimestamp']).isoformat(),
                    'ApproximateReceiveCount': result['approximatereceivecount'],
                    'MD5OfMessageBody': result['md5ofmessagebody'],
                    'MessageBody': result['messagebody'],
                    'MessageDeduplicationId': result.get('messagededuplicationid', ''),  # could be None
                    'MessageId': str(result['messageid']),
                    'Priority': result['priority'],
                    'QueueName': result['queuename'],
                    'ReceiptHandle': str(result['receipthandle']),
                    'SentTimestamp': arrow.get(result['senttimestamp']).isoformat(),
                }

                # decrypt messagebody
                message_data['MessageBody'] = await encryptionobj.decrypt(message_data['MessageBody'])

                await tx.commit()
                return message_data
            except NoMessagesAvailableException as e:
                # normal situation, no messages found
                await tx.rollback()
            except Exception as e:
                logger.critical(f"MessageReceive ZUNKNOWN ERROR ROLLBACK TRANSACTION {repr(e)}")
                await tx.rollback()

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
            tx = connection.transaction()
            await tx.start()
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
                $1, 
                $2, 
                $3, 
                $4, 
                CURRENT_TIMESTAMP + $5 * interval '1 second', 
                CURRENT_TIMESTAMP + $6 * interval '1 second', 
                 {'$7' if (MessageDeduplicationId == None) else "CURRENT_TIMESTAMP + $7 * interval '1 second'"}, 
                $8, 
                $9) 
            RETURNING messageid, md5ofmessagebody, sequencenumber
            ;'''
            params = (
                sql,
                str(api_request_data['accountid']),
                api_request_data['queuename'],
                api_request_data['MessageBody'],
                api_request_data['Priority'],
                VisibilityTimeout,
                MessageRetentionPeriod,
                # this inserts NULL if there is no MessageDeduplicationId
                None if (MessageDeduplicationId == None) else MessageDeduplicationTimePeriod,
                api_request_data['MessageDeduplicationId'],
                api_request_data['MD5OfMessageBody'],
            )
            try:
                result = await connection.fetchrow(*params)
                await tx.commit()
            except asyncpg.exceptions.UniqueViolationError:
                await tx.rollback()
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
                logger.critical(f"UNKNOWN DATABASE ERROR IN MESSAGESEND {repr(e)}")
                await tx.rollback()
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
                        "MessageId": str(result['messageid']),
                        "MD5OfMessageBody": result['md5ofmessagebody'],
                    }
            }
            return response_data
