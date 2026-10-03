"""Regression tests for request handling, validation, and database writes."""

import io
import importlib
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from flask import Flask, jsonify, make_response
from flask_jwt_extended import create_access_token, unset_jwt_cookies  # type: ignore
from flask_jwt_extended.exceptions import NoAuthorizationError
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from bafser import AppConfig, JsonObj, Log, Role, SqlAlchemyBase, UserRole, create_app
from bafser.data.user import UserBase
from bafser.jsonobj import validate_type


class ValidationTests(unittest.TestCase):
    def test_unknown_json_fields_cannot_replace_methods(self):
        class Payload(JsonObj):
            name: str

        payload = Payload.new({"name": "example", "validate": "broken", "extra": 1})
        self.assertIsNone(payload.validate())
        self.assertEqual(payload.json(), {"name": "example"})
        self.assertNotIn("extra", vars(payload))

    def test_integer_rejects_boolean_and_tuple_checks_each_position(self):
        self.assertIsNotNone(validate_type(True, int)[1])
        self.assertEqual(validate_type((1, "x"), tuple[int, str]), ((1, "x"), None))
        self.assertIsNotNone(validate_type((1, 2), tuple[int, str])[1])
        self.assertEqual(validate_type((1, 2), tuple[int, ...]), ((1, 2), None))


class AppTests(unittest.TestCase):
    def test_add_secret_key_rnd_creates_parent_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            key_path = Path(directory) / "nested" / "keys" / "secret.txt"

            first = AppConfig().add_secret_key_rnd("TEST_SECRET", str(key_path))
            second = AppConfig().add_secret_key_rnd("TEST_SECRET", str(key_path))

            self.assertTrue(key_path.is_file())
            self.assertEqual(first.config[-1], ("TEST_SECRET", key_path.read_text(encoding="utf8")))
            self.assertEqual(second.config[-1], first.config[-1])

    def make_app(
        self,
        directory: Path,
        *,
        health_route: str = "/healthz",
        dev_mode: bool = False,
        log_json_responses: bool | None = None,
    ):
        logger = Mock()
        with (
            patch("bafser.app.setLogging"),
            patch("bafser.app.get_logger_requests", return_value=logger),
            patch("bafser.app.get_logger_dashboard", return_value=Mock()),
            patch("bafser.app.register_blueprints"),
            patch("bafser.app.init_api_docs"),
            patch("bafser_config.jwt_key_file_path", str(directory / "jwt.key")),
            patch("bafser_config.images_folder", str(directory / "images")),
        ):
            app, _ = create_app(
                __name__,
                AppConfig(
                    HEALTH_ROUTE=health_route,
                    DEV_MODE=dev_mode,
                    LOG_JSON_RESPONSES=log_json_responses,
                    JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=5),
                    JWT_ACCESS_TOKEN_REFRESH=timedelta(minutes=30),
                ),
            )
        app.testing = True
        return app, logger

    def test_health_route_uses_configured_path(self):
        with tempfile.TemporaryDirectory() as directory:
            app, _ = self.make_app(Path(directory))
            self.assertIn("/healthz", {rule.rule for rule in app.url_map.iter_rules()})
            self.assertNotIn("/api/health", {rule.rule for rule in app.url_map.iter_rules()})

    def test_logout_does_not_refresh_deleted_cookie(self):
        with tempfile.TemporaryDirectory() as directory:
            app, _ = self.make_app(Path(directory))

            @app.get("/api/logout")
            def logout():
                response = make_response("bye")
                unset_jwt_cookies(response)
                return response

            with app.app_context():
                token = create_access_token(identity="user")
            client = app.test_client()
            client.set_cookie("access_token_cookie", token)
            response = client.get("/api/logout")
            cookies = [value for value in response.headers.getlist("Set-Cookie") if value.startswith("access_token_cookie=")]
            self.assertEqual(len(cookies), 1)
            self.assertIn("Expires=Thu, 01 Jan 1970", cookies[0])

    def test_active_request_still_refreshes_near_expiring_cookie(self):
        with tempfile.TemporaryDirectory() as directory:
            app, _ = self.make_app(Path(directory))

            @app.get("/api/ping")
            def ping():
                return "pong"

            with app.app_context():
                token = create_access_token(identity="user")
            client = app.test_client()
            client.set_cookie("access_token_cookie", token)
            response = client.get("/api/ping")
            cookies = [value for value in response.headers.getlist("Set-Cookie") if value.startswith("access_token_cookie=")]
            self.assertEqual(len(cookies), 1)
            self.assertNotIn("Expires=Thu, 01 Jan 1970", cookies[0])

    def test_json_response_body_is_not_logged(self):
        with tempfile.TemporaryDirectory() as directory:
            app, logger = self.make_app(Path(directory))

            @app.get("/api/secret")
            def secret():
                return jsonify(access_token="secret-value")

            self.assertEqual(app.test_client().get("/api/secret").status_code, 200)
            self.assertNotIn("secret-value", str(logger.info.call_args_list))

    def test_json_response_body_is_logged_in_dev_with_redaction(self):
        with tempfile.TemporaryDirectory() as directory:
            app, logger = self.make_app(Path(directory), dev_mode=True)

            @app.get("/api/secret")
            def secret():
                return jsonify(message="visible", access_token="secret-value")

            self.assertEqual(app.test_client().get("/api/secret").status_code, 200)
            calls = str(logger.info.call_args_list)
            self.assertIn("visible", calls)
            self.assertIn("***", calls)
            self.assertNotIn("secret-value", calls)

    def test_json_response_logging_can_be_explicitly_disabled_in_dev(self):
        with tempfile.TemporaryDirectory() as directory:
            app, logger = self.make_app(Path(directory), dev_mode=True, log_json_responses=False)

            @app.get("/api/data")
            def data():
                return jsonify(message="not-logged")

            app.test_client().get("/api/data")
            self.assertNotIn("not-logged", str(logger.info.call_args_list))

    def test_json_response_logging_can_be_explicitly_enabled_in_production(self):
        with tempfile.TemporaryDirectory() as directory:
            app, logger = self.make_app(Path(directory), log_json_responses=True)

            @app.get("/api/data")
            def data():
                return jsonify(message="logged")

            app.test_client().get("/api/data")
            self.assertIn("logged", str(logger.info.call_args_list))


class DatabaseTests(unittest.TestCase):
    def test_log_added_flushes_new_id_without_commit_unless_disabled(self):
        from test.data.apple import Apple  # type: ignore
        from test.data.img import Img  # type: ignore
        from test.data.user import User

        engine = create_engine("sqlite:///:memory:")
        SqlAlchemyBase.metadata.create_all(engine)
        with Session(engine) as session:
            actor = User(login="admin", name="Admin", balance=0)
            actor.set_password("password")
            session.add(actor)
            session.commit()

            delayed_user = User(login="delayed-user", name="Delayed User", balance=0)
            delayed_user.set_password("password")
            delayed_log = Log.added(delayed_user, actor, commit=False, db_sess=session, flush=False)
            self.assertIsNone(delayed_user.id)
            self.assertEqual(delayed_log.recordId, -1)

            user = User(login="new-user", name="New User", balance=0)
            user.set_password("password")
            log = Log.added(user, actor, commit=False, db_sess=session)
            self.assertIsNotNone(user.id)
            self.assertEqual(log.recordId, user.id)
            session.rollback()

            committed_user = User(login="committed-user", name="Committed User", balance=0)
            committed_user.set_password("password")
            committed_log = Log.added(committed_user, actor, db_sess=session)
            self.assertEqual(committed_log.recordId, committed_user.id)
            self.assertIsNotNone(session.get(Log, committed_log.id))
        engine.dispose()

    def test_failed_role_assignment_does_not_save_user(self):
        from test.data.apple import Apple  # type: ignore
        from test.data.img import Img  # type: ignore
        from test.data.user import User

        engine = create_engine("sqlite:///:memory:")

        @event.listens_for(engine, "connect")
        def enable_foreign_keys(connection, record):  # type: ignore
            connection.execute("PRAGMA foreign_keys=ON")  # type: ignore

        SqlAlchemyBase.metadata.create_all(engine)
        with Session(engine) as session:
            admin = User(login="admin", name="Admin", balance=0)
            admin.set_password("admin")
            role = Role(name="Admin")
            role.id = 1
            session.add_all([role, admin])
            session.commit()

            with self.assertRaises(IntegrityError):
                User.new(admin, "new-user", "password", "New User", [999], 0, db_sess=session)
            session.rollback()
            self.assertIsNone(User.get_by_login(session, "new-user"))

            user = User.new(admin, "new-user", "password", "New User", [1], 0, db_sess=session)
            self.assertIsNotNone(UserRole.get(session, user.id, 1))
            user_log = session.query(Log).filter_by(tableName="User", recordId=user.id).one()
            self.assertTrue(any(change[0] == "login" for change in user_log.changes))
        engine.dispose()

    def test_existing_operation_name_is_updated(self):
        from test.data.apple import Apple  # type: ignore
        from test.data.img import Img  # type: ignore
        from test.data.user import User  # type: ignore

        from bafser.data.operation import Operation

        class Operations:
            @staticmethod
            def get_all():
                return [("edit", "New name")]

        class Roles:
            ROLES = {}

        engine = create_engine("sqlite:///:memory:")
        SqlAlchemyBase.metadata.create_all(engine)
        with Session(engine) as session:
            role = Role(name="Admin")
            role.id = 1
            session.add_all([role, Operation(id="edit", name="Old name")])
            session.commit()
            with (
                patch("bafser.data.role.get_operations", return_value=Operations),
                patch("bafser.data.role.get_roles", return_value=Roles),
            ):
                Role.update_roles_permissions(session)
            self.assertEqual(session.get(Operation, "edit").name, "New name")  # type: ignore
        engine.dispose()

    def test_schema_creation_depends_on_alembic_setting(self):
        from bafser import db_session

        for use_alembic in (True, False):
            with self.subTest(use_alembic=use_alembic):
                with (
                    patch("bafser_config.use_alembic", use_alembic),
                    patch("bafser_config.db_mysql", False),
                    patch.object(db_session, "__factory", None),
                    patch.object(db_session, "setup_sqlite"),
                    patch.object(db_session, "get_db_path", return_value="test.sqlite"),
                    patch.object(db_session, "import_all_tables"),
                    patch.object(db_session.sa, "create_engine"),
                    patch.object(db_session.orm, "sessionmaker"),
                    patch.object(SqlAlchemyBase.metadata, "create_all") as create_all,
                ):
                    db_session.global_init(dev=False)
                self.assertEqual(create_all.call_count, 0 if use_alembic else 1)


class CurrentUserTests(unittest.TestCase):
    def test_database_error_propagates(self):
        app = Flask(__name__)
        with app.test_request_context("/"):
            with (
                patch("bafser.data.user.verify_jwt_in_request"),
                patch("bafser.get_db_session", side_effect=RuntimeError("database unavailable")),
            ):
                with self.assertRaisesRegex(RuntimeError, "database unavailable"):
                    UserBase._get_current(False, False)  # type: ignore

    def test_missing_token_returns_none(self):
        app = Flask(__name__)
        with app.test_request_context("/"):
            with patch("bafser.data.user.verify_jwt_in_request", side_effect=NoAuthorizationError("missing")):
                self.assertIsNone(UserBase._get_current(False, False))  # type: ignore


class CommandTests(unittest.TestCase):
    def test_password_commands_read_stdin_without_echoing_secret(self):
        for module, args in (
            (importlib.import_module("bafser.scripts.add_user"), ["alice", "Alice", "2"]),
            (importlib.import_module("bafser.scripts.change_user_password"), ["alice"]),
        ):
            output = io.StringIO()
            with (
                patch("sys.stdin", io.StringIO("private-password\n")),
                patch.object(module, module.__name__.split(".")[-1]) as command,
                redirect_stdout(output),
            ):
                module.run(args)
            self.assertEqual(command.call_args.args[1], "private-password")
            self.assertNotIn("private-password", output.getvalue())

    def test_init_project_preserves_files_until_force_is_requested(self):
        module = importlib.import_module("bafser.scripts.init_project")
        with tempfile.TemporaryDirectory() as directory:
            previous_cwd = os.getcwd()
            try:
                os.chdir(directory)
                with (
                    patch("builtins.input", return_value="n"),
                    patch.dict(sys.modules, {"bafser_tgapi": None}),
                    patch("bafser_config.data_tables_folder", "data"),
                    patch("bafser_config.blueprints_folder", "blueprints"),
                    patch("bafser_config.migrations_folder", "alembic"),
                    patch("bafser_config.use_alembic", True),
                ):
                    module.run([])
                    paths = [Path("main.py"), Path("data/user.py"), Path("alembic/env.py"), Path(".gitignore")]
                    for path in paths:
                        path.write_text("custom content", encoding="utf-8")
                    module.run([])
                    self.assertTrue(all(path.read_text(encoding="utf-8") == "custom content" for path in paths))
                    module.run(["--force"])
                    self.assertTrue(all(path.read_text(encoding="utf-8") != "custom content" for path in paths))
            finally:
                os.chdir(previous_cwd)


if __name__ == "__main__":
    unittest.main()
