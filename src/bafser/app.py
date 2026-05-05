import json
import logging
import os
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Literal
from urllib.parse import quote

from flask import Flask, Response, abort, g, jsonify, make_response, redirect, request, send_from_directory
from flask_jwt_extended import JWTManager, create_access_token, get_jwt, get_jwt_identity, set_access_cookies, verify_jwt_in_request  # type: ignore
from sqlalchemy import text
from sqlalchemy.orm import Session

import bafser_config

from . import db_session
from .alembic import alembic_upgrade
from .authentication import get_user_id_by_jwt_identity
from .doc_api import init_api_docs
from .logger import get_logger_dashboard, get_logger_requests, setLogging
from .utils import get_json, get_secret_key, get_secret_key_rnd, randstr, register_blueprints, response_msg

_config: "AppConfig | None" = None


class AppConfig:
    data_folders: list[tuple[str, str]] = []
    config: list[tuple[str, Any]] = []

    def __init__(
        self,
        *,
        FRONTEND_FOLDER: str = "build",
        JWT_ACCESS_TOKEN_EXPIRES: Literal[False] | timedelta = timedelta(hours=24),
        JWT_ACCESS_TOKEN_REFRESH: Literal[False] | timedelta = timedelta(minutes=30),
        CACHE_MAX_AGE: int = 31536000,
        MESSAGE_TO_FRONTEND: str = "",
        STATIC_FOLDERS: list[str] = ["/static/", "/fonts/", "/_next/"],
        DEV_MODE: bool = False,
        DELAY_MODE: bool = False,
        PAGE404: str = "index.html",
        HEALTH_ROUTE: bool | str = False,
        THREADED: bool = False,
    ):
        """
        Initializes the application configuration settings.

        Args:
            FRONTEND_FOLDER (str): Path to compiled frontend assets.
            JWT_ACCESS_TOKEN_EXPIRES (Literal[False] | timedelta): Lifespan of JWT access tokens.
                Use `False` for no expiration. Defaults to 24 hours.
            JWT_ACCESS_TOKEN_REFRESH (Literal[False] | timedelta): Lifespan for refresh tokens.
                Defaults to 30 minutes.
            CACHE_MAX_AGE (int): 'max-age' for Cache-Control headers in seconds.
                Defaults to one year.
            MESSAGE_TO_FRONTEND (str): Custom string passed to the client.
            STATIC_FOLDERS (list[str]): URL prefixes treated as static asset directories.
                Defaults to ["/static/", "/fonts/", "/_next/"].
            DEV_MODE (bool): If True, enables verbose logging and debug features.
            DELAY_MODE (bool): If True, simulates network latency for UI testing.
            PAGE404 (str): Filename to serve for missing routes (SPA fallback).
            HEALTH_ROUTE (bool | str): Path for health checks.
                - `True`: defaults to "/api/health".
                - `str`: uses the specific path.
                - `False`: disables the endpoint.
            THREADED (bool): Enables multithreaded mode.

                When True, the following changes take effect

                **Logging:** File rotation is disabled, and the log handler is switched to
                `WatchedFileHandler` to safely support log file rotation.

                **`run` function behavior:** The behavior of the `run` function is modified
                based on the presence of the `--setup` command-line argument
                - **Normal startup (without `--setup`):** The application runs normally,
                but database initialization and migrations are skipped.
                - **Setup mode (with `--setup`):** The application performs only
                database initialization and migrations, then exits.
        """
        self.FRONTEND_FOLDER = FRONTEND_FOLDER
        self.JWT_ACCESS_TOKEN_EXPIRES = JWT_ACCESS_TOKEN_EXPIRES
        self.JWT_ACCESS_TOKEN_REFRESH = JWT_ACCESS_TOKEN_REFRESH
        self.CACHE_MAX_AGE = CACHE_MAX_AGE
        self.MESSAGE_TO_FRONTEND = MESSAGE_TO_FRONTEND
        self.STATIC_FOLDERS = STATIC_FOLDERS
        self.DEV_MODE = DEV_MODE
        self.DELAY_MODE = DELAY_MODE
        self.PAGE404 = PAGE404
        self.HEALTH_ROUTE = "/api/health" if HEALTH_ROUTE is True else HEALTH_ROUTE
        self.THREADED = THREADED
        self.add_data_folder("IMAGES_FOLDER", bafser_config.images_folder)
        self.add("CACHE_MAX_AGE", CACHE_MAX_AGE)

    def add(self, key: str, value: Any) -> "AppConfig":
        """Adds value accessible via `current_app.config[key]`"""
        self.config.append((key, value))
        return self

    def add_data_folder(self, key: str, path: str) -> "AppConfig":
        """
        Registers a directory that must exist at startup.

        The directory will be created automatically if it is missing.
        The path is stored in `current_app.config[key]`.

        Args:
            key: The configuration key.
            path: Filesystem path to the folder.

        Returns:
            The AppConfig instance for method chaining.
        """
        self.add(key, path)
        self.data_folders.append((key, path))
        return self

    def add_secret_key(self, key: str, path: str) -> "AppConfig":
        """
        Loads a secret key from a local file.

        The value is stored in `current_app.config[key]`.

        Args:
            key: The configuration key.
            path: Path to the file containing the secret.

        Returns:
            The AppConfig instance for method chaining.

        Raises:
            FileNotFoundError: If the file at `path` does not exist.
        """
        self.add(key, get_secret_key(path))
        return self

    def add_env_var(self, key: str, envname: str | None = None, default: str | None = None) -> "AppConfig":
        """
        Loads a string configuration value from an environment variable.

        The value is stored in `current_app.config[key]`.

        Args:
            key: The configuration key used within the app.
            envname: The environment variable name (defaults to `key`).
            default: Fallback value if the environment variable is missing.

        Returns:
            The AppConfig instance for method chaining.

        Raises:
            ValueError: If the environment variable is missing and no default is set.
        """
        if envname is None:
            envname = key
        v = os.environ.get(envname, default)
        if v is None:
            raise ValueError(f"Required environment variable '{envname}' is not set.")
        self.add(key, v)
        return self

    add_secret_key_env = add_env_var

    def add_env_var_int(self, key: str, envname: str | None = None, default: int | None = None) -> "AppConfig":
        """
        Loads an integer configuration value from an environment variable.

        The value is stored in `current_app.config[key]`.

        Args:
            key: The configuration key used within the app.
            envname: The environment variable name (defaults to `key`).
            default: Fallback value if the environment variable is missing.

        Returns:
            The AppConfig instance for method chaining.

        Raises:
            ValueError: If the environment variable is missing (and no default
                is provided) or if the value cannot be cast to an integer.
        """
        if envname is None:
            envname = key

        raw_v = os.environ.get(envname)
        if raw_v is None:
            if default is not None:
                self.add(key, default)
                return self
            raise ValueError(f"Required environment variable '{envname}' is not set.")

        try:
            v = int(raw_v)
        except ValueError:
            raise ValueError(f"Environment variable '{envname}' must be an integer, got: '{raw_v}'")

        self.add(key, v)
        return self

    def add_secret_key_rnd(self, key: str, path: str) -> "AppConfig":
        """
        Generates a random secret key and persists it to a file if it doesn't exist.

        The value is stored in `current_app.config[key]`.

        Args:
            key: The configuration key.
            path: Path where the secret key is or should be stored.

        Returns:
            The AppConfig instance for method chaining.
        """
        self.add(key, get_secret_key_rnd(path))
        return self


def create_app(import_name: str, config: AppConfig):
    global _config
    _config = config
    setLogging()
    logreq = get_logger_requests()
    logdash = get_logger_dashboard()
    app = Flask(import_name, static_folder=None)
    app.config["JWT_TOKEN_LOCATION"] = ["cookies"]
    app.config["JWT_SECRET_KEY"] = get_secret_key_rnd(bafser_config.jwt_key_file_path)
    app.config["JWT_ACCESS_TOKEN_EXPIRES"] = config.JWT_ACCESS_TOKEN_EXPIRES
    app.config["JWT_COOKIE_CSRF_PROTECT"] = False
    app.config["JWT_SESSION_COOKIE"] = False
    app.secret_key = app.config["JWT_SECRET_KEY"]
    for key, path in config.config:
        app.config[key] = path

    jwt_manager = JWTManager(app)

    register_blueprints(app)
    init_api_docs(app)

    for _, path in config.data_folders:
        os.makedirs(path, exist_ok=True)

    def run(
        run_server: bool,
        init_db: Callable[[Session, AppConfig], None] | None = None,
        init_dev_values: Callable[[Session, AppConfig], None] | None = None,
        port: int = 5000,
        host: str = "127.0.0.1",
    ):
        setup_only = config.THREADED and "--setup" in sys.argv

        if not config.THREADED or setup_only:
            print("Setup database")
            if bafser_config.use_alembic:
                alembic_upgrade(config.DEV_MODE)
            init_database(init_db, init_dev_values)
            if setup_only:
                return

        db_session.global_init(config.DEV_MODE)
        if run_server:
            print(f"Starting on http://{host}:{port}")
            if config.DELAY_MODE:
                print("Delay for requests is enabled")
            app.run(debug=config.DEV_MODE, port=port, host=host)

    def init_database(init_db: Callable[[Session, AppConfig], None] | None, init_dev_values: Callable[[Session, AppConfig], None] | None):
        from . import Role, UserBase
        from .data.db_state import DBState

        db_session.global_init(config.DEV_MODE)
        with db_session.create_session() as db_sess:
            is_initialized = DBState.is_initialized(db_sess)
            Role.update_roles_permissions(db_sess)
            if not is_initialized:
                print("initialize database")
                UserBase._create_admin(db_sess)  # type: ignore
                if init_db is not None:
                    print("init_db")
                    init_db(db_sess, config)
                if config.DEV_MODE and init_dev_values is not None:
                    print("init_dev_values")
                    init_dev_values(db_sess, config)
                DBState.mark_as_initialized(db_sess)

            if not config.DEV_MODE:
                change_admin_default_pwd(db_sess)

    def change_admin_default_pwd(db_sess: Session):
        from .data.user import get_user_table

        User = get_user_table()
        admin = User.get_by_login(db_sess, "admin", includeDeleted=True)
        if admin is not None and admin.check_password("admin"):
            admin.set_password(randstr(16))
            db_sess.commit()
        db_sess.close()

    @app.before_request
    def before_request():  # type: ignore
        if bafser_config.sql_echo:
            print(request.path)
        g.json = get_json(request)
        g.req_id = randstr(4)
        g.req_start = time.perf_counter_ns()
        try:
            verify_jwt_in_request()
            g.userId = get_user_id_by_jwt_identity(get_jwt_identity())
        except Exception:
            g.userId = None
        if request.path.startswith(bafser_config.api_url):
            try:
                if g.json[1]:
                    if isinstance(g.json[0], dict) and "password" in g.json[0]:
                        password = g.json[0]["password"]  # type: ignore
                        g.json[0]["password"] = "***"
                        data = json.dumps(g.json[0])[:512]
                        g.json[0]["password"] = password
                    else:
                        data = json.dumps(g.json[0])[:512]
                    logreq.info("Request;;%(data)s", {"data": data})
                else:
                    logreq.info("Request")
            except Exception as x:
                logging.error("Request logging error: %s", x)

        if config.DELAY_MODE:
            time.sleep(0.5)

    @app.after_request
    def after_request(response: Response):  # type: ignore
        logdash.info("", extra={"code": response.status_code})
        if request.path.startswith(bafser_config.api_url):
            try:
                if response.content_type == "application/json":
                    logreq.info("Response;%s;%s", response.status_code, str(response.data)[:512])
                else:
                    logreq.info("Response;%s", response.status_code)
            except Exception as x:
                logging.error("Request logging error: %s", x)

        response.set_cookie("MESSAGE_TO_FRONTEND", quote(config.MESSAGE_TO_FRONTEND))

        if config.JWT_ACCESS_TOKEN_REFRESH:
            try:
                exp_timestamp: float = get_jwt()["exp"]  # type: ignore
                now = datetime.now(timezone.utc)
                target_timestamp = datetime.timestamp(now + config.JWT_ACCESS_TOKEN_REFRESH)
                if target_timestamp > exp_timestamp:
                    access_token = create_access_token(identity=get_jwt_identity())
                    set_access_cookies(response, access_token)
            except (RuntimeError, KeyError):
                # Case where there is not a valid JWT
                pass

        return response

    @app.teardown_appcontext
    def teardown(exception: BaseException | None = None):  # pyright: ignore[reportUnusedFunction]
        g.pop("user", None)
        db_sess = g.pop("db_session", None)
        if db_sess:
            try:
                db_sess.close()
            except Exception as x:
                logging.error("Error: %s", x)

    @app.route("/", defaults={"path": ""})
    @app.route("/<path:path>")
    def frontend(path: str):  # type: ignore
        if request.path.startswith(bafser_config.api_url):
            abort(404)

        if path == "":
            fname = "index.html"
        elif os.path.exists(config.FRONTEND_FOLDER + "/" + path):
            fname = path
        elif os.path.exists(config.FRONTEND_FOLDER + "/" + path + ".html"):
            fname = path + ".html"
        elif "." in os.path.basename(path):
            abort(404)
        else:
            fname = config.PAGE404

        res = send_from_directory(config.FRONTEND_FOLDER, fname)
        if any(request.path.startswith(path) for path in config.STATIC_FOLDERS):
            res.headers.set("Cache-Control", f"public,max-age={config.CACHE_MAX_AGE},immutable")
        else:
            res.headers.set("Cache-Control", "public,max-age=60,stale-while-revalidate=600,stale-if-error=14400")
        return res

    if config.HEALTH_ROUTE:

        @app.route("/api/health")
        def health():  # pyright: ignore[reportUnusedFunction]
            try:
                with db_session.create_session() as db_sess:
                    db_sess.execute(text("SELECT 1")).scalar()
                return jsonify(status="ok"), 200
            except Exception as e:
                logging.error("%s\n%s", e, traceback.format_exc())
                return jsonify(status="unhealthy"), 500

    @app.errorhandler(404)
    def not_found(error: Exception):  # pyright: ignore[reportUnusedFunction]
        if request.path.startswith(bafser_config.api_url):
            return response_msg("Not found", 404)
        return make_response("Страница не найдена", 404)

    @app.errorhandler(405)
    def method_not_allowed(error: Exception):  # pyright: ignore[reportUnusedFunction]
        return response_msg("Method Not Allowed", 405)

    @app.errorhandler(415)
    def unsupported_media_type(error: Exception):  # pyright: ignore[reportUnusedFunction]
        return response_msg("Unsupported Media Type", 415)

    @app.errorhandler(403)
    def no_permission(error: Exception):  # pyright: ignore[reportUnusedFunction]
        return response_msg("No permission", 403)

    @app.errorhandler(500)
    @app.errorhandler(Exception)
    def internal_server_error(error: Exception):  # pyright: ignore[reportUnusedFunction]
        print(error)
        logging.error("%s\n%s", error, traceback.format_exc())
        if request.path.startswith(bafser_config.api_url):
            return response_msg("Internal Server Error", 500)
        return make_response("Произошла ошибка", 500)

    @app.errorhandler(401)
    def unauthorized(error: Exception):  # pyright: ignore[reportUnusedFunction]
        if not request.path.startswith(bafser_config.api_url):
            return redirect(bafser_config.login_page_url + "?redirect=" + request.path)
        return response_msg("Unauthorized", 401)

    @jwt_manager.expired_token_loader  # type: ignore
    def expired_token_loader(jwt_header, jwt_data):  # type: ignore
        if not request.path.startswith(bafser_config.api_url):
            return redirect(bafser_config.login_page_url + "?redirect=" + request.path)
        return response_msg("The JWT has expired", 401)

    @jwt_manager.invalid_token_loader  # type: ignore
    def invalid_token_loader(error: Exception):  # pyright: ignore[reportUnusedFunction]
        if not request.path.startswith(bafser_config.api_url):
            return redirect(bafser_config.login_page_url + "?redirect=" + request.path)
        return response_msg("Invalid JWT", 401)

    @jwt_manager.unauthorized_loader  # type: ignore
    def unauthorized_loader(error: Exception):  # pyright: ignore[reportUnusedFunction]
        if not request.path.startswith(bafser_config.api_url):
            return redirect(bafser_config.login_page_url + "?redirect=" + request.path)
        return response_msg("Unauthorized", 401)

    return app, run


def update_message_to_frontend(msg: str):
    assert _config
    _config.MESSAGE_TO_FRONTEND = msg


def get_app_config():
    assert _config
    return _config
