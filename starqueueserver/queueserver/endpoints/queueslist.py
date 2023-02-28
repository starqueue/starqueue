from queueserver.auth import authobj
from queueserver.clean_request import clean_request
from starlette.endpoints import HTTPEndpoint
from starlette.responses import JSONResponse
import logging
from db import dbobj
from queueserver.clean_action import QueuesList

logger = logging.getLogger('starqueue')
logger.debug('QueuesList std')


class EndpointQueuesList(HTTPEndpoint):
    async def post(self, request):
        logger.debug('EndpointQueuesList')
        await authobj.authenticate_request(request)
        data_to_clean = await clean_request.clean(request, QueuesList.required_fields, QueuesList.optional_fields)
        '''
        await authobj.verify_jwt_rs256(
            data_to_clean['accountid'],
            data_to_clean['AuthToken']
        )
        '''
        action = QueuesList()
        api_request_data = await action.clean(data_to_clean)
        result = await dbobj.QueuesList(api_request_data)

        # a hack to filter on accountid
        print(result)
        result = [x for x in result['QueuesListResult'] if x['AccountId'] == data_to_clean['accountid']]
        result = {'QueuesListResult': result}
        return JSONResponse(result, status_code=200)
