"""Real user state is checked at renewal, without adding a DB read to fast polling."""

import tempfile
import unittest
from contextlib import ExitStack
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from flask import g, make_response
from flask_jwt_extended import decode_token, unset_jwt_cookies
from sqlalchemy import create_engine, delete, event, inspect
from sqlalchemy.orm import Session

from bafser import AppConfig, Log, SqlAlchemyBase, create_app
from bafser.app import RequestPolicy, request_policy
from bafser.authentication import create_access_token, get_user_id_by_jwt_identity
from test.data.apple import Apple  # noqa: F401
from test.data.img import Img  # noqa: F401
from test.data.user import User


class HttpAuthRefreshTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.engine = create_engine(
            f"sqlite:///{self.root / 'users.db'}", hide_parameters=True, pool_size=1, max_overflow=0, pool_timeout=0.2
        )
        self.stack.callback(self.engine.dispose)
        SqlAlchemyBase.metadata.create_all(self.engine)
        with Session(self.engine, expire_on_commit=False) as session:
            self.user = User(login="refresh-user", name="Refresh User", balance=0)
            self.user.password = "initial-stored-password-hash"
            session.add(self.user)
            session.commit()
        self.user_id = self.user.id
        self.statements = []
        event.listen(self.engine, "before_cursor_execute", self.record_statement)

        key_path = self.root / "jwt.key"
        key_path.write_text("http-refresh-test-key-with-at-least-32-bytes", encoding="utf8")
        images_path = self.root / "images"
        images_path.mkdir()
        with (
            patch("bafser.app.setLogging"),
            patch("bafser.app.get_logger_requests", return_value=Mock()),
            patch("bafser.app.get_logger_dashboard", return_value=Mock()),
            patch("bafser.app.register_blueprints"),
            patch("bafser.app.init_api_docs"),
            patch("bafser_config.jwt_key_file_path", str(key_path)),
            patch("bafser_config.images_folder", str(images_path)),
        ):
            self.app, _ = create_app(__name__, AppConfig(AUTO_SETUP=False, JWT_COOKIE_SECURE=True))
        self.app.config.update(TESTING=True, PROPAGATE_EXCEPTIONS=False)

        @self.app.get("/api/poll")
        def poll():
            return {"completed": True, "userId": g.userId}

        @self.app.get("/api/logout")
        def logout():
            response = make_response("logged out")
            unset_jwt_cookies(response)
            return response

        @self.app.get("/api/public")
        @request_policy(RequestPolicy(authenticate=False))
        def public():
            return {"userId": g.userId}

        self.client = self.app.test_client()
        self.get_session = Mock(side_effect=self.request_session)
        self.stack.enter_context(patch("bafser.app.get_db_session", self.get_session))
        self.stack.enter_context(patch("bafser.get_db_session", self.get_session))

    def record_statement(self, connection, cursor, statement, parameters, context, executemany):
        self.statements.append(statement)

    def request_session(self):
        if "db_session" not in g:
            g.db_session = Session(self.engine)
        return g.db_session

    def issue(self, expires_in=timedelta(minutes=5)):
        with self.app.app_context():
            original = self.app.config["JWT_ACCESS_TOKEN_EXPIRES"]
            self.app.config["JWT_ACCESS_TOKEN_EXPIRES"] = expires_in
            try:
                token = create_access_token(self.user)
            finally:
                self.app.config["JWT_ACCESS_TOKEN_EXPIRES"] = original
        self.client.set_cookie("access_token_cookie", token)
        self.statements.clear()
        self.get_session.reset_mock()
        return token

    def get(self, path):
        return self.client.get(path, base_url="https://localhost")

    def access_cookies(self, response):
        return [header for header in response.headers.getlist("Set-Cookie") if header.startswith("access_token_cookie=")]

    def assert_revoked_response(self, response):
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["completed"])
        cookies = self.access_cookies(response)
        self.assertEqual(len(cookies), 1)
        self.assertIn("Expires=Thu, 01 Jan 1970", cookies[0])
        self.get_session.assert_called_once()
        self.assertEqual(len(self.statements), 1)

    def test_current_user_near_expiry_gets_a_fresh_default_lifetime_token(self):
        original = self.issue()
        response = self.get("/api/poll")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"completed": True, "userId": self.user_id})
        self.get_session.assert_called_once()
        self.assertEqual(len(self.statements), 1)
        cookies = self.access_cookies(response)
        self.assertEqual(len(cookies), 1)
        refreshed = cookies[0].split(";", 1)[0].split("=", 1)[1]
        self.assertNotEqual(refreshed, original)
        with self.app.app_context():
            decoded = decode_token(refreshed)
        self.assertEqual(decoded["exp"] - decoded["iat"], 24 * 60 * 60)
        self.assertEqual(get_user_id_by_jwt_identity(decoded["sub"]), self.user_id)
        self.assertNotIn(self.user.password, decoded["sub"])

    def test_default_lifetime_polling_does_not_read_current_user_state(self):
        self.issue(timedelta(hours=24))
        for _ in range(3):
            response = self.get("/api/poll")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["userId"], self.user_id)
            self.assertEqual(self.access_cookies(response), [])
        self.get_session.assert_not_called()
        self.assertEqual(self.statements, [])

    def test_changed_password_blocks_refresh_but_preserves_completed_view(self):
        self.issue()
        with Session(self.engine) as session:
            user = session.get(User, self.user_id)
            user.password = "replacement-stored-password-hash"
            session.commit()
        self.statements.clear()
        self.assert_revoked_response(self.get("/api/poll"))

    def test_soft_deleted_user_cannot_refresh(self):
        self.issue()
        with Session(self.engine) as session:
            user = session.get(User, self.user_id)
            user.deleted = True
            session.commit()
        self.statements.clear()
        self.assert_revoked_response(self.get("/api/poll"))

    def test_missing_user_cannot_refresh(self):
        self.issue()
        with Session(self.engine) as session:
            session.execute(delete(User).where(User.id == self.user_id))
            session.commit()
        self.statements.clear()
        self.assert_revoked_response(self.get("/api/poll"))

    def test_external_password_change_after_loading_user_prevents_renewal(self):
        writer_engine = create_engine(self.engine.url)
        self.stack.callback(writer_engine.dispose)

        @self.app.get("/api/change-after-load")
        def change_after_load():
            session = self.request_session()
            g.user = session.get(User, self.user_id)
            with writer_engine.connect() as connection:
                connection.execute(User.__table__.update().where(User.id == self.user_id).values(password="external-password"))
                connection.commit()
            self.assertEqual(g.user.password, self.user.password)
            return {"completed": True}

        self.issue()
        response = self.get("/api/change-after-load")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["completed"])
        cookies = self.access_cookies(response)
        self.assertEqual(len(cookies), 1)
        self.assertIn("Expires=Thu, 01 Jan 1970", cookies[0])

    def test_renewal_preserves_dirty_user_and_request_transaction_with_single_connection_pool(self):
        @self.app.get("/api/dirty-user")
        def dirty_user():
            session = self.request_session()
            g.user = session.get(User, self.user_id)
            g.user.password = "pending-password"
            g.user.name = "Pending name"
            return {"completed": True}

        original = self.issue()
        with self.app.app_context():
            # Keep the app context open to inspect the Session after renewal,
            # before the normal request-owner teardown closes it.
            session = self.request_session()
            with (
                patch.object(session, "commit", wraps=session.commit) as commit,
                patch.object(session, "rollback", wraps=session.rollback) as rollback,
            ):
                response = self.get("/api/dirty-user")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(len(self.access_cookies(response)), 1)
                self.assertNotIn("Expires=Thu, 01 Jan 1970", self.access_cookies(response)[0])
                refreshed = self.access_cookies(response)[0].split(";", 1)[0].split("=", 1)[1]
                self.assertEqual(decode_token(refreshed)["sub"], decode_token(original)["sub"])
                self.assertEqual(g.user.password, "pending-password")
                self.assertEqual(g.user.name, "Pending name")
                self.assertIn(g.user, session.dirty)
                self.assertTrue(inspect(g.user).attrs.password.history.has_changes())
                self.assertTrue(session.in_transaction())
                commit.assert_not_called()
                rollback.assert_not_called()
            self.assertFalse(any(statement.lstrip().upper().startswith("UPDATE") for statement in self.statements))
        with Session(self.engine) as session:
            self.assertEqual(session.get(User, self.user_id).password, self.user.password)

    def test_flushed_uncommitted_password_is_not_minted_into_a_new_token(self):
        @self.app.get("/api/flushed-user")
        def flushed_user():
            session = self.request_session()
            g.user = session.get(User, self.user_id)
            g.user.password = "flushed-uncommitted-password"
            session.flush()
            return {"completed": True}

        self.issue()
        response = self.get("/api/flushed-user")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Expires=Thu, 01 Jan 1970", self.access_cookies(response)[0])
        with Session(self.engine) as session:
            self.assertEqual(session.get(User, self.user_id).password, self.user.password)

    def test_database_failure_is_500_and_does_not_mint_a_token(self):
        self.issue()
        User.__table__.drop(self.engine)
        self.statements.clear()
        response = self.get("/api/poll")
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.get_json(), {"msg": "Internal Server Error"})
        self.assertEqual(self.access_cookies(response), [])
        self.get_session.assert_called_once()

    def test_logout_does_not_read_db_or_replace_cookie_with_fresh_token(self):
        self.issue()
        response = self.get("/api/logout")
        self.assertEqual(response.status_code, 200)
        cookies = self.access_cookies(response)
        self.assertEqual(len(cookies), 1)
        self.assertIn("Expires=Thu, 01 Jan 1970", cookies[0])
        self.get_session.assert_not_called()
        self.assertEqual(self.statements, [])

    def test_public_policy_ignores_valid_user_cookie_and_has_no_set_cookie(self):
        self.issue()
        response = self.get("/api/public")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"userId": None})
        self.assertEqual(response.headers.getlist("Set-Cookie"), [])
        self.get_session.assert_not_called()
        self.assertEqual(self.statements, [])

    def test_public_policy_blocks_cached_and_locked_current_user_resolution(self):
        @self.app.get("/api/public-current-user")
        @request_policy(RequestPolicy(authenticate=False))
        def public_current_user():
            uncached = User.get_current()
            g.user = self.user
            return {
                "uncached": uncached is None,
                "cached": User.get_current() is None,
                "lazy": User.get_current(lazyload=True) is None,
                "locked": User.get_current(for_update=True) is None,
            }

        self.issue()
        with patch("bafser.data.user.verify_jwt_in_request") as verify:
            response = self.get("/api/public-current-user")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"uncached": True, "cached": True, "lazy": True, "locked": True})
        verify.assert_not_called()
        self.get_session.assert_not_called()
        self.assertEqual(self.statements, [])
        self.assertEqual(response.headers.getlist("Set-Cookie"), [])

    def test_public_audit_uses_system_implicitly_and_preserves_explicit_actor(self):
        @self.app.get("/api/public-audit")
        @request_policy(RequestPolicy(authenticate=False))
        def public_audit():
            session = self.request_session()
            # A caller may already have an explicit business object. It must
            # not become the implicit actor just because it is cached on g.
            g.user = self.user
            implicit = Log.updated(self.user, changes=[], commit=False, db_sess=session)
            explicit = Log.updated(self.user, self.user, changes=[], commit=False, db_sess=session)
            session.commit()
            return {"implicit": implicit.userId, "implicitName": implicit.userName, "explicit": explicit.userId}

        self.issue()
        with patch("bafser.data.user.verify_jwt_in_request") as verify:
            response = self.get("/api/public-audit")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"implicit": None, "implicitName": "System", "explicit": self.user_id})
        verify.assert_not_called()
        self.get_session.assert_not_called()
        self.assertEqual(response.headers.getlist("Set-Cookie"), [])
        with Session(self.engine) as session:
            logs = session.query(Log).order_by(Log.id).all()
            self.assertEqual([log.userId for log in logs], [None, self.user_id])

    def test_options_with_valid_cookie_does_not_refresh_or_query_db(self):
        self.issue()
        response = self.client.options("/api/poll", base_url="https://localhost")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.access_cookies(response), [])
        self.get_session.assert_not_called()
        self.assertEqual(self.statements, [])


if __name__ == "__main__":
    unittest.main()
