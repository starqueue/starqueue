from starlette.exceptions import HTTPException
import logging
import pprint
from queueserver.clean_field import clean_field

logger = logging.getLogger('starqueue')
logger.debug('MessageReceive std')


class MessageReceive():
    required_fields = [
        'Version',
        'accountid',
        'contenttype',
        'ipaddress',
        'metadata',
        'queuename',
    ]
    optional_fields = [
        'DeadLetterQueueName',
        'MaxNumberOfMessages',
        'MaxReceives',
        'VisibilityTimeout',
        'WaitTimeSeconds',
    ]

    async def clean(self, data_to_clean):
        logger.debug('STD MessageReceive.clean')

        '''
        if a VisibilityTimeout has not been provided, then we must set the default for VisibilityTimeout at this point, 
        because VisibilityTimeout is used in MessageChangeVisibility, MessageReceive and MessageSend and the default 
        might vary in each case. 
        The default case when receiving a message is VisibilityTimeout=30 which means the message is hidden 
        from further receives for 30 seconds.  
        '''
        if data_to_clean['VisibilityTimeout'] is None:
            data_to_clean['VisibilityTimeout'] = 30

        # we do this check after validation because we have to compare to another field (queuename)
        if data_to_clean['DeadLetterQueueName'] is not None:
            if data_to_clean['DeadLetterQueueName'] == data_to_clean['queuename']:
                message = f'''The DeadLetterQueueName ({data_to_clean['DeadLetterQueueName']}) must not be the same as the queuename ({data_to_clean['queuename']})'''
                raise HTTPException(400, detail=message)
        logger.debug(data_to_clean)

        return await clean_field.do_clean_fields(data_to_clean, data_to_clean.keys())
