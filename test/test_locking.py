"""FOR UPDATE tracking; real concurrency tests run when BAFSER_TEST_MYSQL_URL is set."""

import os
import threading
import unittest
from unittest.mock import patch

from sqlalchemy import ForeignKey, MetaData, String, create_engine, event, text, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Mapped, Session, joinedload, mapped_column, relationship, selectinload

import bafser_config
from bafser import BigIdMixin, ForUpdateRequiredError, IdMixin, LockNotSupportedError, ObjMixin, SqlAlchemyBase


class LockBase(SqlAlchemyBase):
    __abstract__ = True
    metadata = MetaData()


class LockItem(LockBase, IdMixin):
    __tablename__ = "bafser_lock_items"
    name: Mapped[str] = mapped_column(String(32))
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("bafser_lock_items.id"), default=None)
    parent: Mapped["LockItem | None"] = relationship(remote_side="LockItem.id", init=False)


class LockObject(LockBase, ObjMixin, BigIdMixin):
    __tablename__ = "bafser_lock_objects"
    name: Mapped[str] = mapped_column(String(32))


class LockBigId(LockBase, BigIdMixin):
    __tablename__ = "bafser_lock_big_ids"
    id: Mapped[int] = mapped_column(primary_key=True, init=False)
    name: Mapped[str] = mapped_column(String(32))


class LockingTests(unittest.TestCase):
    def setUp(self):
        self.config = patch.object(bafser_config, "allow_unsupported_for_update_clause", True, create=True)
        self.config.start()
        self.addCleanup(self.config.stop)
        self.engine = create_engine("sqlite:///:memory:")
        self.addCleanup(self.engine.dispose)
        LockBase.metadata.create_all(self.engine)
        self.session = Session(self.engine, expire_on_commit=False)
        self.addCleanup(self.session.close)
        self.parent = LockItem(name="parent")
        self.session.add(self.parent)
        self.session.flush()
        self.item = LockItem(name="old", parent_id=self.parent.id)
        self.obj = LockObject(name="object")
        self.obj.id_big = "obj"
        self.big = LockBigId(name="big")
        self.big.id_big = "big"
        self.session.add_all([self.item, self.obj, self.big])
        self.session.commit()

    def lock(self):
        return LockItem.get(self.item.id, db_sess=self.session, for_update=True)

    def test_plain_read_requires_lock_even_in_compatibility_mode(self):
        item = LockItem.get(self.item.id, db_sess=self.session)
        self.assertFalse(item.is_for_update)
        with self.assertRaises(ForUpdateRequiredError):
            item.require_for_update()

    def test_query_construction_does_not_mark(self):
        LockItem.query(for_update=True, db_sess=self.session)
        self.assertFalse(self.item.is_for_update)
        self.assertFalse(self.session.in_transaction())

    def test_sqlite_strict_mode_fails_before_sql(self):
        calls = []
        event.listen(self.engine, "before_cursor_execute", lambda *args: calls.append(args))
        with patch.object(bafser_config, "allow_unsupported_for_update_clause", False):
            query = LockItem.query(for_update=True, db_sess=self.session)
            with self.assertRaises(LockNotSupportedError):
                query.first()
        self.assertEqual(calls, [])
        self.assertFalse(self.item.is_for_update)

    def test_missing_config_defaults_to_strict(self):
        del bafser_config.allow_unsupported_for_update_clause
        try:
            with self.assertRaises(LockNotSupportedError):
                self.lock()
        finally:
            bafser_config.allow_unsupported_for_update_clause = True

    def test_first_refreshes_same_instance_and_marks_only_selected_row(self):
        self.session.execute(
            update(LockItem).where(LockItem.id == self.item.id).values(name="fresh"), execution_options={"synchronize_session": False}
        )
        self.assertEqual(self.item.name, "old")
        item = self.lock()
        self.assertIs(item, self.item)
        self.assertEqual(item.name, "fresh")
        item.require_for_update()
        self.assertFalse(self.parent.is_for_update)

    def test_refresh_cannot_be_disabled_by_execution_options(self):
        self.session.execute(
            update(LockItem).where(LockItem.id == self.item.id).values(name="fresh"), execution_options={"synchronize_session": False}
        )
        item = LockItem.query(for_update=True, db_sess=self.session).execution_options(populate_existing=False).filter_by(id=self.item.id).first()
        self.assertEqual(item.name, "fresh")
        self.assertTrue(item.is_for_update)

    def test_count_does_not_mark_instances(self):
        self.assertEqual(LockItem.query(for_update=True, db_sess=self.session).count(), 2)
        self.assertFalse(self.item.is_for_update)

    def test_all_and_iteration_mark_results(self):
        for consume in (lambda query: query.all(), list):
            with self.subTest(consume=consume):
                items = consume(LockItem.query(for_update=True, db_sess=self.session))
                self.assertEqual(len(items), 2)
                self.assertTrue(all(item.is_for_update for item in items))
                self.session.rollback()

    def test_newly_loaded_object_is_marked(self):
        self.session.expunge_all()
        item = self.lock()
        self.assertIsNot(item, self.item)
        self.assertTrue(item.is_for_update)

    def test_obj_and_both_big_id_paths(self):
        obj = LockObject.get(self.obj.id, db_sess=self.session, for_update=True)
        self.assertTrue(obj.is_for_update)
        self.session.rollback()
        obj = LockObject.get_by_big_id("obj", db_sess=self.session, for_update=True)
        self.assertTrue(obj.is_for_update)
        big = LockBigId.get_by_big_id("big", db_sess=self.session, for_update=True)
        self.assertTrue(big.is_for_update)

    def test_deleted_filter_is_preserved(self):
        self.obj.deleted = True
        self.session.commit()
        self.assertIsNone(LockObject.get(self.obj.id, db_sess=self.session, for_update=True))
        self.assertFalse(self.obj.is_for_update)
        obj = LockObject.get(self.obj.id, includeDeleted=True, db_sess=self.session, for_update=True)
        self.assertTrue(obj.is_for_update)

    def test_commit_rollback_and_close_invalidate_marks(self):
        for end in (self.session.commit, self.session.rollback, self.session.close):
            with self.subTest(end=end):
                item = self.lock()
                self.assertTrue(item.is_for_update)
                end()
                self.assertFalse(item.is_for_update)

    def test_new_transaction_does_not_restore_old_mark(self):
        item = self.lock()
        self.session.commit()
        self.session.query(LockItem).first()
        self.assertFalse(item.is_for_update)
        self.lock()
        self.assertTrue(item.is_for_update)

    def test_transaction_change_during_result_loading_does_not_mark(self):
        def change_transaction(item, context, attributes):
            self.session.commit()
            self.session.begin()

        event.listen(LockItem, "refresh", change_transaction, once=True)
        self.addCleanup(event.remove, LockItem, "refresh", change_transaction)
        self.assertIs(self.lock(), self.item)
        self.assertFalse(self.item.is_for_update)

    def test_detach_and_reattach_in_same_or_other_session(self):
        item = self.lock()
        self.session.expunge(item)
        self.assertFalse(item.is_for_update)
        self.session.add(item)
        self.assertFalse(item.is_for_update)
        self.lock()
        self.session.expunge(item)
        with Session(self.engine) as other:
            other.add(item)
            self.assertFalse(item.is_for_update)

    def test_savepoint_commit_preserves_mark(self):
        item = self.lock()
        nested = self.session.begin_nested()
        nested.commit()
        self.assertTrue(item.is_for_update)

    def test_savepoint_rollback_invalidates_all_marks(self):
        item = self.lock()
        nested = self.session.begin_nested()
        parent = LockItem.get(self.parent.id, for_update=True, db_sess=self.session)
        nested.rollback()
        self.assertFalse(item.is_for_update)
        self.assertFalse(parent.is_for_update)
        self.lock()
        self.assertTrue(item.is_for_update)
        self.assertFalse(parent.is_for_update)

    def test_failed_sql_and_missing_rows_do_not_mark(self):
        with self.assertRaises(OperationalError):
            LockItem.query(for_update=True, db_sess=self.session).filter(text("missing_column = 1")).all()
        self.assertFalse(self.item.is_for_update)
        self.session.rollback()
        self.assertIsNone(LockItem.get(-1, for_update=True, db_sess=self.session))
        self.assertFalse(self.item.is_for_update)

    def test_sql_error_invalidates_previous_marks(self):
        for tracked in (True, False):
            with self.subTest(tracked=tracked):
                item = self.lock()
                self.assertTrue(item.is_for_update)
                with self.assertRaises(OperationalError):
                    LockItem.query(for_update=tracked, db_sess=self.session).filter(text("missing_column = 1")).all()
                self.assertFalse(item.is_for_update)
                self.session.rollback()

    def test_self_relationships_are_not_marked(self):
        for loader in (joinedload, selectinload):
            with self.subTest(loader=loader):
                item = LockItem.query(for_update=True, db_sess=self.session).options(loader(LockItem.parent)).filter_by(id=self.item.id).first()
                self.assertTrue(item.is_for_update)
                self.assertFalse(item.parent.is_for_update)
                self.session.rollback()

    def test_scalar_projections_do_not_mark_cached_instances(self):
        values = LockItem.query(for_update=True, db_sess=self.session).with_entities(LockItem.id).all()
        self.assertEqual(len(values), 2)
        self.assertFalse(self.item.is_for_update)
        self.assertFalse(self.parent.is_for_update)

    def test_multi_entity_results_mark_only_helper_model(self):
        result = LockObject.query(for_update=True, db_sess=self.session).add_entity(LockBigId).join(LockBigId, LockBigId.id == LockObject.id).all()
        self.assertEqual(len(result), 1)
        self.assertTrue(result[0][0].is_for_update)
        self.assertFalse(result[0][1].is_for_update)

    def test_shared_lock_override_is_rejected(self):
        with self.assertRaises(ValueError):
            LockItem.query(for_update=True, db_sess=self.session).with_for_update(read=True).first()
        self.assertFalse(self.item.is_for_update)

    def test_raw_for_update_is_not_tracked(self):
        item = self.session.query(LockItem).with_for_update().populate_existing().filter_by(id=self.item.id).first()
        self.assertFalse(item.is_for_update)

    def test_mark_is_read_only_and_not_serialized(self):
        item = self.lock()
        with self.assertRaises(AttributeError):
            item.is_for_update = False
        self.assertNotIn("is_for_update", item.to_dict())
        self.assertFalse(LockItem(name="new").is_for_update)

    def test_autoflush_and_explicit_no_autoflush_keep_sqlalchemy_semantics(self):
        self.item.name = "flushed"
        self.assertEqual(self.lock().name, "flushed")
        self.item.name = "discarded"
        with self.session.no_autoflush:
            self.assertEqual(self.lock().name, "flushed")


@unittest.skipUnless(os.environ.get("BAFSER_TEST_MYSQL_URL"), "BAFSER_TEST_MYSQL_URL is not configured")
class MySQLLockingTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(os.environ["BAFSER_TEST_MYSQL_URL"], isolation_level="REPEATABLE READ")
        self.addCleanup(self.engine.dispose)
        LockBase.metadata.create_all(self.engine)
        with Session(self.engine) as session:
            session.query(LockItem).delete()
            item = LockItem(name="old")
            session.add(item)
            session.commit()
            self.item_id = item.id

    def test_waiting_reader_refreshes_cached_object_after_writer_commit(self):
        with Session(self.engine, expire_on_commit=False) as reader, Session(self.engine) as writer:
            cached = LockItem.get(self.item_id, db_sess=reader)
            locked = LockItem.get(self.item_id, for_update=True, db_sess=writer)
            locked.name = "fresh"
            writer.flush()
            started = threading.Event()
            finished = threading.Event()
            result = []
            errors = []

            @event.listens_for(reader.connection(), "before_cursor_execute")
            def query_started(connection, cursor, statement, parameters, context, executemany):
                if "FOR UPDATE" in statement:
                    started.set()

            def read_locked():
                try:
                    result.append(LockItem.get(self.item_id, for_update=True, db_sess=reader))
                except BaseException as exc:
                    errors.append(exc)
                finally:
                    finished.set()

            thread = threading.Thread(target=read_locked, daemon=True)
            thread.start()
            try:
                self.assertTrue(started.wait(5))
                self.assertFalse(finished.wait(0.3), "Reader did not wait for the row lock")
            finally:
                writer.commit()
                thread.join(10)
            self.assertTrue(finished.is_set())
            self.assertEqual(errors, [])
            self.assertIs(result[0], cached)
            self.assertEqual(cached.name, "fresh")
            self.assertTrue(cached.is_for_update)
            reader.commit()
            self.assertFalse(cached.is_for_update)

    def test_commit_and_rollback_release_real_lock(self):
        for end_name in ("commit", "rollback"):
            with self.subTest(end=end_name), Session(self.engine) as first, Session(self.engine) as second:
                item = LockItem.get(self.item_id, for_update=True, db_sess=first)
                second.execute(text("SET SESSION innodb_lock_wait_timeout = 1"))
                with self.assertRaises(OperationalError) as caught:
                    LockItem.get(self.item_id, for_update=True, db_sess=second)
                self.assertEqual(caught.exception.orig.args[0], 1205)
                second.rollback()
                getattr(first, end_name)()
                self.assertFalse(item.is_for_update)
                self.assertTrue(LockItem.get(self.item_id, for_update=True, db_sess=second).is_for_update)


if __name__ == "__main__":
    unittest.main()
