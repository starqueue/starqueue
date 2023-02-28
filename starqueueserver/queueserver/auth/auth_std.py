import hashlib, binascii
import logging
import os
from starlette.exceptions import HTTPException
from db import dbobj
from passwordgenerator import pwgenerator
import uuid
from definitions import JWTKEY, PASSWORDLENGTH_MAXIMUM
import jwt
import time
import traceback

logger = logging.getLogger('starqueue')
logger.debug('auth std')

class Auth():

    async def start(self):
        pass

    async def authenticate_request(self, request):
        try:
            form = await request.json()
            # get the token, removing the 'Bearer ' prefix
            AuthToken = request.headers['Authorization'].partition('Bearer ')[2].encode('utf-8')
            accountid = request.path_params['accountid']
            await self.verify_jwt_rs256(accountid, AuthToken)
            print('AUTH OK VIA HEADER')
        except Exception as e:
            print('AUTH NOT OK VIA HEADER', repr(e))
            raise HTTPException(403, detail=f'access denied')

    async def generate_jwt_rs256(self, accountid):
        try:
            with open('/opt/starqueueserver/queueserver/auth/private-key.pem', 'rb') as f:
                key = f.read()
                data = {
                    "accountid": accountid,
                    "time": time.time(),
                }
                encoded = jwt.encode(data, key, algorithm="RS256")
        except Exception as e:
            print(repr(e), traceback.format_exc())
            raise HTTPException(400, detail=f'error in generate_jwt')
        return encoded

    async def verify_jwt_rs256(self, accountid, AuthToken):
        try:
            with open('/opt/starqueueserver/queueserver/auth/public-key.pem', 'rb') as f:
                key = f.read()
                decoded = jwt.decode(AuthToken, key, algorithms="RS256")
        except Exception as e:
            print(repr(e), traceback.format_exc())
            raise HTTPException(403, detail=f'access denied')

        if decoded['accountid'] != accountid:
            raise HTTPException(403, detail=f'access denied')
    '''
    async def generate_jwt(self, accountid):
        try:
            data = {
                "accountid": accountid,
                "time": time.time(),
            }
            encoded = jwt.encode(data, JWTKEY, algorithm="HS256")
        except Exception as e:
            print(repr(e), traceback.format_exc())
            raise HTTPException(400, detail=f'error in generate_jwt')
        return encoded

    async def verify_jwt(self, accountid, AuthToken):
        try:
            decoded = jwt.decode(AuthToken, JWTKEY, algorithms="HS256")
        except Exception as e:
            print(repr(e), traceback.format_exc())
            raise HTTPException(403, detail=f'error decoding JWT')

        if decoded['accountid'] != accountid:
            raise HTTPException(403, detail=f'access denied')
    '''

    async def generate_accountid(self):
        return str(uuid.uuid4())

    async def generate_password(self):
        password = pwgenerator.pw(
            number_of_elements=3,
            no_special_characters=False,
            min_word_length=5,
            max_int_value=999,
        )
        return password[:PASSWORDLENGTH_MAXIMUM]

    async def hash_password(self, password):
        try:
            salt = hashlib.sha256(os.urandom(60)).hexdigest().encode('ascii')
            pwdhash = hashlib.pbkdf2_hmac('sha512', password.encode('utf-8'), salt, 100000)
            pwdhash = binascii.hexlify(pwdhash)
            return (salt + pwdhash).decode('ascii')
        except:
            raise HTTPException(400, detail=f'error in hash_password')

    async def request_password_check(self, api_request_data):
        logger.info('request_password_check')
        result = await dbobj.GetAccountPasswordHash(api_request_data)
        if not result:
            # database result is None, accountid does not exist
            raise HTTPException(403, detail=f'access denied')

        stored_password_hash = result['accountpasswordhash']
        if not stored_password_hash:
            raise HTTPException(403, detail=f'access denied')

        try:
            result = await self.verify_password(stored_password_hash, api_request_data['AccountPassword'])
            if result != True:
                raise
        except:
            raise HTTPException(403, detail=f'access denied')

    async def verify_password(self, stored_password_hash, provided_password):
        try:
            if not stored_password_hash:
                return False
            if not provided_password:
                return False
            portion_salt = stored_password_hash[:64]
            portion_password = stored_password_hash[64:]
            pwdhash = hashlib.pbkdf2_hmac('sha512', provided_password.encode('utf-8'), portion_salt.encode('ascii'), 100000)
            pwdhash = binascii.hexlify(pwdhash).decode('ascii')
            return pwdhash == portion_password
        except:
            raise HTTPException(403, detail=f'access denied')

