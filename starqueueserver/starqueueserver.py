import os

from queueserver.auth import authobj
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
import asyncio
import coloredlogs
import logging
import signal
import uvicorn
from queueserver.routes import routes
from queueserver.tasks import \
    task_shutdown, \
    task_MaxReceivesExceededTidyupTask, \
    task_MessageRetentionPeriodTidyupTask, \
    task_list_coroutines
import definitions
import socket
import sys
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from db import dbobj

try:
    from queueserver.encryption import encryptionobj
except:
    pass


logger = logging.getLogger('starqueue')
coloredlogs.install(level=definitions.LOGLEVEL, logger=logger)
logger.setLevel(definitions.LOGLEVEL)

class MessageIsAvailableException(Exception):
    pass

def handle_exception(loop, context):
    # ref https://www.roguelynn.com/words/asyncio-exception-handling/
    # ref https://docs.python.org/3/library/asyncio-dev.html#detect-never-retrieved-exceptions
    # ref https://docs.python.org/3/library/asyncio-eventloop.html#asyncio.loop.set_exception_handler

    # context['message'] will always be there; but context['exception'] must not
    msg = context.get('exception', context['message'])
    logging.error(f'Caught exception: {msg}')
    logger.debug('Shutting down...')
    task = asyncio.create_task(task_shutdown(loop))
    task.set_name('task: task_shutdown')


def setup_signals():
    # ref https://www.roguelynn.com/words/asyncio-exception-handling/
    # ref https://docs.python.org/3/library/asyncio-dev.html#detect-never-retrieved-exceptions
    # ref https://docs.python.org/3/library/asyncio-eventloop.html#asyncio.loop.set_exception_handler
    # May want to catch other signals too
    loop = asyncio.get_event_loop()
    signals = (signal.SIGHUP, signal.SIGTERM, signal.SIGINT)
    for s in signals:
        loop.add_signal_handler(
            s, lambda s=s: asyncio.create_task(task_shutdown(loop, signal=s)))
    loop.set_exception_handler(handle_exception)


async def startup():
    # read these:
    # https://lucumr.pocoo.org/2020/1/1/async-pressure/
    # https://nullprogram.com/blog/2020/05/24/
    # https://medium.com/@jayphelps/backpressure-explained-the-flow-of-data-through-software-2350b3e77ce7
    print('startup')
    await dbobj.get_pool()
    await authobj.start()
    if encryptionobj:
        await encryptionobj.start()

    loop = asyncio.get_event_loop()
    #task = loop.create_task(task_list_coroutines())
    #task.set_name('task: task_list_coroutines')
    task = loop.create_task(task_MessageRetentionPeriodTidyupTask())
    task.set_name('task: task_MessageRetentionPeriodTidyupTask')
    task = loop.create_task(task_MaxReceivesExceededTidyupTask())
    task.set_name('task: task_MaxReceivesExceededTidyupTask')
    setup_signals()

async def not_found(request, exc):
    return JSONResponse({'error': 'not found'}, status_code=exc.status_code)

async def server_error(request, exc):
    return JSONResponse({'error': 'server error'}, status_code=exc.status_code)

async def http_exception(request, exc):
    return JSONResponse({'detail': exc.detail}, status_code=exc.status_code)

async def unhandled_exception_handler(request, exc):
    return JSONResponse({'detail': exc.detail}, status_code=exc.status_code)

exception_handlers = {
    Exception: unhandled_exception_handler,
    HTTPException: http_exception,
    404: not_found,
    500: server_error
}

middleware = [
    Middleware(CORSMiddleware, allow_headers=['*'], allow_origins=['*'], allow_methods=['POST','OPTIONS'])
]


app = Starlette(
    routes=routes,
    middleware=middleware,
    debug=False,
    exception_handlers=exception_handlers,
    # on_startup=[startup, db_message_poll],
    on_startup=[startup],
    on_shutdown=[],
)
# on_shutdown = [shutdown],

def next_free_port():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    port = definitions.PORT_NUMBER_MINIMUM
    while port <= definitions.PORT_NUMBER_MAXIMUM:
        try:
            sock.bind(('', port))
            sock.close()
            return port
        except OSError:
            port += 1
    print(f'exiting: no free ports in range {definitions.PORT_NUMBER_MINIMUM} to {definitions.PORT_NUMBER_MAXIMUM}')
    sys.exit()

if __name__ == '__main__':
    #uvicorn.run(app, host='0.0.0.0', port=next_free_port(), headers=[('server', 'StarQueue')])
    #uvicorn.run(app, host='0.0.0.0', port=port, headers=[('server', 'StarQueue')])
    #uvicorn.run(app, host='0.0.0.0', port=8000, headers=[('server', 'StarQueue')])
    '''
    uvicorn.run("starqueueserver:app",
                uds=f'/run/starqueue/starqueue{get_systemd_instance_number()}.sock',
                headers=[('server', 'StarQueue')],
                workers=1,
                reload=False
                )
    '''
    # https://idea.popcount.org/2019-11-06-creating-sockets/
    # fd = 3, this is the file descriptor passed by systemd which appears t always be 3 for some reason
    uvicorn.run("starqueueserver:app",
                host='0.0.0.0',
                fd=3,
                headers=[('server', 'StarQueue')],
                workers=1,
                reload=False
                )


