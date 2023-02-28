import logging

logger = logging.getLogger('starqueue')
logger.debug('MessageChangeVisibility std')


class MessageChangeVisibility():
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
        pass
