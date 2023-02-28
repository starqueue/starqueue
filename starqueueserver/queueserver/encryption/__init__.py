from .encryption_pro import Encryption
import asyncio

encryptionobj = Encryption()

__all__ = [
    'encryptionobj'
]

'''
async def start_encryptionobj():
    global encryptionobj
    encryptionobj = Encryption()
    await encryptionobj.start()
    loop = asyncio.new_event_loop()  # Note: custom loop!

asyncio.get_running_loop().run_until_complete(start_encryptionobj())
'''
#asyncio.run(encryptionobj.start())