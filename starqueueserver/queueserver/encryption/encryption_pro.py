import logging
from definitions import CONFIG_DIR
from cryptography.fernet import Fernet, InvalidToken
import asyncio
import base64
import traceback

logger = logging.getLogger('starqueue')

logger.debug('encryption std')

class Encryption():

    def __init__(self):
        self.encryptionkey_filename = f'{CONFIG_DIR}/encryptionkeys.txt'

    async def start(self):
        loop = asyncio.get_event_loop()  # Note: custom loop!
        task = loop.create_task(self.task_ReloadEncryptionkeys())
        task.set_name('task: start_task_ReloadEncryptionkeys')
        await self.load_encryptionkeys()

    async def task_ReloadEncryptionkeys(self):
        # encryption keys are reloaded periodically - ths allows key changes without restarting the server
        delay = 60  # 1 minute
        while True:
            await asyncio.sleep(delay)
            try:
                logger.debug(f'doing periodic task_ReloadEncryptionkeys.....')
                await self.load_encryptionkeys()
            except Exception as e:
                logger.critical(f'task_ReloadEncryptionkeys ERROR {repr(e)}')

    async def encrypt(self, messagebody):
        try:
            # if there are no encryption keys then we do not encrypt
            if len(self.encryptionkeys) == 0:
                return messagebody
            # we always use the FIRST encryption key from the encryptionkeys.txt file
            f = Fernet(self.encryptionkeys[0])
            messagebody_decrypted_asbytes = messagebody.encode()
            messagebody_encrypted_asbytes = f.encrypt(messagebody_decrypted_asbytes)
            messagebody_encrypted_asbase64bytes = base64.b64encode(messagebody_encrypted_asbytes)
            messagebody_encrypted_asb64string = messagebody_encrypted_asbase64bytes.decode()
            return messagebody_encrypted_asb64string
        except Exception as e:
            print('repr(e)')
            print(repr(e), traceback.format_exc())
            return messagebody

    async def decrypt(self, messagebody):
        # to decrypt, we try each encryption key in encryptionkeys.txt
        # this allows changing of keys without restarting the server

        # it is a bad idea to have more than a few keys and ideally only one

        # if there are no encryption keys then we do not encrypt
        if len(self.encryptionkeys) == 0:
            return messagebody
        for count, key in enumerate(self.encryptionkeys):
            try:
                key = bytes(self.encryptionkeys[0])

                try:
                    # we always use the FIRST encryption key from the encryptionkeys.txt file
                    f = Fernet(key)
                    messagebody_encrypted_asbytes = base64.b64decode(messagebody)
                    messagebody_decrypted_asbytes = f.decrypt(messagebody_encrypted_asbytes)
                    messagebody_decrypted_asstring = messagebody_decrypted_asbytes.decode("utf-8")
                except Exception as e:
                    logger.critical({repr(e)})
                    return messagebody

                # if the key that successfully encrypted is not either position 0 or 1, then move it into position 1
                # this means the next message to be decrypted is less likely to try lots of keys (CPU intensive)
                # we do not move it to position 0 because the key in position 0 is always used for encrypting
                if count > 1:
                    self.encryptionkeys.remove(key)
                    self.encryptionkeys.insert(1, key)
                return messagebody_decrypted_asstring
            except InvalidToken as e:
                # move on to the next key
                continue
            except Exception as e:
                # some other unknown critical error
                logger.critical(f'DECRYPTION FAILED!')
        # if we failed to decrypt with any of the keys then return the messagebody same as we got it
        return messagebody

    async def load_encryptionkeys(self):
        self.encryptionkeys = []
        try:
            with open(self.encryptionkey_filename, 'rb') as f:
                self.encryptionkeys = [line.strip() for line in f]
        except FileNotFoundError as e:
            print(f'{self.encryptionkey_filename} does not exist.....')
        except Exception as e:
            logger.critical(f'failed to read {self.encryptionkey_filename} {repr(e)}')

    async def generate_encryption_key(self):
        print(f'Here is a new encryption key:')
        print(f'')
        print(Fernet.generate_key().decode())
        print('')
        print(f'Add the key to {CONFIG_DIR}/encryptionkeys.txt')
        print(f'')
        print(f'Notes:')
        print(f'encryptionkeys.txt may contain multiple encryption keys, one per line.')
        print(f'Encryption is done with the FIRST key in encryptionkeys.txt')
        print(f'Decryption is attempted with EVERY key in encryptionkeys.txt')
        print(f'Ideally there should be only one encryption key in encryptionkeys.txt')
        print()



