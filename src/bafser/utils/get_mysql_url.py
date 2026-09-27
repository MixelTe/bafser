import os

from sqlalchemy.engine import URL, make_url

from .get_db_path import get_db_path


def get_mysql_url(path_config: str) -> URL:
    """Build a MySQL URL without interpolating credentials into a string."""
    password_file = os.environ.get("DB_PASSWORD_FILE")
    if password_file is None:
        return make_url(f"mysql+pymysql://{get_db_path(path_config)}?charset=UTF8mb4")

    try:
        with open(password_file, encoding="utf-8") as file:
            password = file.read().rstrip("\r\n")
    except OSError as error:
        raise ValueError("Unable to read DB_PASSWORD_FILE") from error

    if not password:
        raise ValueError("DB_PASSWORD_FILE is empty")

    username = _required_env("DB_USER")
    host = _required_env("DB_HOST")
    database = _required_env("DB_NAME")
    try:
        port = int(os.environ.get("DB_PORT", "3306"))
    except ValueError as error:
        raise ValueError("DB_PORT must be an integer") from error
    if not 1 <= port <= 65535:
        raise ValueError("DB_PORT must be between 1 and 65535")

    return URL.create(
        "mysql+pymysql",
        username=username,
        password=password,
        host=host,
        port=port,
        database=database,
        query={"charset": "UTF8mb4"},
    )


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ValueError(f"Required environment variable '{name}' is not set")
    return value
