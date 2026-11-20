"""Token-only validation and current-user checks have deliberately distinct costs."""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token as jwt_create_access_token, decode_token
from sqlalchemy import column

from bafser import UserBase
from bafser.authentication import create_access_token, get_user_by_jwt_identity, get_user_id_by_jwt_identity
from bafser.utils.protected_route import protected_route

_SERVER_SECRET = "test-server-key-for-auth-contracts-only"
_OTHER_SECRET = "another-server-key-for-auth-contracts"


class AuthenticationContractsTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__, static_folder=None)
        self.app.config.update(TESTING=True, JWT_SECRET_KEY=_SERVER_SECRET, JWT_TOKEN_LOCATION=["headers"])
        JWTManager(self.app)
        self.user = SimpleNamespace(id=7, password="stored-hash-to-keep-private", deleted=False)
        self.table = SimpleNamespace(
            id=column("id"), password=column("password"), deleted=column("deleted"),
            get=Mock(return_value=self.user), get_lazy=Mock(return_value=self.user),
        )
        self.session = Mock()
        self.session.no_autoflush = MagicMock()
        self.session.execute.return_value.one_or_none.return_value = self.user

    def issue(self, user=None):
        with self.app.app_context():
            token = create_access_token(self.user if user is None else user)
            return token, decode_token(token)["sub"]

    def test_identity_does_not_disclose_password_hash(self):
        _, identity = self.issue()
        self.assertNotIn(self.user.password, identity)
        self.assertEqual(get_user_id_by_jwt_identity(identity), self.user.id)
        self.assertEqual(len(json.loads(identity)[2]), 64)

    def test_fast_id_has_no_context_or_database_dependency(self):
        _, identity = self.issue()
        with patch("bafser.data.user.get_user_table", side_effect=AssertionError("Unexpected DB lookup")):
            self.assertEqual(get_user_id_by_jwt_identity(identity), 7)

    def test_old_and_invalid_identities_are_rejected_before_querying(self):
        _, identity = self.issue()
        version, _, stamp = json.loads(identity)
        invalid = [None, b"[]", "invalid-json", "{}", json.dumps([7, self.user.password])]
        invalid += [json.dumps([version, value, stamp]) for value in (True, False, 0, -1, "7", None)]
        invalid += [json.dumps([version, 7, value]) for value in ("", "a" * 63, "A" * 64, "z" * 64, 1)]
        invalid += [json.dumps(["unknown-version", 7, stamp])]
        with self.app.app_context(), patch("bafser.data.user.get_user_table") as table_getter:
            for value in invalid:
                with self.subTest(identity=value):
                    self.assertIsNone(get_user_id_by_jwt_identity(value))
                    self.assertIsNone(get_user_by_jwt_identity(self.session, value))
            table_getter.assert_not_called()

    def test_strict_lookup_checks_current_password_and_deletion(self):
        _, identity = self.issue()
        with self.app.app_context(), patch("bafser.data.user.get_user_table", return_value=self.table):
            self.assertIs(get_user_by_jwt_identity(self.session, identity), self.user)
            self.table.get.assert_called_once_with(7, for_update=False, db_sess=self.session)
            self.user.password = "changed-password-hash"
            self.assertIsNone(get_user_by_jwt_identity(self.session, identity))
            _, replacement_identity = self.issue()
            self.assertIs(get_user_by_jwt_identity(self.session, replacement_identity), self.user)
            self.user.deleted = True
            self.assertIsNone(get_user_by_jwt_identity(self.session, replacement_identity))
            self.table.get.return_value = None
            self.assertIsNone(get_user_by_jwt_identity(self.session, replacement_identity))

    def test_strict_lookup_preserves_lazy_and_lock_options(self):
        _, identity = self.issue()
        with self.app.app_context(), patch("bafser.data.user.get_user_table", return_value=self.table):
            self.assertIs(get_user_by_jwt_identity(self.session, identity, lazyload=True, for_update=True), self.user)
        self.table.get_lazy.assert_called_once_with(7, for_update=True, db_sess=self.session)
        self.table.get.assert_not_called()

    def test_stamp_is_bound_to_server_key_and_user_id(self):
        _, identity = self.issue()
        version, _, stamp = json.loads(identity)
        with self.app.app_context(), patch("bafser.data.user.get_user_table", return_value=self.table):
            self.app.config["JWT_SECRET_KEY"] = _OTHER_SECRET
            self.assertIsNone(get_user_by_jwt_identity(self.session, identity))
            self.app.config["JWT_SECRET_KEY"] = _SERVER_SECRET
            self.user.id = 8
            self.assertIsNone(get_user_by_jwt_identity(self.session, json.dumps([version, 8, stamp])))

    def test_creation_requires_a_persisted_non_bool_id(self):
        for value in (None, True, 0, -1):
            with self.subTest(user_id=value), self.app.app_context():
                with self.assertRaises(ValueError):
                    create_access_token(SimpleNamespace(id=value, password="stored-hash"))

    def test_route_modes_preserve_fast_path_and_strict_resolution(self):
        @self.app.get("/fast")
        @protected_route()
        def fast():
            return {"ok": True}

        @self.app.get("/strict")
        @protected_route(check_user=True)
        def strict():
            return {"ok": True}

        token, _ = self.issue()
        headers = {"Authorization": f"Bearer {token}"}
        client = self.app.test_client()
        with patch.object(UserBase, "get_current", side_effect=AssertionError("Unexpected user lookup")):
            self.assertEqual(client.get("/fast", headers=headers).status_code, 200)
        with patch.object(UserBase, "get_current", return_value=None) as getter:
            self.assertEqual(client.get("/strict", headers=headers).status_code, 401)
            getter.assert_called_once()
        with patch.object(UserBase, "get_current", return_value=self.user) as getter:
            self.assertEqual(client.get("/strict", headers=headers).status_code, 200)
            getter.assert_called_once()

    def test_token_only_route_rejects_signed_old_schema_without_db_lookup(self):
        @self.app.get("/fast")
        @protected_route()
        def fast():
            return {"ok": True}

        with self.app.app_context():
            old_token = jwt_create_access_token(identity=json.dumps([7, self.user.password]))
        with patch.object(UserBase, "get_current", side_effect=AssertionError("Unexpected user lookup")):
            response = self.app.test_client().get("/fast", headers={"Authorization": f"Bearer {old_token}"})
        self.assertEqual(response.status_code, 401)

    def test_permission_route_checks_user_even_without_check_user_flag(self):
        @self.app.get("/permitted")
        @protected_route(perms=("manage", "Manage"), perms_any=[("view", "View")])
        def permitted():
            return {"ok": True}

        token, _ = self.issue()
        user = UserBase(name="Permission fixture", login="permission-fixture")
        user.check_permission = Mock(return_value=True)
        with patch.object(UserBase, "get_current", return_value=user) as getter:
            response = self.app.test_client().get("/permitted", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(response.status_code, 200)
        getter.assert_called_once()
        self.assertEqual(user.check_permission.call_count, 2)

    def test_strict_database_failures_are_not_treated_as_anonymous(self):
        @self.app.get("/strict")
        @protected_route(check_user=True)
        def strict():
            return {"ok": True}

        token, _ = self.issue()
        with patch.object(UserBase, "get_current", side_effect=RuntimeError("database failed")):
            with self.assertRaisesRegex(RuntimeError, "database failed"):
                self.app.test_client().get("/strict", headers={"Authorization": f"Bearer {token}"})


if __name__ == "__main__":
    unittest.main()
