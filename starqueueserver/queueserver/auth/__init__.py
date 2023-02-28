try:
    from .auth_pro import Auth
except ImportError as e:
    from .auth_std import Auth

authobj = Auth()

