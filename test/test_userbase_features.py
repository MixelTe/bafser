"""User helpers share permission hooks and compose audited role transactions."""

import re
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.orm import Session

from bafser import Log, Role, SqlAlchemyBase, UserRole
from bafser.data.log import Actions
from bafser.data.operation import Operation
from bafser.data.permission import Permission
from test.data.apple import Apple  # noqa: F401
from test.data.img import Img  # noqa: F401
from test.data.user import User


class UserBaseFeatureTests(unittest.TestCase):
    read = ("read", "Read")
    write = ("write", "Write")

    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        directory = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.engine = create_engine("sqlite:///" + (directory / "users.db").as_posix())
        self.stack.callback(self.engine.dispose)

        @event.listens_for(self.engine, "connect")
        def foreign_keys(connection, _record):
            connection.execute("PRAGMA foreign_keys=ON")

        SqlAlchemyBase.metadata.create_all(self.engine)
        self.session = self.stack.enter_context(Session(self.engine, expire_on_commit=False))
        self.actor = User(login="actor", name="Operator", balance=0)
        self.actor.password = "unused"
        target = User(login="target", name="Original", balance=0)
        target.password = "unused"
        roles = []
        for role_id in (1, 2, 3, 4):
            role = Role(name=f"Role {role_id}")
            role.id = role_id
            roles.append(role)
        self.session.add_all([self.actor, target, *roles])
        self.session.flush()
        roles[-1].deleted = True
        self.target_id = target.id
        self.session.add_all([UserRole(userId=target.id, roleId=1), UserRole(userId=target.id, roleId=2)])
        self.session.commit()
        self.session.expire_all()
        self.target = self.session.get(User, self.target_id)
        self.commits = 0

        @event.listens_for(self.session, "after_commit")
        def count_commits(_session):
            self.commits += 1

    def role_ids(self, session):
        return set(session.scalars(select(UserRole.roleId).where(UserRole.userId == self.target_id)))

    def prepare_role_permissions(self):
        self.session.add_all([
            Operation(id="read", name="Read"), Operation(id="write", name="Write"),
            Permission(roleId=1, operationId="read"), Permission(roleId=3, operationId="write"),
        ])
        self.session.commit()
        self.session.expire_all()
        self.target = self.session.get(User, self.target_id)
        self.commits = 0

    def capture_statements(self):
        statements = []

        def collect(_connection, _cursor, statement, _parameters, _context, _executemany):
            statements.append(statement)

        event.listen(self.engine, "before_cursor_execute", collect)
        self.stack.callback(event.remove, self.engine, "before_cursor_execute", collect)
        return statements

    def assert_no_user_updates(self, statements):
        self.assertFalse(any(re.match(r'^\s*UPDATE\s+["`]?User["`]?\s', statement, re.IGNORECASE) for statement in statements))

    def test_bulk_permissions_evaluate_available_operations_once_per_call(self):
        with patch.object(User, "get_operations", return_value=["read", "read"]) as available:
            self.assertTrue(self.target.has_permissions(operation for operation in [self.read, self.read]))
            self.assertEqual(available.call_count, 1)
            available.reset_mock()
            self.assertTrue(self.target.has_any_permissions(iter([self.write, self.read])))
            self.assertEqual(available.call_count, 1)
            available.return_value = ["write"]
            self.assertFalse(self.target.has_permissions([self.read]))
            self.assertTrue(self.target.has_permissions([self.write]))

    def test_empty_permission_and_role_queries_do_not_fetch_memberships(self):
        with patch.object(User, "get_operations", side_effect=AssertionError("unnecessary permission read")):
            self.assertTrue(self.target.has_permissions([]))
            self.assertFalse(self.target.has_any_permissions([]))
        with patch.object(User, "get_roles_ids", side_effect=AssertionError("unnecessary role read")):
            self.assertFalse(self.target.has_any_role([]))

    def test_role_id_helpers_preserve_custom_get_roles_override(self):
        with patch.object(User, "get_roles", return_value=[(7, "Custom"), (9, "Other")]):
            self.assertEqual(self.target.get_roles_ids(), [7, 9])
            self.assertTrue(self.target.has_role(7))
            self.assertTrue(self.target.has_any_role([9]))
            self.assertFalse(self.target.has_any_role([1, 2]))

    def test_bulk_permissions_preserve_custom_single_checker(self):
        def custom_check(_user, operation):
            return operation[0] == "write"

        with (
            patch.object(User, "check_permission", custom_check),
            patch.object(User, "get_operations", side_effect=AssertionError("custom checker was bypassed")),
        ):
            self.assertFalse(self.target.has_permissions([self.read]))
            self.assertTrue(self.target.has_permissions([self.write]))
            self.assertTrue(self.target.has_any_permissions([self.read, self.write]))

    def test_set_roles_deduplicates_audits_diff_and_rolls_back_with_pending_changes(self):
        self.session.autoflush = False
        self.target.name = "Pending name"
        self.target.balance = 42
        with self.session.no_autoflush:
            self.assertTrue(self.target.set_roles(None, (role_id for role_id in [3, 2, 3]), commit=False))
            self.assertEqual(self.target.get_roles_ids(), [2, 3])
            self.assertEqual((self.target.name, self.target.balance), ("Pending name", 42))
            self.assertTrue(self.target.has_any_role([3, 99]))
            self.assertFalse(self.target.has_any_role([1, 99]))
            self.assertEqual(self.commits, 0)
            logs = self.session.query(Log).order_by(Log.id).all()
            self.assertEqual([log.actionCode for log in logs], [Actions.deleted, Actions.added])
            self.assertTrue(all(log.userId is None and log.userName == "System" for log in logs))
            self.assertEqual(logs[0].changes, [["userId", self.target_id, None], ["roleId", 1, None]])
            self.assertEqual(logs[1].changes, [["userId", None, self.target_id], ["roleId", None, 3]])
        self.session.rollback()
        self.assertEqual(self.target.name, "Original")
        self.assertEqual(self.target.balance, 0)
        self.assertEqual(set(self.target.get_roles_ids()), {1, 2})
        self.assertEqual(self.session.query(Log).count(), 0)

    def test_changed_default_call_commits_once_with_actor(self):
        self.assertTrue(self.target.set_roles(self.actor, [3]))
        self.assertEqual(self.commits, 1)
        with Session(self.engine) as other:
            self.assertEqual(self.role_ids(other), {3})
            logs = other.query(Log).all()
            self.assertEqual(len(logs), 3)
            self.assertTrue(all(log.userId == self.actor.id and log.userName == "Operator" for log in logs))

    def test_noop_does_not_commit_pending_work_or_add_audit(self):
        self.actor.name = "Pending operator"
        self.assertFalse(self.target.set_roles(None, [2, 1, 2]))
        self.assertFalse(self.target.add_role(None, 2))
        self.assertFalse(self.target.remove_role(None, 99))
        self.assertEqual(self.commits, 0)
        self.assertEqual(self.session.query(Log).count(), 0)
        with Session(self.engine) as other:
            self.assertEqual(other.get(User, self.actor.id).name, "Operator")
        self.session.rollback()
        self.assertEqual(self.actor.name, "Operator")

    def test_empty_desired_set_removes_all_roles_and_repeated_call_is_noop(self):
        self.assertTrue(self.target.set_roles(None, [], commit=False))
        self.assertEqual(self.target.get_roles_ids(), [])
        self.assertFalse(self.target.set_roles(None, [], commit=False))
        self.assertEqual(self.session.query(Log).count(), 2)
        self.assertEqual(self.commits, 0)

    def test_invalid_ids_are_rejected_without_partial_role_or_audit_changes(self):
        for invalid, exception in (([True], TypeError), ([1.0], TypeError), (["2"], TypeError), ([0], ValueError), ([-1], ValueError)):
            with self.subTest(invalid=invalid), self.assertRaises(exception):
                self.target.set_roles(None, invalid)
        for desired in ([2, 3, 999], [2, 4]):
            with self.subTest(desired=desired), self.assertRaisesRegex(ValueError, "Unknown or deleted"):
                self.target.set_roles(None, desired)
            self.assertEqual(set(self.target.get_roles_ids()), {1, 2})
            self.assertEqual(self.session.query(Log).count(), 0)
        self.assertEqual(self.commits, 0)

    def test_other_session_is_rejected_before_role_changes(self):
        with Session(self.engine) as other, self.assertRaisesRegex(ValueError, "different session"):
            self.target.set_roles(None, [3], db_sess=other)
        self.assertEqual(set(self.target.get_roles_ids()), {1, 2})
        self.assertEqual(self.session.query(Log).count(), 0)

    def test_detached_target_can_join_explicit_transaction(self):
        self.session.expunge_all()
        with Session(self.engine) as other:
            self.assertTrue(self.target.set_roles(None, [3], db_sess=other, commit=False))
            self.assertIs(self.target.get_session(), other)
            self.assertEqual(self.target.get_roles_ids(), [3])
            other.rollback()
        self.assertEqual(self.role_ids(self.session), {1, 2})

    def test_partially_detached_relationship_graph_is_not_moved_between_sessions(self):
        self.session.expunge(self.target)
        with Session(self.engine) as other, self.assertRaises(InvalidRequestError):
            self.target.set_roles(None, [3], db_sess=other)
        self.assertEqual(self.role_ids(self.session), {1, 2})
        self.assertEqual(self.session.query(Log).count(), 0)
        self.assertEqual(self.commits, 0)

    def test_new_target_is_flushed_before_parent_lock(self):
        target = User(login="new", name="New", balance=0)
        target.password = "unused"
        self.assertTrue(target.set_roles(None, [3], db_sess=self.session, commit=False))
        self.assertIsNotNone(target.id)
        self.assertEqual(target.get_roles_ids(), [3])
        self.assertEqual(self.commits, 0)
        self.session.rollback()
        self.assertIsNone(self.session.get(User, target.id))

    def test_mutators_refresh_memberships_changed_outside_the_session_cache(self):
        self.assertEqual(set(self.target.get_roles_ids()), {1, 2})
        with self.engine.begin() as connection:
            connection.execute(UserRole.__table__.insert().values(userId=self.target_id, roleId=3))
        self.assertFalse(self.target.add_role(None, 3, commit=False))
        self.assertEqual(set(self.target.get_roles_ids()), {1, 2, 3})
        self.assertTrue(self.target.remove_role(None, 3, commit=False))
        self.assertEqual(set(self.target.get_roles_ids()), {1, 2})
        self.session.rollback()
        self.assertEqual(set(self.target.get_roles_ids()), {1, 2, 3})

    def test_clean_parent_cache_and_permissions_follow_savepoint_rollback_and_outer_continuation(self):
        self.prepare_role_permissions()
        self.assertTrue(self.target.has_permissions([self.read]))
        self.assertFalse(self.target.has_any_permissions([self.write]))
        # Establish a physical outer transaction even with SQLite's legacy
        # transaction mode. The role target itself must remain clean.
        self.actor.name = "Outer change"
        self.session.flush()
        self.assertNotIn(self.target, self.session.dirty)
        transaction = self.session.get_transaction()
        statements = self.capture_statements()
        nested = self.session.begin_nested()
        self.assertTrue(self.target.set_roles(None, [3], commit=False))
        self.assertEqual(self.target.get_roles_ids(), [3])
        self.assertTrue(self.target.has_permissions([self.write]))
        self.assertFalse(self.target.has_any_permissions([self.read]))
        self.assertEqual(self.session.query(Log).count(), 3)
        nested.rollback()
        self.assertIs(self.session.get_transaction(), transaction)
        self.assertTrue(transaction.is_active)
        self.assertEqual(set(self.target.get_roles_ids()), {1, 2})
        self.assertEqual(self.role_ids(self.session), {1, 2})
        self.assertTrue(self.target.has_permissions([self.read]))
        self.assertFalse(self.target.has_any_permissions([self.write]))
        self.assertEqual(self.session.query(Log).count(), 0)
        self.assertEqual(self.actor.name, "Outer change")
        self.assert_no_user_updates(statements)

        self.assertTrue(self.target.add_role(None, 3, commit=False))
        self.session.commit()
        with Session(self.engine) as other:
            self.assertEqual(self.role_ids(other), {1, 2, 3})
            self.assertEqual(other.get(User, self.actor.id).name, "Outer change")
            self.assertEqual(other.query(Log).count(), 1)
        self.assert_no_user_updates(statements)

    def test_nested_commit_is_still_rolled_back_with_outer_transaction(self):
        self.prepare_role_permissions()
        self.actor.name = "Outer change"
        self.session.flush()
        self.assertNotIn(self.target, self.session.dirty)
        transaction = self.session.get_transaction()
        statements = self.capture_statements()
        nested = self.session.begin_nested()
        self.assertTrue(self.target.set_roles(None, [3], commit=False))
        nested.commit()
        self.assertIs(self.session.get_transaction(), transaction)
        self.assertTrue(transaction.is_active)
        self.assertEqual(self.target.get_roles_ids(), [3])
        self.assertTrue(self.target.has_permissions([self.write]))
        with Session(self.engine) as other:
            self.assertEqual(self.role_ids(other), {1, 2})
            self.assertEqual(other.query(Log).count(), 0)
        self.session.rollback()
        self.assertEqual(set(self.target.get_roles_ids()), {1, 2})
        self.assertEqual(self.role_ids(self.session), {1, 2})
        self.assertTrue(self.target.has_permissions([self.read]))
        self.assertFalse(self.target.has_any_permissions([self.write]))
        self.assertEqual(self.actor.name, "Operator")
        self.assertEqual(self.session.query(Log).count(), 0)
        self.assert_no_user_updates(statements)

    def assert_composed_cache_rollback(self, *, audit_membership: bool, invalid: bool):
        self.assertEqual(set(self.target.get_roles_ids()), {1, 2})
        self.assertTrue(self.target.has_permissions([self.read]))
        self.assertFalse(self.target.has_any_permissions([self.write]))
        self.actor.name = "Outer change"
        self.session.flush()
        self.assertNotIn(self.target, self.session.dirty)
        transaction = self.session.get_transaction()
        statements = self.capture_statements()
        nested = self.session.begin_nested()
        if audit_membership:
            locked_id = self.session.scalar(
                select(User.id).where(User.id == self.target_id).with_for_update(), execution_options={"autoflush": False},
            )
            self.assertEqual(locked_id, self.target_id)
            UserRole.new(None, self.target_id, 3, db_sess=self.session, commit=False)
        else:
            self.session.add(UserRole(userId=self.target_id, roleId=3))
        self.assertNotIn(self.target, self.session.dirty)
        with self.session.no_autoflush:
            self.assertEqual(set(self.target.get_roles_ids()), {1, 2})
        if invalid:
            with self.assertRaisesRegex(ValueError, "Unknown or deleted"):
                self.target.set_roles(None, [2, 999], commit=False)
        else:
            self.assertFalse(self.target.set_roles(None, [1, 2, 3], commit=False))
        self.assertEqual(set(self.target.get_roles_ids()), {1, 2, 3})
        self.assertEqual(self.role_ids(self.session), {1, 2, 3})
        self.assertTrue(self.target.has_permissions([self.write]))
        self.assertEqual(self.session.query(Log).count(), int(audit_membership))
        self.assertEqual(self.commits, 0)
        nested.rollback()
        self.assertIs(self.session.get_transaction(), transaction)
        self.assertTrue(transaction.is_active)
        self.assertEqual(set(self.target.get_roles_ids()), {1, 2})
        self.assertEqual(self.role_ids(self.session), {1, 2})
        self.assertTrue(self.target.has_permissions([self.read]))
        self.assertFalse(self.target.has_any_permissions([self.write]))
        self.assertEqual(self.session.query(Log).count(), 0)
        self.assertEqual(self.actor.name, "Outer change")
        self.assert_no_user_updates(statements)

        self.assertTrue(self.target.add_role(None, 3, commit=False))
        self.assertEqual(set(self.target.get_roles_ids()), {1, 2, 3})
        self.assertTrue(self.target.has_permissions([self.read, self.write]))
        self.assertEqual(self.session.query(Log).count(), 1)
        self.assertEqual(self.commits, 0)
        self.session.rollback()
        self.assertEqual(set(self.target.get_roles_ids()), {1, 2})
        self.assertEqual(self.role_ids(self.session), {1, 2})
        self.assertFalse(self.target.has_any_permissions([self.write]))
        self.assertEqual(self.session.query(Log).count(), 0)
        self.assert_no_user_updates(statements)

    def test_noop_cache_follows_savepoint_rollback_of_pending_membership(self):
        self.prepare_role_permissions()
        for audit_membership in (False, True):
            with self.subTest(audit_membership=audit_membership):
                self.assert_composed_cache_rollback(audit_membership=audit_membership, invalid=False)

    def test_validation_error_cache_follows_savepoint_rollback_of_pending_membership(self):
        self.prepare_role_permissions()
        for audit_membership in (False, True):
            with self.subTest(audit_membership=audit_membership):
                self.assert_composed_cache_rollback(audit_membership=audit_membership, invalid=True)
