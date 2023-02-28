from starlette.exceptions import HTTPException
import logging
import pprint
from queueserver.clean_field import clean_field

logger = logging.getLogger('starqueue')
logger.debug('QueuesList std')

class QueuesList():
    required_fields = [
        'Version',
        'accountid',
        'contenttype',
        'ipaddress',
        'metadata',
    ]
    optional_fields = ['queuename']

    async def clean(self, data_to_clean):
        data_to_clean.pop('queuename')
        return await clean_field.do_clean_fields(data_to_clean, data_to_clean.keys())
