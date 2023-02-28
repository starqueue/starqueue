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
        action = AccountCreate()
        api_request_data = await action.clean(data_to_clean)
        data_to_clean['AccountPassword'] = await authobj.hash_password(data_to_clean['AccountPassword'])
        result = await dbobj.AccountCreate(api_request_data)
        return JSONResponse(result, status_code=200)

