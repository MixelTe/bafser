"""Role replacement must serialize writers and bypass old MySQL snapshots."""

import os
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import create_engine, delete, event, select, text
from sqlalchemy.orm import Session

from bafser import Log, Role, SqlAlchemyBase, UserRole
from test.data.apple import Apple  # noqa: F401
from test.data.img import Img  # noqa: F401
from test.data.user import User


@unittest.skipUnless(os.environ.get("BAFSER_TEST_MYSQL_URL"), "BAFSER_TEST_MYSQL_URL is not configured")
class MySQLUserRoleTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            os.environ["BAFSER_TEST_MYSQL_URL"], isolation_level="REPEATABLE READ",
            pool_size=3, max_overflow=0, pool_timeout=1, hide_parameters=True,
        )
        self.addCleanup(self.engine.dispose)
        SqlAlchemyBase.metadata.create_all(self.engine)
        first_role = 1_000_000 + uuid.uuid4().int % 1_000_000_000
        self.role_ids = [first_role + offset for offset in range(3)]
        with Session(self.engine, expire_on_commit=False) as session:
            for role_id in self.role_ids:
                role = Role(name=f"Role {role_id}")
                role.id = role_id
                session.add(role)
            user = User(login=f"roles-{uuid.uuid4().hex}", name="Original", balance=0)
            user.password = "unused"
            session.add(user)
            session.flush()
            self.user_id = user.id
            session.add(UserRole(userId=user.id, roleId=self.role_ids[0]))
            session.commit()
        self.addCleanup(self.remove_owned_rows)

    def remove_owned_rows(self):
        with Session(self.engine) as session:
            owned_logs = [
                log.id for log in session.scalars(select(Log).where(Log.tableName == UserRole.__tablename__))
                if any(field == "userId" and self.user_id in (old, new) for field, old, new in log.changes)
            ]
            if owned_logs:
                session.execute(delete(Log).where(Log.id.in_(owned_logs)))
            session.execute(delete(UserRole).where(UserRole.userId == self.user_id))
            session.execute(delete(User).where(User.id == self.user_id))
            session.execute(delete(Role).where(Role.id.in_(self.role_ids)))
            session.commit()

    def stored_roles(self):
        with self.engine.connect() as connection:
            return set(connection.scalars(select(UserRole.roleId).where(UserRole.userId == self.user_id)))

    def test_parent_lock_serializes_add_and_replacement_with_stale_membership_cache(self):
        attempted = threading.Event()
        completed = threading.Event()
        owner_thread = threading.get_ident()

        def lock_attempt(_connection, _cursor, statement, _parameters, _context, _executemany):
            if threading.get_ident() != owner_thread and "FOR UPDATE" in statement and "User" in statement:
                attempted.set()

        event.listen(self.engine, "before_cursor_execute", lock_attempt)
        self.addCleanup(event.remove, self.engine, "before_cursor_execute", lock_attempt)

        def replace_roles():
            with Session(self.engine, expire_on_commit=False) as session:
                session.execute(text("SET SESSION innodb_lock_wait_timeout=4"))
                user = session.get(User, self.user_id)
                self.assertEqual(user.get_roles_ids(), [self.role_ids[0]])
                changed = user.set_roles(None, [self.role_ids[2]])
                completed.set()
                return changed, user.get_roles_ids()

        with Session(self.engine, expire_on_commit=False) as first, ThreadPoolExecutor(max_workers=1) as pool:
            user = first.get(User, self.user_id)
            user.add_role(None, self.role_ids[1], commit=False)
            future = pool.submit(replace_roles)
            try:
                self.assertTrue(attempted.wait(3), "Second writer never reached the parent lock")
                self.assertFalse(completed.wait(0.15), "Role replacement escaped the parent lock")
                first.commit()
            finally:
                first.rollback()
            self.assertEqual(future.result(timeout=6), (True, [self.role_ids[2]]))
        self.assertEqual(self.stored_roles(), {self.role_ids[2]})

    def test_replacement_uses_current_memberships_and_preserves_pending_user_fields(self):
        initial, externally_added, desired = self.role_ids
        with Session(self.engine, expire_on_commit=False) as reader:
            cached = reader.get(User, self.user_id)
            self.assertEqual(cached.get_roles_ids(), [initial])
            with self.engine.begin() as writer:
                writer.execute(delete(UserRole).where(UserRole.userId == self.user_id))
                writer.execute(UserRole.__table__.insert().values(userId=self.user_id, roleId=externally_added))
            self.assertEqual(set(reader.scalars(select(UserRole.roleId).where(UserRole.userId == self.user_id))), {initial})
            cached.name = "Pending name"
            cached.balance = 42
            reader.autoflush = False
            transaction = reader.get_transaction()
            with reader.no_autoflush:
                self.assertTrue(cached.set_roles(None, [desired], commit=False))
            self.assertEqual(cached.get_roles_ids(), [desired])
            self.assertEqual((cached.name, cached.balance), ("Pending name", 42))
            self.assertIs(reader.get_transaction(), transaction)
            reader.rollback()
            self.assertEqual(cached.get_roles_ids(), [externally_added])
            self.assertEqual((cached.name, cached.balance), ("Original", 0))
        self.assertEqual(self.stored_roles(), {externally_added})

    def test_add_and_remove_recheck_current_memberships_after_snapshot(self):
        initial, added, _desired = self.role_ids
        with Session(self.engine, expire_on_commit=False) as reader:
            cached = reader.get(User, self.user_id)
            self.assertEqual(cached.get_roles_ids(), [initial])
            with self.engine.begin() as writer:
                writer.execute(UserRole.__table__.insert().values(userId=self.user_id, roleId=added))
            self.assertFalse(cached.add_role(None, added, commit=False))
            self.assertEqual(set(cached.get_roles_ids()), {initial, added})
            self.assertTrue(cached.remove_role(None, added, commit=False))
            self.assertEqual(cached.get_roles_ids(), [initial])
            reader.rollback()
        self.assertEqual(self.stored_roles(), {initial, added})
