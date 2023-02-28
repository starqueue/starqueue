import asyncio

import sys


if __name__ == '__main__':
    try:
        if len(sys.argv) == 1:
            asyncio.run(authobj.setup_passwords_from_commandline())
        if len(sys.argv) == 3:
            asyncio.run(authobj.setup_passwords_from_commandline(sys.argv[1], sys.argv[2]))
        else:
            print('usage:')
            print('python setup_passwords.py accountid/queuename password')
            print('')
            print('note the slash. for example:')
            print('python setup_passwords.py 111111111111/myqueuename supersecretpassword')
            print('')
            print('to set up server password use * instead of accountid/queuename')
            print('for example:')
            print('python setup_passwords.py * supersecretpassword')
            print('')
            print('or you can use interactive mode:')
            print('python setup_passwords.py')
    except KeyboardInterrupt:
        pass


