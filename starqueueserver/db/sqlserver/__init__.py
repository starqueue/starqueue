try:
    from .opro import DatabaseQueue
except ImportError as e:
    from .ostd import DatabaseQueue

dbobj = DatabaseQueue()

