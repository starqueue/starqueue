from email_validator import validate_email, EmailNotValidError
import asyncio
import concurrent.futures
import hashlib
from starlette.exceptions import HTTPException
import string
import uuid
import logging
import base64
from definitions import VISIBILITYTIMEOUT_MINIMUM, VISIBILITYTIMEOUT_MAXIMUM, MESSAGEBODYLENGTH_MAX, \
    MESSAGEBODYLENGTH_MAX, MESSAGERETENTIONPERIOD_DEFAULT, MESSAGERETENTIONPERIOD_MAX, VERSIONS, \
    PASSWORDLENGTH_MINIMUM, PASSWORDLENGTH_MAXIMUM

logger = logging.getLogger('starqueue')
logger.debug('CleanField std')


class CleanField():

    async def do_clean_fields(self, data_to_clean, fields_to_clean):
        '''
        This cleans each inbound field.
        '''
        logger.debug('STD do_clean_fields')
        # Executes a clean function for each of the fields in field_names
        for field_name in fields_to_clean:
            # clean functions are named 'clean_' plus the name of the field, getattr gets the so-named function
            try:
                clean_function = getattr(self, f'clean_field_{field_name}')
            except AttributeError:
                # if there is no clean function then an unknown field is in the data
                raise HTTPException(400, detail=f'Request must not include unknown fields: {field_name}')
            data_to_clean[field_name] = await clean_function(data_to_clean[field_name])
        return data_to_clean

    async def clean_field_Action(self, field_value):
        logger.debug('STD clean_field_Action')
        if not field_value:
            raise HTTPException(400, detail='Action is required')
        actions = [
            'MessageChangeVisibility',
            'MessageDelete',
            'QueueClear',
            'QueuesList',
            'MessageReceive',
            'MessageSend',
            'AccountCreate',
        ]
        if field_value not in actions:
            raise HTTPException(400, detail='Action is not recognised')
        return field_value

    async def clean_field_recaptcha(self, field_value):
        logger.debug('STD clean_field_recaptcha')
        # just a stub to meet the requirement that his function exists
        return field_value

    async def clean_field_ipaddress(self, field_value):
        logger.debug('STD clean_field_ipaddress')
        # just a stub to meet the requirement that his function exists
        return field_value

    async def clean_field_DeadLetterQueueName(self, field_value):
        logger.debug('STD clean_field_DeadLetterQueueName')
        if not field_value:
            # DeadLetterQueueName is an optional field
            return None

        # it's not ideal because the errror messages contain a different field name, but lets recycle to be dry
        await self.clean_field_queuename(field_value)

        return field_value

    async def clean_field_MD5OfMessageBody(self, field_value):
        logger.debug('STD clean_field_MD5OfMessageBody')
        if not field_value:
            return ''

        def offload_md5():
            return hashlib.md5(field_value.encode('utf-8')).hexdigest()

        # offload the md5 processing to avoid blocking the async loop
        loop = asyncio.get_running_loop()
        with concurrent.futures.ThreadPoolExecutor() as pool:
            field_value = await loop.run_in_executor(pool, offload_md5)
        return field_value

    async def clean_field_MaxNumberOfMessages(self, field_value):
        logger.debug('STD clean_field_MaxNumberOfMessages')
        if not field_value:
            # default 1 message
            return 1
        if not isinstance(field_value, int):
            raise HTTPException(400, detail="MaxNumberOfMessages must be an integer between 1-10")
        if not (1 <= field_value <= 10):
            raise HTTPException(400, detail="MaxNumberOfMessages must be an integer between 1-10")
        return field_value

    async def clean_field_MaxReceives(self, field_value):
        logger.debug('STD clean_field_MaxReceives')
        if not field_value:
            # default 4
            return 4
        if not isinstance(field_value, int):
            raise HTTPException(400, detail="MaxReceives must be an integer between 1-10")
        if not (1 <= field_value <= 10):
            raise HTTPException(400, detail="MaxReceives must be an integer between 1-10")
        return field_value

    async def clean_field_EmailAddress(self, field_value):
        logger.debug('STD clean_field_EmailAddress')
        if not field_value:
            raise HTTPException(400, detail='EmailAddress is required')

        try:
            valid = validate_email(field_value)
            return valid.email
        except EmailNotValidError as e:
            raise HTTPException(400, detail='EmailAddress is not valid')

    async def clean_field_MessageBody(self, field_value):
        logger.debug('STD clean_field_MessageBody')
        if not field_value:
            raise HTTPException(400, detail='MessageBody is required')

        # min length is 1 byte
        if len(field_value.encode('utf-8')) < 1:
            raise HTTPException(400, detail="MessageBody less than minimum 1 byte")

        # max length is 256K
        if len(field_value.encode('utf-8')) > MESSAGEBODYLENGTH_MAX:
            raise HTTPException(400, detail=f'MessageBody exceeds maximum {MESSAGEBODYLENGTH_MAX} bytes')

        try:
            base64.b64decode(field_value, altchars=None, validate=True)
        except:
            raise HTTPException(400, detail='MessageBody must be base64 encoded')

        return field_value

    """
    async def clean_field_MessageBody(self, field_value):
        logger.debug('STD clean_field_MessageBody')
        if not field_value:
            raise HTTPException(400, detail='MessageBody is required')

        ##### VALIDATE INBOUND

        '''
        These Unicode characters are allowed, any others are rejected:
        #x9 | #xA | #xD | #x20 to #xD7FF | #xE000 to #xFFFD | #x10000 to #x10FFFF
        Refer: http://www.w3.org/TR/REC-xml/#charsets
        
        Useful info on unicode:
        https://stackoverflow.com/a/27416004
        
        https://stackoverflow.com/a/28152666
        Notice in the above post the distinction between XML1.0 and XML1.1
        
        The rules here appear to be the XML1.0 restrictions PLUS [#x10000-#x10FFFF]
        
        _illegal_xml_chars_RE = re.compile(u'[\x00-\x08\x0b\x0c\x0e-\x1F\uD800-\uDFFF\uFFFE\uFFFF]')
        
        We validate by pushing the message body through an XML parser.
        Any invalid character will be reported as an invalid token, making the message body invalid.    
        
        Due to security risks we use defusedxml as advised here: https://docs.python.org/3/library/xml.html#defused-packages
        https://pypi.org/project/defusedxml/
        
        
        If the parsing solution becomes a problem maybe look at using a regex to detect invalid chars.
        Good thing about this approach is it inverts not to check valid but to find invalid chars:
        https://lsimons.wordpress.com/2011/03/17/stripping-illegal-characters-out-of-xml-in-python/
        
        Notice "RestrictedChar" seems to define illegal chars in here: https://www.w3.org/TR/xml11/#charsets
        [2a]   	RestrictedChar	   ::=   	[#x1-#x8] | [#xB-#xC] | [#xE-#x1F] | [#x7F-#x84] | [#x86-#x9F]
        This might be useful if switching away from parsing.
        '''
        # there should be no other failures than invalid token
        critical_message = 'MessageBody CRITICAL ERROR UNEXPECTED PARSE FAILURE MUST BE INVESTIGATED'

        def parse():
            # remove anything that might close a tag i.e angle brackets
            string_to_test = re.sub('[><]', '', field_value)
            # parse as XML
            ET.fromstring(f'''<?xml version="1.0"?><data><![CDATA[{string_to_test}]]></data>''')

        # 'regex' or 'xmlparser' - both seem to work
        validation_method = 'regex'

        def xmlparse():
            # remove anything that might close a tag i.e angle brackets
            string_to_test = re.sub('[><]', '', field_value)
            # parse as XML
            ET.fromstring(f'''<?xml version="1.0"?><data><![CDATA[{string_to_test}]]></data>''')

        if validation_method == 'xmlparser':
            try:
                # avoid blocking the potentially time consuming xml parsing
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, parse)
            except ParseError as e:
                if 'not well-formed (invalid token)' in repr(e):
                    raise HTTPException(400, detail="MessageBody contains characters outside the allowed set")
                # there should be no parse error apart from invalid token
                raise HTTPException(400, detail=critical_message)
            except Exception as e:
                # there should be no parse error apart from invalid token
                raise HTTPException(400, detail=critical_message)

        def do_regex():  # blocking
            _illegal_xml_chars_RE = re.compile(u'[\x00-\x08\x0b\x0c\x0e-\x1F\uD800-\uDFFF\uFFFE\uFFFF]')
            return _illegal_xml_chars_RE.search(field_value)

        if validation_method == 'regex':
            loop = asyncio.get_running_loop()
            with concurrent.futures.ThreadPoolExecutor() as pool:
                result = await loop.run_in_executor(pool, do_regex)
                if result:
                    raise HTTPException(400, detail="MessageBody contains characters outside the allowed set")

        return field_value
    """

    async def clean_field_MessageRetentionPeriod(self, field_value):
        logger.debug('STD clean_field_MessageRetentionPeriod')
        if not field_value:
            return MESSAGERETENTIONPERIOD_DEFAULT
        if not isinstance(field_value, int):
            raise HTTPException(400, detail="MessageRetentionPeriod must be an integer")
        if not (60 <= field_value <= MESSAGERETENTIONPERIOD_MAX):
            raise HTTPException(400,
                                detail=f"MessageRetentionPeriod must be an integer between 60-{MESSAGERETENTIONPERIOD_MAX}")
        return field_value

    async def clean_field_metadata(self, field_value):
        logger.debug('STD clean_field_metadata')
        # metadata is a system generated value
        return field_value

    async def clean_field_AuthToken(self, field_value):
        logger.debug('STD clean_field_AuthToken')
        # this is here because all fields must have a clean field function
        return field_value

    async def clean_field_AccountPassword(self, field_value):
        logger.debug('STD clean_field_AccountPassword')
        if not field_value:
            return None

        if len(field_value) < PASSWORDLENGTH_MINIMUM:
            raise HTTPException(400, detail=f'AccountPassword length must be minimum {PASSWORDLENGTH_MINIMUM}')

        if len(field_value) > PASSWORDLENGTH_MAXIMUM:
            raise HTTPException(400, detail=f'AccountPassword length must not be greater than {PASSWORDLENGTH_MAXIMUM}')

        special_characters = '-_:;.=+%*'
        allowed_characters = set(string.ascii_letters + string.digits + special_characters)
        if [x for x in field_value if x not in allowed_characters]:
            raise HTTPException(400,
                                detail=f'''AccountPassword contains illegal characters, must be in {''.join(sorted(allowed_characters))}''')

        if not any(char.isdigit() for char in field_value):
            raise HTTPException(400, detail='AccountPassword must contain at least one number')

        if not any(char.isupper() for char in field_value):
            raise HTTPException(400, detail='AccountPassword must contain at least one uppercase letter')

        if not any(char.islower() for char in field_value):
            raise HTTPException(400, detail='AccountPassword must contain at least one lowercase letter')

        return field_value

    async def clean_field_ReceiptHandle(self, field_value):
        logger.debug('STD clean_field_ReceiptHandle')
        if not field_value:
            raise HTTPException(400, detail="ReceiptHandle is required")
        try:
            field_value = uuid.UUID(field_value)
        except Exception as e:
            raise HTTPException(400, detail="ReceiptHandle must be a valid UUID")
        return field_value

    async def clean_field_ReceiptHandles(self, field_value):
        logger.debug('STD clean_field_ReceiptHandles')
        if not field_value:
            raise HTTPException(400, detail="ReceiptHandles is required")
        try:
            field_value = [uuid.UUID(x) for x in field_value]
            # remove duplicates
            field_value = list(set(field_value))
        except Exception as e:
            raise HTTPException(400, detail="ReceiptHandles not valid, must be an array of UUIDs")
        if len(field_value) > 10:
            raise HTTPException(400, detail="ReceiptHandles not valid, you may provide no more than 10")
        if len(field_value) < 1:
            raise HTTPException(400, detail="ReceiptHandles not valid, you must provide at least 1")
        return field_value

    async def clean_field_Version(self, field_value):
        logger.debug('STD clean_field_Version')
        if not field_value:
            return "1"
        if field_value not in VERSIONS:
            raise HTTPException(400, detail=f'Version invalid.')
        return field_value

    async def clean_field_VisibilityTimeout(self, field_value):
        logger.debug('STD clean_field_VisibilityTimeout')
        if not field_value:
            # Note the default value for VisibilityTimeout differs depending on which function
            # we are in, so it is up to the clean action to set the default
            raise HTTPException(400, detail="VisibilityTimeout is required")
        if not isinstance(field_value, int):
            raise HTTPException(
                400,
                detail=f'VisibilityTimeout must be an integer between {VISIBILITYTIMEOUT_MINIMUM}-{VISIBILITYTIMEOUT_MAXIMUM}')
        if not (VISIBILITYTIMEOUT_MINIMUM <= field_value <= VISIBILITYTIMEOUT_MAXIMUM):
            raise HTTPException(
                400,
                detail=f'VisibilityTimeout must be an integer between {VISIBILITYTIMEOUT_MINIMUM}-{VISIBILITYTIMEOUT_MAXIMUM}')
        return field_value

    async def clean_field_WaitTimeSeconds(self, field_value):
        logger.debug('STD clean_field_WaitTimeSeconds')
        if not field_value:
            # default 1 message
            return 20
        if not isinstance(field_value, int):
            raise HTTPException(400, detail="WaitTimeSeconds must be an integer between 1-20")
        if not (1 <= field_value <= 20):
            raise HTTPException(400, detail="WaitTimeSeconds must be an integer between 1-20")
        return field_value

    async def clean_field_accountid(self, field_value):
        logger.debug('STD clean_field_accountid')
        if not field_value:
            raise HTTPException(400, detail="accountid is required")
        try:
            if len(field_value) != 36:
                raise
        except Exception as e:
            raise HTTPException(400, detail="accountid must be length 36 characters")
        try:
            field_value = uuid.UUID(field_value)
        except Exception as e:
            raise HTTPException(400, detail="accountid must be a valid UUID")
        # notice again we force it to string
        return str(field_value)

    async def clean_field_contenttype(self, field_value):
        logger.debug('STD clean_field_contenttype')
        if field_value != 'application/json':
            raise HTTPException(400, detail='Content-Type must be application/json')
        return field_value

    async def clean_field_queuename(self, field_value):
        logger.debug('STD clean_field_queuename')
        if len(field_value) < 1:
            raise HTTPException(400, detail='Queue name too short (< 1 character)')

        if len(field_value) > 80:
            raise HTTPException(400, detail='Queue name too long (> 80 characters)')

        allowed_characters = set(string.ascii_letters + string.digits + '_' + '-')
        if [x for x in field_value if x not in allowed_characters]:
            raise HTTPException(400,
                                detail=f'Queue name contains illegal characters, must be in {"".join(sorted(allowed_characters))}')
        return field_value
