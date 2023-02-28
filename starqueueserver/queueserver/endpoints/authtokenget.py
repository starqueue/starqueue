from queueserver.auth import authobj
from queueserver.clean_request import clean_request
from starlette.endpoints import HTTPEndpoint
from starlette.responses import JSONResponse
import logging
from db import dbobj
from queueserver.clean_action import AuthTokenGet

logger = logging.getLogger('starqueue')
logger.debug('AuthTokenGet std')

class EndpointAuthTokenGet(HTTPEndpoint):
    async def post(self, request):
        data_to_clean = await clean_request.clean(request, AuthTokenGet.required_fields, AuthTokenGet.optional_fields)
        action = AuthTokenGet()
        api_request_data = await action.clean(data_to_clean)
        #result = await dbobj.GetAccountPasswordHash(data_to_clean)
        await authobj.request_password_check(data_to_clean)  # authenticate request against password
        rv = {'AuthToken':  await authobj.generate_jwt_rs256(api_request_data['accountid'])}
        return JSONResponse(rv, status_code=200)
