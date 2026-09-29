db_dev_path = "storage/db/dev.db"
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

use_alembic = True
migrations_folder = "alembic"

log_info_path = "storage/logs/log_info.csv"
log_requests_path = "storage/logs/log_requests.csv"
log_errors_path = "storage/logs/log_errors.log"
log_frontend_path = "storage/logs/log_frontend.log"
log_dashboard_path = "storage/logs/log_dashboard.csv"

jwt_key_file_path = "storage/secret_key_jwt.txt"
images_folder = "storage/images"

login_page_url = "/login"
api_url = "/api/"

blueprints_folder = "blueprints"
data_tables_folder = "data"
