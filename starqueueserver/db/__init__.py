from dotenv import load_dotenv
from pathlib import Path
from definitions import CONFIG_DIR, DB_TYPE

'''
environment filenames look like this:

config/.env_starqueue
config/.env_mysql
config/.env_oracle
config/.env_postgres
config/.env_sqlserver
'''

env_database = Path(CONFIG_DIR, f'.env_{DB_TYPE}')
load_dotenv(dotenv_path=env_database)

# notice this is not in a function because import * cannot be done from a function
if DB_TYPE == 'mysql':
    from .mysql import *
if DB_TYPE == 'postgres':
    from .postgres import *
if DB_TYPE == 'sqlserver':
    from .sqlserver import *


