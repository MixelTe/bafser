from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
STORAGE_DIR = PROJECT_DIR / "storage"

db_dev_path = str(STORAGE_DIR / "db/dev.db")
# db_dev_path = "ENV:DBPATH"
db_path = "ENV:DBPATH"  # e.g. mysql_user:password@localhost/app_db
# Secure MySQL setup:
# db_path = ""
# env values:
#   DB_PASSWORD_FILE=/run/secrets/db_password
#   DB_USER=username
#   DB_HOST=mysql
#   DB_PORT=3306
#   DB_NAME=database
db_mysql = True
sql_echo = False

# Explicitly emulate FOR UPDATE for test databases without row locking (SQLite).
# Checks still require a successful query with for_update=True.
allow_unsupported_for_update_clause: None | bool = None  # None: True in dev

# Use UTC for shared model timestamps and ISO dates
datetime_utc = True

use_alembic = True
migrations_folder = str(PROJECT_DIR / "alembic")

# Optional engine limits, per process
db_pool_size = 5
db_max_overflow = 10
db_pool_timeout = 30
db_pool_recycle = 3600
db_connect_timeout = 10
db_read_timeout = 30
db_write_timeout = 30
db_hide_parameters: bool | None = None  # None: hidden in production, visible in dev

log_info_path = str(STORAGE_DIR / "logs/log_info.csv")
log_requests_path = str(STORAGE_DIR / "logs/log_requests.csv")
log_errors_path = str(STORAGE_DIR / "logs/log_errors.log")
log_frontend_path = str(STORAGE_DIR / "logs/log_frontend.log")
log_dashboard_path = str(STORAGE_DIR / "logs/log_dashboard.csv")

jwt_key_file_path = str(STORAGE_DIR / "secret_key_jwt.txt")
images_folder = str(STORAGE_DIR / "images")

login_page_url = "/login"
api_url = "/api/"

blueprints_package = "blueprints"
data_tables_package = "data"
