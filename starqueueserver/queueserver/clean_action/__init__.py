'''
try:
    from queueserver.clean_action.clean_action_pro import Action
except ImportError as e:
    from queueserver.clean_action.clean_action_std import Action

clean_action = Action()
'''

try:
    from queueserver.clean_action.MessageChangeVisibility_pro import MessageChangeVisibility
except ImportError as e:
    from queueserver.clean_action.MessageChangeVisibility_std import MessageChangeVisibility

try:
    from queueserver.clean_action.MessageDelete_pro import MessageDelete
except ImportError as e:
    from queueserver.clean_action.MessageDelete_std import MessageDelete

try:
    from queueserver.clean_action.QueueClear_pro import QueueClear
except ImportError as e:
    from queueserver.clean_action.QueueClear_std import QueueClear

try:
    from queueserver.clean_action.QueuesList_pro import QueuesList
except ImportError as e:
    from queueserver.clean_action.QueuesList_std import QueuesList

try:
    from queueserver.clean_action.MessageReceive_pro import MessageReceive
except ImportError as e:
    from queueserver.clean_action.MessageReceive_std import MessageReceive

try:
    from queueserver.clean_action.MessageSend_pro import MessageSend
except ImportError as e:
    from queueserver.clean_action.MessageSend_std import MessageSend

try:
    from queueserver.clean_action.AccountCreate_std import AccountCreate
except ImportError as e:
    from queueserver.clean_action.AccountCreate_std import AccountCreate

try:
    from queueserver.clean_action.AuthTokenGet_std import AuthTokenGet
except ImportError as e:
    from queueserver.clean_action.AuthTokenGet_std import AuthTokenGet







