import json
import logging
import os
import sys
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, TypeVar
from urllib.parse import quote

from flask import Flask, Response, abort, current_app, g, has_app_context, jsonify, make_response, redirect, request, send_from_directory
from flask_jwt_extended import JWTManager, get_jwt, get_jwt_identity, set_access_cookies, verify_jwt_in_request  # type: ignore
from flask_jwt_extended.exceptions import JWTExtendedException
from jwt.exceptions import PyJWTError
from sqlalchemy import text
from sqlalchemy.orm import Session
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge

import bafser_config

from . import db_session
from .alembic import alembic_upgrade
from .authentication import get_user_id_by_jwt_identity, renew_access_token
from .constants import Constants
from .doc_api import init_api_docs
from .logger import format_log_data, get_logger_dashboard, get_logger_requests, log_error_details, setLogging, should_log_body
from .public_error import PublicError
from .utils import get_db_session, get_json, get_secret_key, get_secret_key_rnd, randstr, register_blueprints, response_msg

_config: "AppConfig | None" = None


class AppConfig:
    data_folders: list[tuple[str, str]]
    config: list[tuple[str, Any]]

    def __init__(
        self,
        *,
        FRONTEND_FOLDER: str = "build",
        JWT_ACCESS_TOKEN_EXPIRES: Literal[False] | timedelta = timedelta(hours=24),
        JWT_ACCESS_TOKEN_REFRESH: Literal[False] | timedelta = timedelta(minutes=30),
        JWT_COOKIE_CSRF_PROTECT: bool = True,
        JWT_SESSION_COOKIE: bool = False,
        JWT_COOKIE_DOMAIN: str | None = None,
        JWT_COOKIE_SAMESITE: Literal["None", "Lax", "Strict"] | None = None,
        JWT_COOKIE_SECURE: bool = True,
        MAX_IMAGE_BYTES: int = 7 * Constants.MIB,
        CACHE_MAX_AGE: int = 31536000,
        MESSAGE_TO_FRONTEND: str = "",
        STATIC_FOLDERS: list[str] = ["/static/", "/fonts/", "/_next/"],  # noqa: B006
        DEV_MODE: bool = False,
        LOG_ERROR_DETAILS: bool = True,
        LOG_JSON_RESPONSES: bool | None = None,
        DELAY_MODE: bool = False,
        PAGE404: str = "index.html",
        HEALTH_ROUTE: bool | str = False,
        AUTO_SETUP: bool = True,
        MULTIPROCESS_LOGGING: bool = False,
        CONFIGURE_ROOT_LOGGING: bool = True,
        REQUEST_POLICY: "RequestPolicy | None" = None,
        CORS_HEADERS_PROD: "AccessControlHeaders | None" = None,
        CORS_HEADERS_DEV: "AccessControlHeaders | None" = None,
    ):
        """
        Initializes the application configuration settings.

        Args:
            FRONTEND_FOLDER (str): Path to compiled frontend assets.
            JWT_ACCESS_TOKEN_EXPIRES (Literal[False] | timedelta): Lifespan of JWT access tokens.
                Use `False` for no expiration. Defaults to 24 hours.
            JWT_ACCESS_TOKEN_REFRESH (Literal[False] | timedelta): Lifespan for refresh tokens.
                Defaults to 30 minutes.
            CACHE_MAX_AGE (int): 'max-age' for bundled static assets in seconds.
                Defaults to one year. API responses default to private, no-store.
            JWT_COOKIE_DOMAIN (str | None): Domain for JWT cookies. Defaults to None.
            JWT_COOKIE_SAMESITE (Literal["None", "Lax", "Strict"] | None): SameSite policy for JWT cookies. Defaults to None.
            JWT_COOKIE_SECURE (bool): Whether to set the 'Secure' flag on JWT cookies. Defaults to True.
            MAX_IMAGE_BYTES (int): Maximum decoded image upload size in bytes. Defaults to 7 MiB.
            MESSAGE_TO_FRONTEND (str): Custom string passed to the client.
            STATIC_FOLDERS (list[str]): URL prefixes treated as static asset directories.
                Defaults to ["/static/", "/fonts/", "/_next/"].
                HTML pages and the SPA fallback keep the regular page cache policy.
            DEV_MODE (bool): If True, enables verbose logging and debug features.
            LOG_ERROR_DETAILS (bool): Keep ordinary log messages and full exception
                details in server logs. Defaults to True; False selects reduced
                production diagnostics. Development always keeps full details.
            LOG_JSON_RESPONSES (bool | None): Enable response body diagnostics.
                Defaults to DEV_MODE; RequestPolicy also controls body visibility.
            DELAY_MODE (bool): If True, simulates network latency for UI testing.
            PAGE404 (str): Filename to serve for missing routes (SPA fallback).
            HEALTH_ROUTE (bool | str): Path for health checks.
                - `True`: defaults to "/api/health".
                - `str`: uses the specific path.
                - `False`: disables the endpoint.
            AUTO_SETUP (bool): Prepare keys/directories and run database setup at
                startup for a simple single-process application. Set False in
                production and run --setup explicitly before starting workers.
            MULTIPROCESS_LOGGING (bool): Use coordinated file rotation, independently
                of AUTO_SETUP. All writers to the same files must agree on this.
            CONFIGURE_ROOT_LOGGING (bool): Attach bafser's own root handlers while
                preserving handlers configured by the host application.
            REQUEST_POLICY (RequestPolicy | None): Default early request policy.
            CORS_HEADERS_PROD (AccessControlHeaders | None): CORS configuration for production environments.
                Set to `None` if CORS headers are offloaded to an edge proxy like Nginx.
            CORS_HEADERS_DEV (AccessControlHeaders | None): CORS configuration for development environments.
                Defaults to `None`.
        """
        self.data_folders = []
        self.config = []
        self.FRONTEND_FOLDER = FRONTEND_FOLDER
        self.JWT_ACCESS_TOKEN_EXPIRES = JWT_ACCESS_TOKEN_EXPIRES
        self.JWT_ACCESS_TOKEN_REFRESH = JWT_ACCESS_TOKEN_REFRESH
        self.JWT_COOKIE_CSRF_PROTECT = JWT_COOKIE_CSRF_PROTECT
        self.JWT_COOKIE_DOMAIN = JWT_COOKIE_DOMAIN
        self.JWT_COOKIE_SAMESITE = JWT_COOKIE_SAMESITE
        self.JWT_COOKIE_SECURE = JWT_COOKIE_SECURE
        if MAX_IMAGE_BYTES <= 0:
            raise ValueError("MAX_IMAGE_BYTES must be positive")
        self.MAX_IMAGE_BYTES = MAX_IMAGE_BYTES
        self.JWT_SESSION_COOKIE = JWT_SESSION_COOKIE
        self.CACHE_MAX_AGE = CACHE_MAX_AGE
        self.MESSAGE_TO_FRONTEND = MESSAGE_TO_FRONTEND
        self.STATIC_FOLDERS = [*STATIC_FOLDERS]
        self.DEV_MODE = DEV_MODE
        self.LOG_ERROR_DETAILS = LOG_ERROR_DETAILS
        self.LOG_JSON_RESPONSES = DEV_MODE if LOG_JSON_RESPONSES is None else LOG_JSON_RESPONSES
        self.DELAY_MODE = DELAY_MODE
        self.PAGE404 = PAGE404
        self.HEALTH_ROUTE = "/api/health" if HEALTH_ROUTE is True else HEALTH_ROUTE
        if any(type(value) is not bool for value in (AUTO_SETUP, MULTIPROCESS_LOGGING, CONFIGURE_ROOT_LOGGING, LOG_ERROR_DETAILS)):
            raise TypeError("Startup and logging switches must be bool")
        if REQUEST_POLICY is not None and not isinstance(REQUEST_POLICY, RequestPolicy):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise TypeError("REQUEST_POLICY must be RequestPolicy or None")
        self.AUTO_SETUP = AUTO_SETUP
        self.MULTIPROCESS_LOGGING = MULTIPROCESS_LOGGING
        self.CONFIGURE_ROOT_LOGGING = CONFIGURE_ROOT_LOGGING
        self.REQUEST_POLICY = RequestPolicy.resolve(RequestPolicy(max_log_length=2048, authenticate=True), REQUEST_POLICY)
        self.CORS_HEADERS_PROD = CORS_HEADERS_PROD
        self.CORS_HEADERS_DEV = CORS_HEADERS_DEV
        self.add_data_folder("IMAGES_FOLDER", bafser_config.images_folder)
        self.add("MAX_IMAGE_BYTES", MAX_IMAGE_BYTES)
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
        Missing parent directories are created automatically.

        The value is stored in `current_app.config[key]`.

        Args:
            key: The configuration key.
            path: Path where the secret key is or should be stored.

        Returns:
            The AppConfig instance for method chaining.
        """
        loader = get_secret_key_rnd if self.AUTO_SETUP or "--setup" in sys.argv else get_secret_key
        self.add(key, loader(path))
        return self


class AccessControlHeaders:
    """Manages Access Control (CORS) header configuration for API responses.

    Attributes:
        origin (str): Allowed origin domain(s). Set to `"***"` for dynamic origin
            reflection (echoing the request's `Origin` header).
        credentials (bool): Indicates whether the response to the request can be exposed
            when the credentials flag is true.
        methods (str): Comma-separated list of allowed HTTP methods.
        headers (str): Comma-separated list of allowed HTTP request headers.
    """

    def __init__(
        self,
        origin: str = "*",
        credentials: bool = False,
        methods: str = "GET, POST, PUT, DELETE, PATCH, OPTIONS",
        headers: str = "Authorization, Content-Type, X-CSRF-TOKEN, X-Requested-With, Accept, Origin",
    ) -> None:
        """Initializes the AccessControlHeaders configuration.

        Args:
            origin (str, optional): The allowed origin pattern. Standard origin string,
                `"*"` for open access, or `"***"` to signal dynamic origin reflection
                based on incoming request headers. Defaults to `"*"` (Note: if
                `credentials=True`, `origin` should be specific or dynamic `"***"`).
            credentials (bool, optional): Allow credentials (cookies, authorization headers).
                Defaults to `False`.
            methods (str, optional): Allowed HTTP methods. Defaults to common REST methods.
            headers (str, optional): Allowed HTTP headers. Defaults to recommended standard set.
        """
        self.origin = origin
        self.credentials = credentials
        self.methods = methods
        self.headers = headers


@dataclass(frozen=True)
class RequestPolicy:
    """Request limits and diagnostics selected before reading the HTTP body.

    None log switches mean full diagnostics in development and metadata in
    production. A None body limit preserves Flask's application-wide limit.
    authenticate=True resolves an optional user JWT; protected_route requires login.
    authenticate=False ignores user cookies and disables their renewal.
    """

    max_content_length: int | None = None
    log_body: bool | None = None
    log_query: bool | None = None
    body_fields: tuple[str, ...] | None = None
    sensitive_fields: tuple[str, ...] = ()
    max_log_length: int | None = None
    authenticate: bool | None = None

    def __post_init__(self):
        if self.max_content_length is not None and (type(self.max_content_length) is not int or self.max_content_length <= 0):
            raise ValueError("max_content_length must be a positive integer or None")
        if self.max_log_length is not None and (type(self.max_log_length) is not int or self.max_log_length <= 0):
            raise ValueError("max_log_length must be a positive integer or None")
        for name in ("log_body", "log_query"):
            if getattr(self, name) is not None and type(getattr(self, name)) is not bool:
                raise TypeError(f"{name} must be bool or None")
        if self.authenticate is not None and type(self.authenticate) is not bool:
            raise TypeError("authenticate must be bool or None")
        if self.sensitive_fields is None:  # pyright: ignore[reportUnnecessaryComparison]
            raise TypeError("sensitive_fields must be a tuple of field names")
        for name in ("body_fields", "sensitive_fields"):
            value = getattr(self, name)
            if value is not None and (
                not isinstance(value, tuple) or any(not isinstance(key, str) or not key for key in value)  # pyright: ignore[reportUnknownVariableType]
            ):
                raise TypeError(f"{name} must contain nonempty field names")

    @staticmethod
    def resolve(base: "RequestPolicy", override: "RequestPolicy | None") -> "RequestPolicy":
        """None fields inherit the default; sensitive fields can only be extended."""
        if override is None:
            return base
        values = {
            name: getattr(override, name) if getattr(override, name) is not None else getattr(base, name)
            for name in ("max_content_length", "log_body", "log_query", "body_fields", "max_log_length", "authenticate")
        }
        values["sensitive_fields"] = tuple(dict.fromkeys((*base.sensitive_fields, *override.sensitive_fields)))
        return RequestPolicy(**values)


TFn = TypeVar("TFn", bound=Callable[..., Any])


def request_policy(policy: RequestPolicy):
    """Attach an early request policy to a Flask view, preserving its identity."""
    if not isinstance(policy, RequestPolicy):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise TypeError("policy must be RequestPolicy")

    def decorate(fn: TFn) -> TFn:
        fn._bafser_request_policy = policy  # type: ignore[attr-defined]
        return fn

    return decorate


def create_app(import_name: str, config: AppConfig):
    global _config
    _config = config
    setLogging(configure_root=config.CONFIGURE_ROOT_LOGGING)
    logreq = get_logger_requests()
    logdash = get_logger_dashboard()
    app = Flask(import_name, static_folder=None)
    app.extensions["bafser_config"] = config
    app.config["JWT_TOKEN_LOCATION"] = ["cookies"]
    extra_config = dict(config.config)
    prepare = config.AUTO_SETUP or "--setup" in sys.argv
    key_loader = get_secret_key_rnd if prepare else get_secret_key
    if "JWT_SECRET_KEY" in extra_config:
        key = extra_config["JWT_SECRET_KEY"]
        if not isinstance(key, (str, bytes)) or not key.strip():
            raise ValueError("JWT_SECRET_KEY must be a nonempty secret")
    else:
        key = key_loader(bafser_config.jwt_key_file_path)
    app.config["JWT_SECRET_KEY"] = key
    app.config["JWT_ACCESS_TOKEN_EXPIRES"] = config.JWT_ACCESS_TOKEN_EXPIRES
    app.config["JWT_SESSION_COOKIE"] = config.JWT_SESSION_COOKIE
    app.config["JWT_COOKIE_CSRF_PROTECT"] = config.JWT_COOKIE_CSRF_PROTECT
    app.config["JWT_COOKIE_DOMAIN"] = config.JWT_COOKIE_DOMAIN
    app.config["JWT_COOKIE_SAMESITE"] = config.JWT_COOKIE_SAMESITE
    app.config["JWT_COOKIE_SECURE"] = config.JWT_COOKIE_SECURE
    app.secret_key = app.config["JWT_SECRET_KEY"]
    for key, path in config.config:
        app.config[key] = path
    allow_unsupported_for_update_clause = getattr(bafser_config, "allow_unsupported_for_update_clause", None)
    if allow_unsupported_for_update_clause is None:
        bafser_config.allow_unsupported_for_update_clause = config.DEV_MODE

    jwt_manager = JWTManager(app)

    def log_internal_error(error: BaseException | None):
        if error is None:
            logging.error("Unhandled internal error", extra={"bafser_safe_message": True})
            return
        if log_error_details():
            logging.error("%s", error, exc_info=(type(error), error, error.__traceback__))
        else:
            frames: Any = traceback.extract_tb(error.__traceback__) if error.__traceback__ else []  # pyright: ignore[reportUnknownVariableType]
            locations = "\n".join(f"{frame.filename}:{frame.lineno} in {frame.name}" for frame in frames)
            logging.error("Unhandled %s\n%s", type(error).__name__, locations, extra={"bafser_safe_message": True})

    def log_flask_exception(exc_info: tuple[type, BaseException, Any] | tuple[None, None, None]):
        # Flask logs failures outside view dispatch (for example after_request)
        # before invoking a 500 handler. Apply the selected diagnostics policy
        # before host-owned handlers receive the record.
        log_internal_error(exc_info[1])

    app.log_exception = log_flask_exception

    register_blueprints(app)
    init_api_docs(app)

    for _, path in config.data_folders:
        if prepare:
            os.makedirs(path, exist_ok=True)
        elif not os.path.isdir(path):
            raise FileNotFoundError("A configured data directory is missing; run setup before starting workers")

    def run(
        run_server: bool,
        init_db: Callable[[Session, AppConfig], None] | None = None,
        init_dev_values: Callable[[Session, AppConfig], None] | None = None,
        port: int = 5000,
        host: str = "127.0.0.1",
    ):
        setup_only = "--setup" in sys.argv

        if config.AUTO_SETUP or setup_only:
            print("Setup database")
            with app.app_context():
                if bafser_config.use_alembic:
                    alembic_upgrade(config.DEV_MODE)
                db_session.global_init(config.DEV_MODE, create_tables=not bafser_config.use_alembic)
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
            previous_session = g.get("db_session")
            g.db_session = db_sess
            try:
                is_initialized = DBState.is_initialized(db_sess, commit=False)
                Role.update_roles_permissions(db_sess, commit=False)
                if not is_initialized:
                    print("initialize database")
                    UserBase._create_admin(db_sess, commit=False)  # type: ignore
                    if init_db is not None:
                        print("init_db")
                        init_db(db_sess, config)
                    if config.DEV_MODE and init_dev_values is not None:
                        print("init_dev_values")
                        init_dev_values(db_sess, config)
                    DBState.mark_as_initialized(db_sess, commit=False)

                if not config.DEV_MODE:
                    change_admin_default_pwd(db_sess)
                db_sess.commit()
            finally:
                if previous_session is None:
                    g.pop("db_session", None)
                else:
                    g.db_session = previous_session

    def change_admin_default_pwd(db_sess: Session):
        from .data.user import get_user_table

        User = get_user_table()
        admin = User.get_by_login("admin", includeDeleted=True, db_sess=db_sess)
        if admin is not None and admin.check_password("admin"):
            admin.set_password(randstr(16))

    api_root = bafser_config.api_url.rstrip("/")

    def is_api_request() -> bool:
        return request.path == api_root or request.path.startswith(api_root + "/")

    @app.before_request
    def before_request():  # type: ignore
        g.req_id = randstr(24)
        g.req_start = time.perf_counter_ns()
        g.json = (None, False)
        view = app.view_functions.get(request.endpoint) if request.endpoint else None
        policy = RequestPolicy.resolve(config.REQUEST_POLICY, getattr(view, "_bafser_request_policy", None))
        g.request_policy = policy
        if not policy.authenticate and getattr(view, "_doc_api_jwt", False):
            raise ValueError("A protected view cannot disable authentication in its request policy")
        if policy.max_content_length is not None:
            request.max_content_length = policy.max_content_length
        if request.max_content_length is not None and request.content_length is not None and request.content_length > request.max_content_length:
            raise RequestEntityTooLarge()
        if bafser_config.sql_echo:
            print(request.path)
        g.userId = None
        if policy.authenticate:
            try:
                verified = verify_jwt_in_request(optional=True)  # pyright: ignore[reportUnknownVariableType]
                if verified is not None:
                    g.userId = get_user_id_by_jwt_identity(get_jwt_identity())
            except (JWTExtendedException, PyJWTError):
                # Optional identity is absent/invalid; protected_route still
                # enforces its own JWT contract before invoking the view.
                pass
        if request.endpoint is not None:
            g.json = get_json(request)
        if is_api_request():
            try:
                data = format_log_data(g.json[0]) if g.json[1] else None
                if data is not None:
                    logreq.info("Request;;%s", data, extra={"bafser_safe_message": True})
                else:
                    logreq.info("Request", extra={"bafser_safe_message": True})
            except Exception:
                logging.error(
                    "Request diagnostics could not be formatted",
                    exc_info=True if log_error_details() else None,
                    extra={"bafser_safe_message": True},
                )

        if config.DELAY_MODE:
            time.sleep(0.5)

    @app.after_request
    def after_request(response: Response):  # type: ignore
        policy = g.get("request_policy", config.REQUEST_POLICY)
        access_cookie = app.config.get("JWT_ACCESS_COOKIE_NAME", "access_token_cookie")  # type: ignore
        access_cookie_already_set = any(header.startswith(f"{access_cookie}=") for header in response.headers.getlist("Set-Cookie"))
        if policy.authenticate:
            response.set_cookie("MESSAGE_TO_FRONTEND", quote(config.MESSAGE_TO_FRONTEND))
        if policy.authenticate and config.JWT_ACCESS_TOKEN_REFRESH and response.status_code < 400 and not access_cookie_already_set:
            try:
                claims: dict[Any, Any] = get_jwt()  # pyright: ignore[reportUnknownVariableType]
            except RuntimeError:
                claims = {}
            exp_timestamp = claims.get("exp")
            target_timestamp = (datetime.now(timezone.utc) + config.JWT_ACCESS_TOKEN_REFRESH).timestamp()
            if isinstance(exp_timestamp, (int, float)) and target_timestamp > exp_timestamp:
                access_token = renew_access_token(get_db_session(), get_jwt_identity())
                if access_token is not None:
                    set_access_cookies(response, access_token)
                else:
                    from flask_jwt_extended import unset_jwt_cookies

                    # Preserve the outcome of the completed view, but never
                    # extend a token which no longer matches current state.
                    unset_jwt_cookies(response)
        logdash.info("", extra={"code": response.status_code})
        if is_api_request():
            if not response.headers.get("Cache-Control"):
                response.headers["Cache-Control"] = "private, no-store"
            elif not response.cache_control.public and not response.cache_control.private:
                response.cache_control.private = True
            try:
                if (
                    config.LOG_JSON_RESPONSES
                    and should_log_body()
                    and response.is_json
                    and not response.is_streamed
                    and not response.direct_passthrough
                ):
                    try:
                        response_json = json.loads(response.get_data())
                    except (TypeError, ValueError):
                        logreq.info("Response;%s", response.status_code, extra={"bafser_safe_message": True})
                    else:
                        data = format_log_data(response_json)
                        if data is None:
                            logreq.info("Response;%s", response.status_code, extra={"bafser_safe_message": True})
                        else:
                            logreq.info("Response;%s;%s", response.status_code, data, extra={"bafser_safe_message": True})
                else:
                    logreq.info("Response;%s", response.status_code, extra={"bafser_safe_message": True})
            except Exception:
                logging.error(
                    "Response diagnostics could not be formatted",
                    exc_info=True if log_error_details() else None,
                    extra={"bafser_safe_message": True},
                )

        cors_config = config.CORS_HEADERS_DEV if config.DEV_MODE else config.CORS_HEADERS_PROD
        if cors_config:
            origin = request.headers.get("Origin", "*") if cors_config.origin == "***" else cors_config.origin

            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Methods"] = cors_config.methods
            response.headers["Access-Control-Allow-Headers"] = cors_config.headers

            if cors_config.credentials:
                response.headers["Access-Control-Allow-Credentials"] = "true"

            if cors_config.origin == "***":
                response.headers.add("Vary", "Origin")

        return response

    @app.teardown_appcontext
    def teardown(exception: BaseException | None = None):  # pyright: ignore[reportUnusedFunction]
        g.pop("user", None)
        db_sess = g.pop("db_session", None)
        if db_sess:
            try:
                db_sess.close()
            except Exception as x:
                log_internal_error(x)

    @app.route("/", defaults={"path": ""})
    @app.route("/<path:path>")
    def frontend(path: str):  # type: ignore
        if is_api_request():
            abort(404)

        if path == "":
            fname = "index.html"
        elif os.path.isfile(config.FRONTEND_FOLDER + "/" + path):
            fname = path
        elif os.path.isfile(config.FRONTEND_FOLDER + "/" + path + ".html"):
            fname = path + ".html"
        elif "." in os.path.basename(path):
            abort(404)
        else:
            fname = config.PAGE404

        res = send_from_directory(config.FRONTEND_FOLDER, fname)
        is_page = fname == config.PAGE404 or fname.lower().endswith((".html", ".htm"))
        if not is_page and any(request.path.startswith(path) for path in config.STATIC_FOLDERS):
            res.headers.set("Cache-Control", f"public,max-age={config.CACHE_MAX_AGE},immutable")
        else:
            res.headers.set("Cache-Control", "public,max-age=60,stale-while-revalidate=600,stale-if-error=14400")
        return res

    if config.HEALTH_ROUTE:

        @app.route(config.HEALTH_ROUTE)
        def health():  # pyright: ignore[reportUnusedFunction]
            try:
                with db_session.create_session() as db_sess:
                    db_sess.execute(text("SELECT 1")).scalar()
                return jsonify(status="ok"), 200
            except Exception:
                logging.error(
                    "Database health check failed",
                    exc_info=True if log_error_details() else None,
                    extra={"bafser_safe_message": True},
                )
                return jsonify(status="unhealthy"), 500

    def http_error(error: HTTPException, message: str | None = None):
        rollback_failed_request()
        response = error.get_response()
        if is_api_request():
            response.set_data(json.dumps({"msg": message or error.name}))
            response.content_type = "application/json"
        return response

    @app.errorhandler(HTTPException)
    def http_exception(error: HTTPException):
        return http_error(error)

    @app.errorhandler(404)
    def not_found(error: Exception):  # pyright: ignore[reportUnusedFunction]
        if is_api_request():
            return http_error(error, "Not found")  # type: ignore[arg-type]
        return make_response("Страница не найдена", 404)

    @app.errorhandler(405)
    def method_not_allowed(error: Exception):  # pyright: ignore[reportUnusedFunction]
        return http_error(error, "Method Not Allowed")  # type: ignore[arg-type]

    @app.errorhandler(415)
    def unsupported_media_type(error: Exception):  # pyright: ignore[reportUnusedFunction]
        return http_error(error, "Unsupported Media Type")  # type: ignore[arg-type]

    @app.errorhandler(403)
    def no_permission(error: Exception):  # pyright: ignore[reportUnusedFunction]
        return http_error(error, "No permission")  # type: ignore[arg-type]

    def rollback_failed_request():
        session = g.get("db_session")
        if session is not None:
            try:
                session.rollback()
            except Exception:
                logging.error(
                    "Request rollback failed",
                    exc_info=True if log_error_details() else None,
                    extra={"bafser_safe_message": True},
                )

    @app.errorhandler(PublicError)
    def public_error(error: PublicError):  # pyright: ignore[reportUnusedFunction]
        rollback_failed_request()
        if is_api_request():
            return jsonify(error.get_dict()), error.status
        return make_response("Произошла ошибка", error.status)

    @app.errorhandler(500)
    @app.errorhandler(Exception)
    def internal_server_error(error: Exception):  # pyright: ignore[reportUnusedFunction]
        rollback_failed_request()
        log_internal_error(error)
        if is_api_request():
            return response_msg("Internal Server Error", 500)
        return make_response("Произошла ошибка", 500)

    @app.errorhandler(401)
    def unauthorized(error: HTTPException):  # pyright: ignore[reportUnusedFunction]
        if not is_api_request():
            rollback_failed_request()
            return redirect(bafser_config.login_page_url + "?redirect=" + request.path)
        return http_error(error, "Unauthorized")

    @jwt_manager.expired_token_loader  # type: ignore
    def expired_token_loader(jwt_header: dict[str, Any], jwt_data: dict[str, Any]):  # type: ignore
        if not is_api_request():
            return redirect(bafser_config.login_page_url + "?redirect=" + request.path)
        return response_msg("The JWT has expired", 401)

    @jwt_manager.invalid_token_loader  # type: ignore
    def invalid_token_loader(error: Exception):  # pyright: ignore[reportUnusedFunction]
        if not is_api_request():
            return redirect(bafser_config.login_page_url + "?redirect=" + request.path)
        return response_msg("Invalid JWT", 401)

    @jwt_manager.unauthorized_loader  # type: ignore
    def unauthorized_loader(error: Exception):  # pyright: ignore[reportUnusedFunction]
        if not is_api_request():
            return redirect(bafser_config.login_page_url + "?redirect=" + request.path)
        return response_msg("Unauthorized", 401)

    return app, run


def update_message_to_frontend(msg: str):
    assert _config
    _config.MESSAGE_TO_FRONTEND = msg


def get_app_config():
    if has_app_context() and "bafser_config" in current_app.extensions:
        return current_app.extensions["bafser_config"]
    assert _config
    return _config
