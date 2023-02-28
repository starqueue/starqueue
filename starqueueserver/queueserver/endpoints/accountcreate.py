from queueserver.auth import authobj
from queueserver.clean_request import clean_request
from starlette.endpoints import HTTPEndpoint
from starlette.responses import JSONResponse
import logging
from db import dbobj
from queueserver.clean_action import AccountCreate

logger = logging.getLogger('starqueue')
logger.debug('AccountCreate std')


class EndpointAccountCreate(HTTPEndpoint):
    async def post(self, request):
        logger.debug('EndpointAccountCreate')
        data_to_clean = await clean_request.clean(request, AccountCreate.required_fields, AccountCreate.optional_fields)
        # no email means a guest account
        if not data_to_clean.get('EmailAddress'):
            data_to_clean['EmailAddress'] = 'guest@starqueue.org'
        AccountPassword = await authobj.generate_password()
        data_to_clean['AccountPassword'] = AccountPassword
        accountid = await authobj.generate_accountid()
        data_to_clean['accountid'] = accountid
        action = AccountCreate()
        api_request_data = await action.clean(data_to_clean)
        api_request_data['AccountPasswordHash'] = await authobj.hash_password(data_to_clean['AccountPassword'])
        result = await dbobj.AccountCreate(api_request_data)
        rv = {
            'AccountPassword':  AccountPassword,
            'accountid':  accountid,
            'AuthToken':  await authobj.generate_jwt_rs256(accountid),
        }
        return JSONResponse(rv, status_code=200)

