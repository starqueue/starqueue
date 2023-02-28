try:
    from .opro import DatabaseQueue
except ImportError as e:
    from .ostd import DatabaseQueue
import asyncio

dbobj = DatabaseQueue()

'''
async def init():
    print('foo')
    await dbobj.get_pool()
    print('bar')


asyncio.run(init())
'''
