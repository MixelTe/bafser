from contextlib import ExitStack
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from bafser import Log, Role, SqlAlchemyBase, UserRole
from bafser.data.log import Actions
from bafser.data.operation import Operation
from bafser.data.permission import Permission
from test.data.apple import Apple  # noqa: F401
from test.data.img import Img  # noqa: F401
from test.data.user import User


class RoleSyncTransactionTests(unittest.TestCase):
    read = ("read", "Read")
    write = ("write", "Write")

    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.engine = create_engine("sqlite:///" + (root / "roles.db").as_posix())
        self.stack.callback(self.engine.dispose)

        @event.listens_for(self.engine, "connect")
        def foreign_keys(connection, record):
            connection.execute("PRAGMA foreign_keys=ON")

        SqlAlchemyBase.metadata.create_all(self.engine)
        self.session = self.stack.enter_context(Session(self.engine, expire_on_commit=False))
        actor = User(login="operator", name="Operator", balance=0)
        actor.password = "unused"
        admin_role = Role(name="Admin")
        admin_role.id = 1
        user_role = Role(name="User")
        user_role.id = 2
        self.session.add_all([actor, admin_role, user_role])
        self.session.flush()
        self.session.add(UserRole(userId=actor.id, roleId=2))
        self.session.commit()
        self.session.expunge_all()
        self.actor = self.session.query(User).one()
        self.role = self.actor.roles[0].role
        self.assertEqual(self.role.permissions, [])

        self.operations = [self.read, self.write]
        self.roles = {2: {"name": "User", "operations": []}}
        self.stack.enter_context(patch("bafser.data.role.get_operations", return_value=SimpleNamespace(get_all=lambda: self.operations)))
        self.stack.enter_context(patch("bafser.data.role.get_roles", return_value=SimpleNamespace(ROLES=self.roles)))
        self.commits = 0

        @event.listens_for(self.session, "after_commit")
        def count_commits(session):
            self.commits += 1

    def test_add_and_repeat_are_immediately_visible_and_can_be_rolled_back(self):
        self.roles[2] = {"name": "Renamed", "operations": [self.read]}
        self.roles[3] = {"name": "New role", "operations": [self.write]}

        for _ in range(3):
            Role.update_roles_permissions(self.session, commit=False)
            self.assertTrue(self.actor.check_permission(self.read))
            self.assertFalse(self.actor.check_permission(self.write))
            self.assertEqual([permission.operationId for permission in self.role.permissions], ["read"])
            self.assertEqual(self.session.query(Permission).count(), 4)
            self.assertEqual(self.session.query(Role).count(), 3)
            self.assertEqual(self.session.query(Operation).count(), 2)
            self.assertEqual(self.session.query(Log).count(), 2)
            self.assertEqual(self.commits, 0)

        logs = self.session.query(Log).all()
        self.assertTrue(all(log.userId is None and log.userName == "System" for log in logs))
        self.session.rollback()
        self.assertFalse(self.actor.check_permission(self.read))
        self.assertEqual(self.role.name, "User")
        self.assertIsNone(self.session.get(Role, 3))
        self.assertEqual(self.session.query(Operation).count(), 0)
        self.assertEqual(self.session.query(Permission).count(), 0)
        self.assertEqual(self.session.query(Log).count(), 0)
        self.assertEqual(self.commits, 0)

    def test_remove_and_repeat_are_immediately_visible_and_can_be_rolled_back(self):
        self.roles[2]["operations"] = [self.read]
        Role.update_roles_permissions(self.session)
        self.assertTrue(self.actor.check_permission(self.read))
        self.commits = 0

        self.roles[2]["operations"] = []
        for _ in range(3):
            Role.update_roles_permissions(self.session, commit=False)
            self.assertFalse(self.actor.check_permission(self.read))
            self.assertEqual(self.role.permissions, [])
            self.assertIsNone(self.session.get(Permission, (2, "read")))
            self.assertEqual(self.commits, 0)

        self.session.rollback()
        self.assertTrue(self.actor.check_permission(self.read))
        self.assertIsNotNone(self.session.get(Permission, (2, "read")))
        self.assertEqual(self.commits, 0)

    def test_default_commits_once_and_refreshes_permissions_without_commit_expiration(self):
        self.roles[2] = {"name": "Renamed", "operations": [self.read]}
        Role.update_roles_permissions(self.session)
        self.assertEqual(self.commits, 1)
        self.assertTrue(self.actor.check_permission(self.read))

        self.roles[2]["operations"] = []
        Role.update_roles_permissions(self.session)
        self.assertEqual(self.commits, 2)
        self.assertFalse(self.actor.check_permission(self.read))
        with Session(self.engine) as other:
            self.assertEqual(other.get(Role, 2).name, "Renamed")
            self.assertIsNone(other.get(Permission, (2, "read")))
            log = other.query(Log).one()
            self.assertEqual((log.userId, log.userName), (None, "System"))

    def test_removing_and_restoring_role_refresh_permissions_and_keeps_system_audit(self):
        self.roles[2]["operations"] = [self.read]
        Role.update_roles_permissions(self.session)
        self.assertTrue(self.actor.check_permission(self.read))
        self.commits = 0

        role_description = self.roles.pop(2)
        Role.update_roles_permissions(self.session, commit=False)
        self.assertTrue(self.role.deleted)
        self.assertFalse(self.actor.check_permission(self.read))
        self.assertEqual(self.role.permissions, [])

        self.roles[2] = role_description
        Role.update_roles_permissions(self.session, commit=False)
        self.assertFalse(self.role.deleted)
        self.assertTrue(self.actor.check_permission(self.read))
        logs = self.session.query(Log).order_by(Log.id).all()
        self.assertEqual([log.actionCode for log in logs], [Actions.deleted, Actions.restored])
        self.assertTrue(all(log.userId is None and log.userName == "System" for log in logs))
        self.assertEqual(self.commits, 0)
        self.session.rollback()
        self.assertFalse(self.role.deleted)
        self.assertTrue(self.actor.check_permission(self.read))
        self.assertEqual(self.session.query(Log).count(), 0)

    def test_removed_operation_is_deleted_after_permissions_and_can_be_rolled_back(self):
        self.roles[2]["operations"] = [self.read]
        Role.update_roles_permissions(self.session)
        self.assertTrue(self.actor.check_permission(self.read))
        self.commits = 0

        self.operations = [self.write]
        self.roles[2]["operations"] = []
        for _ in range(3):
            Role.update_roles_permissions(self.session, commit=False)
            self.assertFalse(self.actor.check_permission(self.read))
            self.assertIsNone(self.session.get(Operation, "read"))
            self.assertEqual(self.session.query(Permission).count(), 1)
            self.assertEqual(self.commits, 0)

        self.session.rollback()
        self.assertTrue(self.actor.check_permission(self.read))
        self.assertIsNotNone(self.session.get(Operation, "read"))

    def test_sync_composes_with_pending_objects_and_disabled_autoflush(self):
        for session_autoflush in (True, False):
            with self.subTest(session_autoflush=session_autoflush):
                self.session.autoflush = session_autoflush
                self.roles[2]["operations"] = [self.read]
                self.roles[3] = {"name": "Pending role", "operations": [self.read]}
                pending_role = Role(name="Pending role")
                pending_role.id = 3
                self.session.add_all([
                    Operation(id="read", name="Read"),
                    pending_role,
                    Permission(roleId=2, operationId="read"),
                    Permission(roleId=3, operationId="read"),
                ])

                with self.session.no_autoflush:
                    for _ in range(3):
                        Role.update_roles_permissions(self.session, commit=False)
                        self.assertTrue(self.actor.check_permission(self.read))
                        self.assertEqual([permission.operationId for permission in pending_role.permissions], ["read"])
                        self.assertEqual(self.session.query(Role).count(), 3)
                        self.assertEqual(self.session.query(Operation).count(), 2)
                        self.assertEqual(self.session.query(Permission).count(), 4)
                        self.assertEqual(list(self.session.new), [])
                        self.assertEqual(self.commits, 0)

                self.session.rollback()
                self.assertFalse(self.actor.check_permission(self.read))
                self.assertIsNone(self.session.get(Role, 3))
                self.assertEqual(self.session.query(Operation).count(), 0)
                self.assertEqual(self.session.query(Permission).count(), 0)
                self.assertEqual(self.session.query(Log).count(), 0)
