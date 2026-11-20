"""Renewal must bypass an established MySQL REPEATABLE READ snapshot."""

import os
import unittest
import uuid

from flask import Flask
from flask_jwt_extended import JWTManager, decode_token
from sqlalchemy import create_engine, delete, event, select
from sqlalchemy.orm import Session

from bafser import SqlAlchemyBase
from bafser.authentication import create_access_token, get_user_by_jwt_identity, renew_access_token
from test.data.apple import Apple  # noqa: F401
from test.data.img import Img  # noqa: F401
from test.data.user import User


@unittest.skipUnless(os.environ.get("BAFSER_TEST_MYSQL_URL"), "BAFSER_TEST_MYSQL_URL is not configured")
class MySQLAuthRefreshTests(unittest.TestCase):
    def setUp(self):
        options = {"isolation_level": "REPEATABLE READ", "pool_size": 1, "max_overflow": 0, "pool_timeout": 0.2, "hide_parameters": True}
        self.engine = create_engine(os.environ["BAFSER_TEST_MYSQL_URL"], **options)
        self.addCleanup(self.engine.dispose)
        self.writer_engine = create_engine(os.environ["BAFSER_TEST_MYSQL_URL"], **options)
        self.addCleanup(self.writer_engine.dispose)
        SqlAlchemyBase.metadata.create_all(self.engine)
        with Session(self.engine, expire_on_commit=False) as session:
            self.user = User(login=f"refresh-{uuid.uuid4().hex}", name="Refresh user", balance=0)
            self.user.password = "original-stored-hash"
            session.add(self.user)
            session.commit()
        self.addCleanup(self.remove_user)
        self.app = Flask(__name__)
        self.app.config.update(JWT_SECRET_KEY="mysql-refresh-test-secret-with-at-least-32-bytes")
        JWTManager(self.app)
        with self.app.app_context():
            self.identity = decode_token(create_access_token(self.user))["sub"]

    def remove_user(self):
        with self.engine.begin() as connection:
            connection.execute(delete(User).where(User.id == self.user.id))

    def test_renewal_reads_external_password_change_after_snapshot_with_one_pooled_connection(self):
        statements = []
        event.listen(
            self.engine, "before_cursor_execute", lambda connection, cursor, statement, parameters, context, executemany: statements.append(statement)
        )
        with Session(self.engine) as reader:
            cached = reader.get(User, self.user.id)
            transaction = reader.get_transaction()
            connection = reader.connection()
            self.assertEqual(cached.password, "original-stored-hash")
            with self.writer_engine.begin() as writer:
                writer.execute(User.__table__.update().where(User.id == self.user.id).values(password="externally-replaced-hash"))
            # Prove that an ordinary scalar read still sees the old snapshot;
            # bypassing only the identity map would not fix renewal here.
            self.assertEqual(reader.scalar(select(User.password).where(User.id == self.user.id)), "original-stored-hash")
            with self.app.app_context():
                self.assertIsNone(renew_access_token(reader, self.identity))
            self.assertIn("FOR UPDATE", statements[-1])
            self.assertEqual(cached.password, "original-stored-hash")
            self.assertIs(reader.get_transaction(), transaction)
            self.assertIs(reader.connection(), connection)
            self.assertEqual(self.engine.pool.checkedout(), 1)

    def test_strict_lookup_respects_snapshot_and_explicit_locking_current_read(self):
        with Session(self.engine) as reader:
            cached = reader.get(User, self.user.id)
            with self.writer_engine.begin() as writer:
                writer.execute(User.__table__.update().where(User.id == self.user.id).values(password="externally-replaced-hash"))
            with self.app.app_context():
                # Ordinary validation uses stored scalar values from the caller's
                # transaction snapshot. Locking is an explicit stronger choice.
                self.assertIs(get_user_by_jwt_identity(reader, self.identity), cached)
                self.assertIsNone(get_user_by_jwt_identity(reader, self.identity, for_update=True))
            self.assertEqual(cached.password, "externally-replaced-hash")
            self.assertEqual(self.engine.pool.checkedout(), 1)


if __name__ == "__main__":
    unittest.main()
