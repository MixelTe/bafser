from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
TEST_DIR = PROJECT_DIR / "test"

db_dev_path = str(TEST_DIR / "db/dev.db")
db_path = "ENV:DBPATH"  # e.g. mysql_user:password@localhost/app_db
db_mysql = True
sql_echo = False

allow_unsupported_for_update_clause: None | bool = None  # None: True in dev
datetime_utc = True

use_alembic = True
migrations_folder = str(TEST_DIR / "alembic")

log_info_path = str(TEST_DIR / "logs/log_info.csv")
log_requests_path = str(TEST_DIR / "logs/log_requests.csv")
log_errors_path = str(TEST_DIR / "logs/log_errors.log")
log_frontend_path = str(TEST_DIR / "logs/log_frontend.log")
log_dashboard_path = str(TEST_DIR / "logs/log_dashboard.csv")

jwt_key_file_path = str(TEST_DIR / "secret_key_jwt.txt")
images_folder = str(TEST_DIR / "images")

login_page_url = "/login"
api_url = "/api/"

blueprints_package = "test.blueprints"
data_tables_package = "test.data"
