from queueserver.auth import authobj
from queueserver.clean_request import clean_request
from starlette.endpoints import HTTPEndpoint
from starlette.responses import JSONResponse
import logging
from db import dbobj
from queueserver.clean_action import MessageChangeVisibility

logger = logging.getLogger('starqueue')
logger.debug('MessageChangeVisibility std')


class EndpointMessageChangeVisibility(HTTPEndpoint):
    async def post(self, request):
        logger.debug('EndpointMessageChangeVisibility')
        await authobj.authenticate_request(request)
        data_to_clean = await clean_request.clean(
            request,
            MessageChangeVisibility.required_fields,
            MessageChangeVisibility.optional_fields
        )

        '''
        await authobj.verify_jwt_rs256(
            data_to_clean['accountid'],
            data_to_clean['AuthToken']
        )
        '''

        action = MessageChangeVisibility()
        api_request_data = await action.clean(data_to_clean)
        result = await dbobj.QueuesList(api_request_data)
        return JSONResponse(result, status_code=200)
