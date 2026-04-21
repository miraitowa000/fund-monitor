import os
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
APP_ENV = os.getenv('APP_ENV', 'testing').strip().lower() or 'testing'
SUPPORTED_ENVS = {'testing', 'production'}
ENV_FILE_MAP = {
    'testing': BASE_DIR / '.env.testing',
    'production': BASE_DIR / '.env.production',
}

if APP_ENV not in SUPPORTED_ENVS:
    raise RuntimeError(f'Unsupported APP_ENV: {APP_ENV}')

env_file = ENV_FILE_MAP.get(APP_ENV)
if env_file and env_file.exists():
    load_dotenv(env_file, override=False)


def _get_env(name, default=None, required=False):
    value = os.getenv(name)
    if value not in (None, ''):
        return value
    if required:
        raise RuntimeError(f'Missing required environment variable: {name}')
    return default


DB_HOST = _get_env('DB_HOST', 'localhost')
DB_PORT = int(_get_env('DB_PORT', '3306'))
DB_USER = _get_env('DB_USER', 'root')
DB_PASSWORD = _get_env('DB_PASSWORD', 'abcd.1234')
DB_NAME = _get_env('DB_NAME', 'fund_monitor')
DB_CHARSET = _get_env('DB_CHARSET', 'utf8mb4')


def build_mysql_uri(mask_password=False):
    password = '***' if mask_password else quote_plus(DB_PASSWORD)
    return (
        f"mysql+pymysql://{quote_plus(DB_USER)}:{password}"
        f"@{DB_HOST}:{DB_PORT}/{DB_NAME}?charset={DB_CHARSET}"
    )
