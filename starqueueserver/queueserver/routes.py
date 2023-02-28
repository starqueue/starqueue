from queueserver.endpoints.accountcreate import EndpointAccountCreate
from queueserver.endpoints.authtokenget import EndpointAuthTokenGet
from queueserver.endpoints.messagechangevisibility import EndpointMessageChangeVisibility
from queueserver.endpoints.messagedelete import EndpointMessageDelete
from queueserver.endpoints.messagereceive import EndpointMessageReceive
from queueserver.endpoints.messagesend import EndpointMessageSend
from queueserver.endpoints.queueclear import EndpointQueueClear
from queueserver.endpoints.queueslist import EndpointQueuesList
from starlette.routing import Route

routes = [
    Route('/accountcreate', endpoint=EndpointAccountCreate, methods=['POST']),
    Route('/authtokenget/{accountid:str}', endpoint=EndpointAuthTokenGet, methods=['POST']),
    Route('/messagechangevisibility/{accountid:str}/{queuename:str}', endpoint=EndpointMessageChangeVisibility, methods=['POST']),
    Route('/messagedelete/{accountid:str}/{queuename:str}', endpoint=EndpointMessageDelete, methods=['POST']),
    Route('/messagereceive/{accountid:str}/{queuename:str}', endpoint=EndpointMessageReceive, methods=['POST']),
    Route('/messagesend/{accountid:str}/{queuename:str}', endpoint=EndpointMessageSend, methods=['POST']),
    Route('/queueclear/{accountid:str}/{queuename:str}', endpoint=EndpointQueueClear, methods=['POST']),
    Route('/queueslist/{accountid:str}', endpoint=EndpointQueuesList, methods=['POST']),
]
