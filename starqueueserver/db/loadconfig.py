from dotenv import load_dotenv
from pathlib import Path
import os
import sys
from definitions import ROOT_DIR, CONFIG_DIR, DB_TYPE

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

def load():
    DB_USERNAME = os.getenv("DB_USERNAME")
    DB_HOST = os.getenv("DB_HOST")
    DB_PORT = os.getenv("DB_PORT")
    DB_PASSWORD = os.getenv("DB_PASSWORD")
    DB_DATABASENAME = os.getenv("DB_DATABASENAME")

    def validate_databaseparams(DB_USERNAME, DB_HOST, DB_PORT, DB_PASSWORD, DB_DATABASENAME, DB_TYPE):
        if not all([DB_USERNAME, DB_HOST, DB_PORT, DB_PASSWORD, DB_DATABASENAME]):
            print('Cannot start, failed to load database params from .env')
            sys.exit(1)

        supported_databases = ['postgres', 'sqlserver', 'mysql']
        if DB_TYPE not in supported_databases:
            print(f'Cannot start, {DB_TYPE} is not in supported databases: {supported_databases}')
            sys.exit(1)

    print(f'database type is: {DB_TYPE}')

    validate_databaseparams(DB_USERNAME, DB_HOST, DB_PORT, DB_PASSWORD, DB_DATABASENAME, DB_TYPE)
    return DB_USERNAME, DB_HOST, DB_PORT, DB_PASSWORD, DB_DATABASENAME, DB_TYPE


