from .clean_field_std import CleanField as CleanField_std
from starlette.exceptions import HTTPException
import string
import logging

logger = logging.getLogger('starqueue')

logger.debug('CleanField pro')



class CleanField(CleanField_std):

    async def clean_field_Priority(self, field_value):
        logger.debug('PRO clean_field_Priority')
        if not field_value:
            # set default
            return 100
        if not isinstance(field_value, int):
            raise HTTPException(400, detail='Priority field must be an integer between 0 and 1000')
        field_value = int(field_value)
        if not 0 <= field_value <= 1000:
            raise HTTPException(400, detail='Priority field must be an integer between 0 and 1000')
        return field_value

    async def clean_field_MessageDeduplicationId(self, field_value):
        logger.debug('PRO clean_field_MessageDeduplicationId')
        if not field_value:
            # NULL
            return None

        if field_value == '':
            # empty string is not allowed, we replace it with NULL
            return None

        if len(field_value) > 128:
            raise HTTPException(400, detail='MessageDeduplicationId too long (max length is 128 characters)')

        allowed_characters = set(string.ascii_letters + string.digits)
        if [x for x in field_value if x not in allowed_characters]:
            raise HTTPException(400,
                                detail=f'MessageDeduplicationId contains illegal characters, must be in {"".join(sorted(allowed_characters))}')
        return field_value

    async def clean_field_MessageDeduplicationTimePeriod(self, field_value):
        logger.debug('PRO clean_field_MessageDeduplicationTimePeriod')
        if not field_value:
            # default 300 seconds (5 minutes), max 12 hours (43200 seconds)
            return 300
        try:
            field_value = int(field_value)
        except Exception as e:
            raise HTTPException(400, detail="MessageDeduplicationTimePeriod must be an integer")
        if not (0 <= field_value <= 43200):
            raise HTTPException(400, detail="MessageDeduplicationTimePeriod must be an integer between 0-43200")
        return field_value


