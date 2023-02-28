from db import dbobj
import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

async def notification_listen_task(callback):
    await dbobj.get_pool()
    await dbobj.NotificationListen(callback)

