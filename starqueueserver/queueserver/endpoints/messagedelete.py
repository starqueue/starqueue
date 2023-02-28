
from queueserver.auth import authobj
from queueserver.clean_request import clean_request
from starlette.endpoints import HTTPEndpoint
from starlette.responses import JSONResponse
import logging
from db import dbobj
from queueserver.clean_action import MessageDelete

logger = logging.getLogger('starqueue')
logger.debug('MessageDelete std')


class EndpointMessageDelete(HTTPEndpoint):
    async def post(self, request):
        logger.debug('EndpointMessageDelete')
        await authobj.authenticate_request(request)
        data_to_clean = await clean_request.clean(request, MessageDelete.required_fields, MessageDelete.optional_fields)

        '''
        await authobj.verify_jwt_rs256(
            data_to_clean['accountid'],
            data_to_clean['AuthToken']
        )
        '''

        action = MessageDelete()
        api_request_data = await action.clean(data_to_clean)
        result = await dbobj.MessageDelete(api_request_data)
        return JSONResponse(result, status_code=200)
