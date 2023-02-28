from queueserver.clean_action.MessageChangeVisibility_std import MessageChangeVisibility as MessageChangeVisibility_std
from starlette.exceptions import HTTPException
import logging
from queueserver.clean_field import clean_field

logger = logging.getLogger('starqueue')
logger.debug('MessageChangeVisibility pro')

class MessageChangeVisibility(MessageChangeVisibility_std):

    required_fields = ['VisibilityTimeout', 'ReceiptHandles'] + MessageChangeVisibility_std.required_fields
    optional_fields = [] + MessageChangeVisibility_std.optional_fields

    async def clean(self, data_to_clean):
        # note there is no default value for VisibilityTimeout in this function
        # yes but explaining WHY would help?
        return await clean_field.do_clean_fields(data_to_clean, data_to_clean.keys())


