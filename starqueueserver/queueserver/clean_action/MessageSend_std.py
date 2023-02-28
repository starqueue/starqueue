from starlette.exceptions import HTTPException
import logging
import pprint
from queueserver.clean_field import clean_field

logger = logging.getLogger('starqueue')
logger.debug('MessageSend std')


class MessageSend():
    required_fields = [
        'MessageBody',
        'Version',
        'accountid',
        'contenttype',
        'ipaddress',
        'metadata',
        'queuename',
    ]
    optional_fields = ['MessageRetentionPeriod', 'VisibilityTimeout']

    async def clean(self, data_to_clean):
        logger.debug('STD MessageSend.clean')

        '''
        if a VisibilityTimeout has not been provided, then we must set the default for VisibilityTimeout at this point, 
        because VisibilityTimeout is used in MessageChangeVisibility, MessageReceive and MessageSend and the default 
        might vary in each case. 
        The default case when sending a message is VisibilityTimeout=-300 which is 5 minutes ago, which means the 
        message is immediately available for processing.  It is -300 rather than 0 just to ensure the time
        comparison in the MessageReceive SELECT definitely sees VisibilityTimeout as being in the past. It appears
        that on MySQL there were issues with this when VisibilityTimeout in MessageSend was 0. 
    
        Setting VisibilityTimeout to a positive value in MessageSend means that the message is
        created but is invisible to MessageReceive until the number of seconds from now has elasped. 
        '''
        default_VisibilityTimeout = -300
        if data_to_clean['VisibilityTimeout'] is None:
            data_to_clean['VisibilityTimeout'] = default_VisibilityTimeout

        # we create the MD5OfMessageBody and put the message body in it - the clean function will convert it to the md5
        if data_to_clean.get('MessageBody'):
            data_to_clean['MD5OfMessageBody'] = data_to_clean.get('MessageBody', None)

        return await clean_field.do_clean_fields(data_to_clean, data_to_clean.keys())
