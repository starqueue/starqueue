from starlette.exceptions import HTTPException
import logging
import pprint
from queueserver.clean_field import clean_field

logger = logging.getLogger('starqueue')
logger.debug('QueueClear std')

class QueueClear():
    required_fields = [
        'Version',
        'accountid',
        'contenttype',
        'ipaddress',
        'metadata',
        'queuename',
    ]
    optional_fields = []

    async def clean(self, data_to_clean):
        return await clean_field.do_clean_fields(data_to_clean, data_to_clean.keys())

