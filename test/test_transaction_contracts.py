from contextlib import ExitStack
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from flask import Flask
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from bafser import Log, Role, SqlAlchemyBase, UserBase, UserRole
from bafser.data.db_state import DBState
from bafser.data.operation import Operation
from test.data.apple import Apple
from test.data.img import Img  # noqa: F401
from test.data.user import User


class TransactionContractTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.engine = create_engine("sqlite:///" + (root / "transactions.db").as_posix())
        self.stack.callback(self.engine.dispose)

        @event.listens_for(self.engine, "connect")
        def foreign_keys(connection, record):
            connection.execute("PRAGMA foreign_keys=ON")

        SqlAlchemyBase.metadata.create_all(self.engine)
        self.session = self.stack.enter_context(Session(self.engine))
        self.actor = User(login="operator", name="Original", balance=0)
        self.actor.password = "original-hash"
        admin_role = Role(name="Admin")
        admin_role.id = 1
        user_role = Role(name="User")
        user_role.id = 2
        self.session.add_all([self.actor, admin_role, user_role])
        self.session.flush()
        self.session.add(UserRole(userId=self.actor.id, roleId=1))
        self.session.commit()
        self.commits = 0

        @event.listens_for(self.session, "after_commit")
        def count_commits(session):
            self.commits += 1

        # These cases test transaction ownership, not the password hash algorithm.
        self.stack.enter_context(patch("bafser.data.user.generate_password_hash", side_effect=lambda value: "hash:" + value))

    def new_user(self, *, commit=True, roles=None):
        return User.new(self.actor, "new-user", "password", "New", roles if roles is not None else [1], 0, db_sess=self.session, commit=commit)

    def test_db_state_composes_without_autoflush_or_hidden_flush(self):
        for disable_autoflush in (False, True):
            with self.subTest(session_autoflush=not disable_autoflush):
                self.session.autoflush = not disable_autoflush
                self.actor.name = "Pending unrelated change"
                with self.session.no_autoflush:
                    self.assertFalse(DBState.is_initialized(self.session, commit=False))
                    state = DBState.get(db_sess=self.session, commit=False)
                    DBState.mark_as_initialized(self.session, commit=False)
                    self.assertIs(DBState.get(db_sess=self.session, commit=False), state)
                    self.assertEqual([item for item in self.session.new if isinstance(item, DBState)], [state])
                    self.assertTrue(state.initialized)
                    self.assertIn(self.actor, self.session.dirty)
                    self.assertEqual(self.commits, 0)
                self.session.rollback()
                self.assertIsNone(self.session.get(DBState, 1))
                self.assertEqual(self.actor.name, "Original")

        self.session.autoflush = False
        self.assertFalse(DBState.is_initialized(self.session, commit=False))
        DBState.mark_as_initialized(self.session, commit=False)
        self.session.commit()
        self.assertEqual(self.session.query(DBState).count(), 1)
        self.assertTrue(DBState.is_initialized(self.session, commit=False))
        self.assertEqual(self.commits, 1)

    def test_user_creation_and_roles_can_be_rolled_back_with_audit(self):
        user = self.new_user(commit=False)
        self.assertIsNotNone(user.id)
        self.assertIsNotNone(UserRole.get(self.session, user.id, 1))
        self.assertGreater(self.session.query(Log).count(), 0)
        self.assertEqual(self.commits, 0)
        self.session.rollback()
        self.assertIsNone(User.get_by_login("new-user", db_sess=self.session))
        self.assertEqual(self.session.query(Log).count(), 0)

    def test_default_user_creation_commits_once_including_roles_and_audit(self):
        user = self.new_user()
        self.assertEqual(self.commits, 1)
        self.assertIsNotNone(UserRole.get(self.session, user.id, 1))
        self.assertEqual(self.session.query(Log).count(), 2)

    def test_failed_nested_role_assignment_does_not_persist_partial_user(self):
        with self.assertRaises(IntegrityError):
            self.new_user(roles=[999])
        self.session.rollback()
        self.assertEqual(self.commits, 0)
        self.assertIsNone(User.get_by_login("new-user", db_sess=self.session))
        self.assertEqual(self.session.query(Log).count(), 0)

    def test_user_mutations_compose_without_inner_commit_or_stale_role_list(self):
        self.actor.update_name(self.actor, "Pending", commit=False)
        self.actor.update_password(self.actor, "new-password", commit=False)
        self.assertTrue(self.actor.add_role(self.actor, 2, commit=False))
        self.assertEqual(sorted(self.actor.get_roles_ids()), [1, 2])
        self.assertTrue(self.actor.remove_role(self.actor, 2, commit=False))
        self.assertEqual(self.actor.get_roles_ids(), [1])
        self.assertEqual(self.commits, 0)
        self.session.rollback()
        self.assertEqual(self.actor.name, "Original")
        self.assertEqual(self.actor.password, "original-hash")
        self.assertEqual(self.actor.get_roles_ids(), [1])
        self.assertEqual(self.session.query(Log).count(), 0)

    def test_each_default_user_mutation_finishes_with_one_commit(self):
        self.actor.update_name(self.actor, "Renamed")
        self.assertEqual(self.commits, 1)
        self.actor.update_password(self.actor, "new-password")
        self.assertEqual(self.commits, 2)
        self.actor.add_role(self.actor, 2)
        self.assertEqual(self.commits, 3)
        self.actor.remove_role(self.actor, 2)
        self.assertEqual(self.commits, 4)

    def test_role_noop_does_not_commit_other_pending_changes(self):
        self.actor.name = "Pending"
        self.assertFalse(self.actor.add_role(self.actor, 1))
        self.assertFalse(self.actor.remove_role(self.actor, 99))
        self.assertEqual(self.commits, 0)
        self.session.rollback()
        self.assertEqual(self.actor.name, "Original")

    def test_low_level_role_delete_can_be_rolled_back(self):
        role = UserRole.get(self.session, self.actor.id, 1)
        role.delete(self.actor, db_sess=self.session, commit=False)
        self.session.flush()
        self.assertIsNone(UserRole.get(self.session, self.actor.id, 1))
        self.assertEqual(self.commits, 0)
        self.session.rollback()
        self.assertIsNotNone(UserRole.get(self.session, self.actor.id, 1))
        self.assertEqual(self.session.query(Log).count(), 0)

    def test_log_added_with_deferred_flush_commits_record_and_audit_once(self):
        user = User(login="deferred", name="Deferred", balance=0)
        user.password = "unused"
        log = Log.added(user, self.actor, db_sess=self.session, flush=False)
        self.assertEqual(self.commits, 1)
        self.assertGreater(user.id, 0)
        self.assertEqual(log.recordId, user.id)
        self.assertIsNotNone(self.session.get(Log, log.id))

    def test_log_added_can_leave_flushing_and_committing_to_caller(self):
        user = User(login="deferred", name="Deferred", balance=0)
        user.password = "unused"
        log = Log.added(user, self.actor, db_sess=self.session, flush=False, commit=False)
        self.assertIsNone(user.id)
        self.assertEqual(log.recordId, -1)
        self.assertEqual(self.commits, 0)
        self.session.rollback()
        self.assertIsNone(User.get_by_login("deferred", db_sess=self.session))

    def test_default_background_audit_uses_null_system_actor(self):
        log = Log.updated(self.actor, db_sess=self.session, commit=False)
        self.session.flush()
        self.assertIsNone(log.userId)
        self.assertEqual(log.userName, "System")

    def test_omitted_actor_uses_current_user_but_explicit_none_is_system(self):
        app = Flask(__name__)
        with app.test_request_context(), patch.object(UserBase, "get_current", return_value=self.actor) as current:
            default_log = Log.updated(self.actor, db_sess=self.session, commit=False)
            self.assertEqual(default_log.userId, self.actor.id)
            current.reset_mock()
            system_log = Log.updated(self.actor, actor=None, db_sess=self.session, commit=False)
            current.assert_not_called()
            self.assertIsNone(system_log.userId)
            self.assertEqual(system_log.userName, "System")

    def test_real_user_one_remains_distinct_from_system(self):
        self.assertEqual(self.actor.id, 1)
        user_log = Log.updated(self.actor, self.actor, db_sess=self.session, commit=False)
        system_log = Log.updated(self.actor, None, db_sess=self.session, commit=False)
        self.session.commit()
        self.assertEqual((user_log.userId, user_log.userName), (1, "Original"))
        self.assertEqual((system_log.userId, system_log.userName), (None, "System"))

    def test_admin_bootstrap_uses_system_actor_and_can_be_rolled_back(self):
        role = UserRole.get(self.session, self.actor.id, 1)
        self.session.delete(role)
        self.session.flush()
        admin = UserBase._create_admin(self.session, commit=False)
        self.assertEqual(admin.login, "admin")
        self.assertEqual(admin.get_roles_ids(), [1])
        logs = self.session.query(Log).all()
        self.assertEqual(len(logs), 2)
        self.assertTrue(all(log.userId is None and log.userName == "System" for log in logs))
        self.assertEqual(self.commits, 0)
        self.session.rollback()
        self.assertIsNone(User.get_by_login("admin", db_sess=self.session))
        self.assertIsNotNone(UserRole.get(self.session, self.actor.id, 1))

    def test_role_sync_and_initialization_state_share_callers_transaction(self):
        class Operations:
            @staticmethod
            def get_all():
                return [("test-operation", "Test")]

        class Roles:
            ROLES = {2: {"name": "Updated role", "operations": [("test-operation", "Test")]}}

        with patch("bafser.data.role.get_operations", return_value=Operations), patch("bafser.data.role.get_roles", return_value=Roles):
            Role.update_roles_permissions(self.session, commit=False)
        DBState.mark_as_initialized(self.session, commit=False)
        self.assertTrue(DBState.is_initialized(self.session, commit=False))
        self.assertEqual(self.session.get(Role, 2).name, "Updated role")
        self.assertIsNotNone(self.session.get(Operation, "test-operation"))
        self.assertTrue(all(log.userId is None for log in self.session.query(Log).all()))
        self.assertEqual(self.commits, 0)
        self.session.rollback()
        self.assertEqual(self.session.get(Role, 2).name, "User")
        self.assertIsNone(self.session.get(Operation, "test-operation"))
        self.assertEqual(self.session.query(DBState).count(), 0)
        self.assertEqual(self.session.query(Log).count(), 0)

    def test_mark_initialized_with_missing_singleton_commits_once(self):
        DBState.mark_as_initialized(self.session)
        self.assertEqual(self.commits, 1)
        self.assertTrue(DBState.is_initialized(self.session))

    def test_first_singleton_read_can_avoid_commit(self):
        self.assertFalse(DBState.is_initialized(self.session, commit=False))
        self.assertEqual(self.commits, 0)
        self.session.rollback()
        self.assertEqual(self.session.query(DBState).count(), 0)

    def test_write_session_mismatch_is_rejected_before_mutation(self):
        original_name = self.actor.name
        with Session(self.engine) as other:
            with self.assertRaisesRegex(ValueError, "different session"):
                self.actor.update_name(self.actor, "Incorrect", db_sess=other)
            self.assertEqual(self.actor.name, original_name)
            self.assertNotIn(self.actor, self.session.dirty)
            with self.assertRaisesRegex(ValueError, "different session"):
                Log.updated(self.actor, self.actor, db_sess=other)
            self.assertEqual(other.query(Log).count(), 0)
        self.assertEqual(self.commits, 0)

    def test_explicit_session_can_attach_detached_target(self):
        actor_id = self.actor.id
        self.session.expunge_all()
        with Session(self.engine) as other:
            self.actor.update_name(None, "Detached update", db_sess=other, commit=False)
            self.assertIs(self.actor.get_session(), other)
            other.flush()
            self.assertEqual(other.get(User, actor_id).name, "Detached update")
            self.assertIsNone(other.query(Log).one().userId)
            other.rollback()
        self.assertEqual(self.session.get(User, actor_id).name, "Original")
        self.assertEqual(self.session.query(Log).count(), 0)

    def test_creator_from_another_session_is_not_committed(self):
        actor_id = self.actor.id
        self.actor.name = "Pending creator name"
        user = User(login="other-session", name="New", balance=0)
        user.password = "unused"
        with Session(self.engine) as other:
            log = Log.added(user, self.actor, db_sess=other)
            self.assertEqual(log.userId, actor_id)
            self.assertEqual(other.get(User, actor_id).name, "Original")
        self.assertIn(self.actor, self.session.dirty)
        self.assertEqual(self.commits, 0)

    def test_delete_and_restore_hooks_cannot_request_inner_commit(self):
        apple = Apple(name="Apple", ownerId=self.actor.id)
        self.session.add(apple)
        self.session.commit()
        self.commits = 0
        with patch.object(apple, "_on_delete", return_value=True) as on_delete:
            self.assertTrue(apple.delete(self.actor))
        self.assertIs(on_delete.call_args.args[-1], False)
        self.assertEqual(self.commits, 1)
        with patch.object(apple, "_on_restore", return_value=True) as on_restore:
            self.assertTrue(apple.restore(self.actor))
        self.assertIs(on_restore.call_args.args[-1], False)
        self.assertEqual(self.commits, 2)
