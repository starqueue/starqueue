from queueserver.clean_action.MessageSend_std import MessageSend as MessageSend_std
from starlette.exceptions import HTTPException
import logging
from queueserver.clean_field import clean_field

logger = logging.getLogger('starqueue')
logger.debug('MessageSend pro')

class MessageSend(MessageSend_std):
    pro_fields = ['MessageDeduplicationId','MessageDeduplicationTimePeriod','Priority']
    optional_fields = [] + MessageSend_std.optional_fields + pro_fields
    required_fields = [] + MessageSend_std.required_fields

    async def clean(self, data_to_clean):
        logger.debug('PRO MessageSend.clean')
        ######### IF NOT PRO REQUEST
        # it's a pro request if it contains pro_fields that have something in them other than None
        is_pro_request = False
        for field in self.pro_fields:
            if data_to_clean[field] is not None:
                is_pro_request = True
                break

        if not is_pro_request:
            return await super().clean(data_to_clean)
        ######### /IF NOT PRO REQUEST

        # we create the MD5OfMessageBody and put the message body in it - the clean function will convert it to the md5
        if data_to_clean.get('MessageBody'):
            data_to_clean['MD5OfMessageBody'] = data_to_clean.get('MessageBody', None)

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
        logger.debug('PRO MessageSend.cleanqwdqwdq')
        if data_to_clean['VisibilityTimeout'] is None:
            logger.debug('PRO MessageSend.cleanqwdqwdqasca')
            data_to_clean['VisibilityTimeout'] = default_VisibilityTimeout
        logger.debug('PRO MessageSend.erwe')

        # MessageDeduplicationId must be scoped to the queue
        if data_to_clean.get('MessageDeduplicationId', None):
            data_to_clean['MessageDeduplicationId'] = \
                f"{data_to_clean['accountid']}/{data_to_clean['queuename']}/{data_to_clean['MessageDeduplicationId']}"

        # if there is no MessageDeduplicationId then set MessageDeduplicationTimePeriod to None
        if not data_to_clean.get('MessageDeduplicationId', None):  # if not matches None or empty string ''
            data_to_clean['MessageDeduplicationTimePeriod'] = None
            data_to_clean['VisibilityTimeout'] = default_VisibilityTimeout

        return await clean_field.do_clean_fields(data_to_clean, data_to_clean.keys())

