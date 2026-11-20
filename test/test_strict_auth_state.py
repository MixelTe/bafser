"""Strict validation must read stored credentials rather than cached ORM fields."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask
from flask_jwt_extended import JWTManager, decode_token
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from bafser import SqlAlchemyBase
from bafser.authentication import create_access_token, get_user_by_jwt_identity
from test.data.apple import Apple  # noqa: F401
from test.data.img import Img  # noqa: F401
from test.data.user import User


class StrictAuthStateTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.engine = create_engine(f"sqlite:///{Path(directory.name) / 'strict.db'}", pool_size=1, max_overflow=0)
        self.addCleanup(self.engine.dispose)
        self.writer = create_engine(self.engine.url)
        self.addCleanup(self.writer.dispose)
        SqlAlchemyBase.metadata.create_all(self.engine)
        with Session(self.engine, expire_on_commit=False) as session:
            user = User(login="strict-user", name="Stored Name", balance=0)
            user.password = "original-stored-hash"
            session.add(user)
            session.commit()
            self.user_id = user.id
        self.app = Flask(__name__)
        self.app.config["JWT_SECRET_KEY"] = "strict-auth-state-test-key-at-least-32-bytes"
        JWTManager(self.app)
        self.context = self.app.app_context()
        self.context.push()
        self.addCleanup(self.context.pop)
        self.identity = self.identity_for("original-stored-hash")
        self.session = Session(self.engine, expire_on_commit=False)
        self.addCleanup(self.session.close)

    def identity_for(self, password):
        user = SimpleNamespace(id=self.user_id, password=password)
        return decode_token(create_access_token(user))["sub"]

    def replace_password(self):
        with self.writer.begin() as connection:
            connection.execute(User.__table__.update().where(User.id == self.user_id).values(password="changed-stored-hash"))

    def test_external_password_change_is_rejected_despite_cached_user(self):
        cached = self.session.get(User, self.user_id)
        self.replace_password()
        for lazyload in (False, True):
            with self.subTest(lazyload=lazyload):
                self.assertIsNone(get_user_by_jwt_identity(self.session, self.identity, lazyload=lazyload))
        self.assertEqual(cached.password, "original-stored-hash")

    def test_validation_preserves_dirty_fields_and_does_not_flush_or_finish_transaction(self):
        cached = self.session.get(User, self.user_id)
        cached.name = "Unflushed Name"
        cached.password = "unflushed-password"
        transaction = self.session.get_transaction()
        self.assertIs(get_user_by_jwt_identity(self.session, self.identity), cached)
        self.assertEqual(cached.name, "Unflushed Name")
        self.assertEqual(cached.password, "unflushed-password")
        self.assertIn(cached, self.session.dirty)
        self.assertIs(self.session.get_transaction(), transaction)
        with self.writer.connect() as connection:
            self.assertEqual(connection.scalar(select(User.password).where(User.id == self.user_id)), "original-stored-hash")
            self.assertEqual(connection.scalar(select(User.name).where(User.id == self.user_id)), "Stored Name")

    def test_new_valid_stamp_does_not_require_overwriting_cached_orm_fields(self):
        cached = self.session.get(User, self.user_id)
        self.replace_password()
        self.assertIs(get_user_by_jwt_identity(self.session, self.identity_for("changed-stored-hash")), cached)
        self.assertEqual(cached.password, "original-stored-hash")

    def test_dirty_primary_key_cannot_change_authenticated_identity(self):
        cached = self.session.get(User, self.user_id)
        cached.id = self.user_id + 1
        self.assertIsNone(get_user_by_jwt_identity(self.session, self.identity))

    def test_locking_lookup_refreshes_user_and_rejects_revoked_stamp(self):
        cached = self.session.get(User, self.user_id)
        self.replace_password()
        with patch("bafser_config.allow_unsupported_for_update_clause", True):
            self.assertIsNone(get_user_by_jwt_identity(self.session, self.identity, for_update=True))
        self.assertEqual(cached.password, "changed-stored-hash")
