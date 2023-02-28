from queueserver.auth import authobj
from queueserver.clean_request import clean_request
from starlette.endpoints import HTTPEndpoint
from starlette.responses import JSONResponse
import logging
from db import dbobj
from queueserver.clean_action import MessageSend
from definitions import MESSAGES_IN_QUEUE_MAXIMUM
import datetime

logger = logging.getLogger('starqueue')
logger.debug('EndpointMessageSend std')

class EndpointMessageSend(HTTPEndpoint):
    async def post(self, request):
        logger.debug('EndpointMessageSend')
        await authobj.authenticate_request(request)
        data_to_clean = await clean_request.clean(request, MessageSend.required_fields, MessageSend.optional_fields)
        '''
        await authobj.verify_jwt_rs256(
            data_to_clean['accountid'],
            data_to_clean['AuthToken']
        )
        '''
        action = MessageSend()
        api_request_data = await action.clean(data_to_clean)
        count_of_waiting_messages_in_queue = await dbobj.CountWaitingMessagesInQueue(
            data_to_clean['accountid'],
            data_to_clean['queuename'],
        )
        print('count_of_waiting_messages_in_queue', count_of_waiting_messages_in_queue)
        if count_of_waiting_messages_in_queue > MESSAGES_IN_QUEUE_MAXIMUM:
            return JSONResponse({'error': 'queue is full'}, status_code=429)
        result = await dbobj.MessageSend(api_request_data)
        await dbobj.AccountIncrementMessagesSentCount(api_request_data)
        return JSONResponse(result, status_code=200)
