from datetime import datetime, timedelta, timezone
from typing import Callable, Literal, Union
import json
import logging
import os
import time
import traceback

from flask import Flask, Response, abort, g, make_response, redirect, request, send_from_directory
from flask_jwt_extended import JWTManager, create_access_token, get_jwt, get_jwt_identity, set_access_cookies, verify_jwt_in_request
from urllib.parse import quote

from bafser.scripts.init_db_values import init_db_values

from . import db_session
from .logger import get_logger_requests, setLogging
from .utils import get_json, get_secret_key, get_secret_key_rnd, randstr, register_blueprints, response_msg
import bafser_config


class AppConfig():
    data_folders: list[tuple[str, str]] = []
    config: list[tuple[str, str]] = []

    def __init__(self,
                 FRONTEND_FOLDER="build",
                 IMAGES_FOLDER="images",
                 JWT_ACCESS_TOKEN_EXPIRES: Union[Literal[False], timedelta] = False,
                 JWT_ACCESS_TOKEN_REFRESH: Union[Literal[False], timedelta] = timedelta(minutes=30),
                 CACHE_MAX_AGE=31536000,
                 MESSAGE_TO_FRONTEND="",
                 STATIC_FOLDERS: list[str] = ["/static/", "/fonts/"],
                 DEV_MODE=False,
                 DELAY_MODE=False,
                 ):
        self.FRONTEND_FOLDER = FRONTEND_FOLDER
        self.IMAGES_FOLDER = IMAGES_FOLDER
        self.JWT_ACCESS_TOKEN_EXPIRES = JWT_ACCESS_TOKEN_EXPIRES
        self.JWT_ACCESS_TOKEN_REFRESH = JWT_ACCESS_TOKEN_REFRESH
        self.CACHE_MAX_AGE = CACHE_MAX_AGE
        self.MESSAGE_TO_FRONTEND = MESSAGE_TO_FRONTEND
        self.STATIC_FOLDERS = STATIC_FOLDERS
        self.DEV_MODE = DEV_MODE
        self.DELAY_MODE = DELAY_MODE
        self.add_data_folder("IMAGES_FOLDER", IMAGES_FOLDER)
        self.add("CACHE_MAX_AGE", CACHE_MAX_AGE)

    def add(self, key: str, value: str):
        self.config.append((key, value))
        return self

    def add_data_folder(self, key: str, path: str):
        self.add(key, path)
        self.data_folders.append((key, path))
        return self

    def add_secret_key(self, key: str, path: str):
        self.add(key, get_secret_key(path))
        return self

    def add_secret_key_rnd(self, key: str, path: str):
        self.add(key, get_secret_key_rnd(path))
        return self


def create_app(import_name: str, config: AppConfig):
    setLogging()
    logreq = get_logger_requests()
    app = Flask(import_name, static_folder=None)
    app.config["JWT_TOKEN_LOCATION"] = ["cookies"]
    app.config["JWT_SECRET_KEY"] = get_secret_key_rnd(bafser_config.jwt_key_file_path)
    app.config["JWT_ACCESS_TOKEN_EXPIRES"] = config.JWT_ACCESS_TOKEN_EXPIRES
    app.config["JWT_COOKIE_CSRF_PROTECT"] = False
    app.config["JWT_SESSION_COOKIE"] = False
    for (key, path) in config.config:
        app.config[key] = path

    jwt_manager = JWTManager(app)

    def run(run_app: bool, init_dev_values: Callable[[], None] = None, port=5000):
        for (_, path) in config.data_folders:
            if not os.path.exists(path):
                os.makedirs(path)

        if config.DEV_MODE:
            if not os.path.exists(bafser_config.db_dev_path):
                os.makedirs(os.path.dirname(bafser_config.db_dev_path), exist_ok=True)
                init_db_values(True)
                if init_dev_values is not None:
                    init_dev_values()

        db_session.global_init(config.DEV_MODE)

        if not config.DEV_MODE:
            change_admin_default_pwd()

        register_blueprints(app)
        if run_app:
            print(f"Starting on port={port}")
            if config.DELAY_MODE:
                print("Delay for requests is enabled")
            app.run(debug=config.DEV_MODE, port=port)

    def change_admin_default_pwd():
        from . import UserBase
        db_sess = db_session.create_session()
        admin = UserBase.get_by_login(db_sess, "admin", includeDeleted=True)
        if admin is not None and admin.check_password("admin"):
            admin.set_password(randstr(16))
            db_sess.commit()
        db_sess.close()

    @app.before_request
    def before_request():
        g.json = get_json(request)
        g.req_id = randstr(4)
        try:
            verify_jwt_in_request()
            jwt_identity = get_jwt_identity()
        except Exception:
            jwt_identity = None
        if jwt_identity and isinstance(jwt_identity, (list, tuple)) and len(jwt_identity) == 2:
            g.userId = jwt_identity[0]
        if request.path.startswith(bafser_config.api_url):
            try:
                if g.json[1]:
                    if "password" in g.json[0]:
                        password = g.json[0]["password"]
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
    def after_request(response: Response):
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
                exp_timestamp = get_jwt()["exp"]
                now = datetime.now(timezone.utc)
                target_timestamp = datetime.timestamp(now + config.JWT_ACCESS_TOKEN_REFRESH)
                if target_timestamp > exp_timestamp:
                    access_token = create_access_token(identity=get_jwt_identity())
                    set_access_cookies(response, access_token)
            except (RuntimeError, KeyError):
                # Case where there is not a valid JWT
                pass

        return response

    @app.route("/", defaults={"path": ""})
    @app.route("/<path:path>")
    def frontend(path):
        if request.path.startswith(bafser_config.api_url):
            abort(404)
        if path != "" and os.path.exists(config.FRONTEND_FOLDER + "/" + path):
            res = send_from_directory(config.FRONTEND_FOLDER, path)
            if any(request.path.startswith(path) for path in config.STATIC_FOLDERS):
                res.headers.set("Cache-Control", f"public,max-age={config.CACHE_MAX_AGE},immutable")
            else:
                res.headers.set("Cache-Control", "no_cache")
            return res
        else:
            res = send_from_directory(config.FRONTEND_FOLDER, "index.html")
            res.headers.set("Cache-Control", "no_cache")
            return res

    @app.errorhandler(404)
    def not_found(error):
        if request.path.startswith(bafser_config.api_url):
            return response_msg("Not found", 404)
        return make_response("Страница не найдена", 404)

    @app.errorhandler(405)
    def method_not_allowed(error):
        return response_msg("Method Not Allowed", 405)

    @app.errorhandler(415)
    def unsupported_media_type(error):
        return response_msg("Unsupported Media Type", 415)

    @app.errorhandler(403)
    def no_permission(error):
        return response_msg("No permission", 403)

    @app.errorhandler(500)
    @app.errorhandler(Exception)
    def internal_server_error(error):
        print(error)
        logging.error("%s\n%s", error, traceback.format_exc())
        if request.path.startswith(bafser_config.api_url):
            return response_msg("Internal Server Error", 500)
        return make_response("Произошла ошибка", 500)

    @app.errorhandler(401)
    def unauthorized(error):
        if request.path.startswith(bafser_config.api_url):
            return response_msg("Unauthorized", 401)
        return redirect(bafser_config.login_page_url)

    @jwt_manager.expired_token_loader
    def expired_token_loader(jwt_header, jwt_data):
        return response_msg("The JWT has expired", 401)

    @jwt_manager.invalid_token_loader
    def invalid_token_loader(error):
        return response_msg("Invalid JWT", 401)

    @jwt_manager.unauthorized_loader
    def unauthorized_loader(error):
        return response_msg("Unauthorized", 401)

    return app, run
