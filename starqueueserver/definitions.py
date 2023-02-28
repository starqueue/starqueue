import os
from pathlib import Path
from dotenv import load_dotenv
import sys

ROOT_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = Path(ROOT_DIR, 'config')

env_path = Path(CONFIG_DIR, '.env_starqueue')
load_dotenv(dotenv_path=env_path)
DB_TYPE = os.getenv("DB_TYPE")
JWTKEY = os.getenv('JWTKEY')
if not JWTKEY:
    print('JWTKEY is None')
    sys.exit()
LOGLEVEL = os.getenv('LOGLEVEL', 'CRITICAL').upper()
SOCKETFILE = '/tmp/dbnotificationserver.socket'
PORTNUMFILE = '/tmp/dbnotificationserver.portnum'
LONGPOLLSECONDSMAX = 20
PORT_NUMBER_MINIMUM = 8000
PORT_NUMBER_MAXIMUM = 8003
PASSWORDLENGTH_MINIMUM = 12
PASSWORDLENGTH_MAXIMUM = 20
VISIBILITYTIMEOUT_MINIMUM = -43200
VISIBILITYTIMEOUT_MAXIMUM = 43200
MESSAGES_IN_QUEUE_MAXIMUM = 50000

# MESSAGERETENTIONPERIOD_DEFAULT =  345600 # 4 days
MESSAGERETENTIONPERIOD_DEFAULT =  14400 # 4 hours (for free online service)
#MESSAGERETENTIONPERIOD_MAX =  1209600 # 14 days
MESSAGERETENTIONPERIOD_MAX =  14400 # 2 hours (for free online service)
MESSAGEBODYLENGTH_MAX =  262144 # bytes
VERSIONS =  [1]

print(f'DB_TYPE is {DB_TYPE}')
print(f'ROOT_DIR is {ROOT_DIR}')
print(f'CONFIG_DIR is {CONFIG_DIR}')
