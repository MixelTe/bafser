import base64
from contextlib import ExitStack
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from flask import Flask, current_app
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from bafser import ImageError, Log, PublicError, SqlAlchemyBase, track_created_file
from test.data.apple import Apple  # noqa: F401
from test.data.img import Img
from test.data.user import User


class ImageTransactionsTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.engine = create_engine("sqlite:///:memory:")
        self.stack.callback(self.engine.dispose)
        SqlAlchemyBase.metadata.create_all(self.engine)
        app = Flask(__name__)
        app.config.update(IMAGES_FOLDER=str(self.root), MAX_IMAGE_BYTES=1024)
        self.stack.enter_context(app.app_context())
        self.session = self.stack.enter_context(Session(self.engine))
        self.actor = User(login="images", name="Original", balance=0)
        self.actor.password = "unused"
        self.session.add(self.actor)
        self.session.commit()
        self.payload = {"name": "Poster", "desc": "Design", "data": "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\npayload").decode()}

    def test_caller_rollback_removes_file_row_and_audit_without_committing_other_changes(self):
        self.actor.name = "Uncommitted"
        image = Img.new(self.actor, self.payload, commit=False)
        path = Path(image.get_path())
        self.assertTrue(path.is_file())
        self.session.rollback()
        self.assertFalse(path.exists())
        self.assertEqual(self.actor.name, "Original")
        self.assertEqual(self.session.query(Img).count(), 0)
        self.assertEqual(self.session.query(Log).count(), 0)

    def test_caller_commit_keeps_the_file_and_audit(self):
        image = Img.new(self.actor, self.payload, commit=False)
        path = Path(image.get_path())
        self.session.commit()
        self.session.rollback()  # A later transaction must not remove the committed file.
        self.assertTrue(path.is_file())
        self.assertEqual(self.session.query(Img).count(), 1)
        self.assertEqual(self.session.query(Log).count(), 1)

    def test_image_download_defaults_to_no_store_and_allows_explicit_caching(self):
        image = Img.new(self.actor, self.payload)
        with current_app.test_request_context():
            response = image.create_file_response()
            self.addCleanup(response.close)
            self.assertTrue(response.cache_control.private)
            self.assertTrue(response.cache_control.no_store)
            self.assertEqual(b"".join(response.response), b"\x89PNG\r\n\x1a\npayload")
            for policy in ("private, max-age=3600", "public, max-age=3600"):
                with self.subTest(policy=policy):
                    response = image.create_file_response(cache_control=policy)
                    self.addCleanup(response.close)
                    self.assertEqual(response.headers["Cache-Control"], policy)

    def test_explicit_session_owns_image_and_audit_with_detached_creator(self):
        actor_id = self.actor.id
        actor_name = self.actor.name
        self.session.expunge(self.actor)
        with Session(self.engine) as other:
            image = Img.new(self.actor, self.payload, db_sess=other, commit=False)
            path = Path(image.get_path())
            self.assertIs(image.get_session(), other)
            log = other.query(Log).one()
            self.assertEqual((log.userId, log.userName, log.recordId), (actor_id, actor_name, image.id))
            self.assertTrue(path.is_file())
            other.rollback()
            self.assertFalse(path.exists())
            self.assertEqual(other.query(Img).count(), 0)
            self.assertEqual(other.query(Log).count(), 0)

    def test_explicit_session_commit_does_not_commit_creator_session(self):
        actor_id = self.actor.id
        self.actor.name = "Pending in creator session"
        with Session(self.engine) as other:
            image = Img.new(self.actor, self.payload, db_sess=other)
            self.assertTrue(Path(image.get_path()).is_file())
            self.assertEqual(other.query(Img).count(), 1)
            self.assertEqual(other.query(Log).count(), 1)
            self.assertEqual(other.get(User, actor_id).name, "Original")
        self.assertIn(self.actor, self.session.dirty)

    def test_session_close_removes_abandoned_file(self):
        image = Img.new(self.actor, self.payload, commit=False)
        path = Path(image.get_path())
        self.session.close()
        self.assertFalse(path.exists())
        with Session(self.engine) as other:
            self.assertEqual(other.query(Img).count(), 0)

    def test_savepoint_rollback_removes_only_its_images(self):
        outer = Img.new(self.actor, self.payload, commit=False)
        outer_path = Path(outer.get_path())
        nested = self.session.begin_nested()
        inner = Img.new(self.actor, self.payload, commit=False)
        inner_path = Path(inner.get_path())
        nested.rollback()
        self.assertFalse(inner_path.exists())
        self.assertTrue(outer_path.exists())
        self.session.commit()
        self.assertTrue(outer_path.exists())
        self.assertEqual(self.session.query(Img).count(), 1)

    def test_savepoint_commit_still_cleans_file_when_outer_transaction_rolls_back(self):
        # Start a physical SQLite transaction before its first SAVEPOINT.
        self.actor.name = "Outer transaction"
        self.session.flush()
        with self.session.begin_nested():
            inner = Img.new(self.actor, self.payload, commit=False)
            path = Path(inner.get_path())
        self.assertTrue(path.exists())
        self.session.rollback()
        self.assertFalse(path.exists())
        self.assertEqual(self.session.query(Img).count(), 0)

    def test_commit_failure_rolls_back_the_file_and_database(self):
        with patch.object(self.session, "commit", side_effect=RuntimeError("injected commit failure")):
            with self.assertRaisesRegex(RuntimeError, "injected"):
                Img.new(self.actor, self.payload)
        self.assertEqual(list(self.root.iterdir()), [])
        self.assertEqual(self.session.query(Img).count(), 0)

    def test_database_commit_failure_before_commit_removes_the_file(self):
        with patch.object(self.engine.dialect, "do_commit", side_effect=OSError("commit rejected")):
            with self.assertRaisesRegex(OSError, "commit rejected"):
                Img.new(self.actor, self.payload)
        self.assertEqual(list(self.root.iterdir()), [])
        with Session(self.engine) as other:
            self.assertEqual(other.query(Img).count(), 0)

    def test_lost_commit_acknowledgment_keeps_the_committed_file(self):
        physical_commit = self.engine.dialect.do_commit

        def commit_then_fail(connection):
            physical_commit(connection)
            raise OSError("lost commit acknowledgment")

        actor_id = self.actor.id
        for caller_commits in (False, True):
            with self.subTest(caller_commits=caller_commits):
                if caller_commits:
                    Img.new(self.actor, self.payload, commit=False)
                with patch.object(self.engine.dialect, "do_commit", commit_then_fail):
                    with self.assertRaisesRegex(OSError, "lost commit acknowledgment"):
                        if caller_commits:
                            self.session.commit()
                        else:
                            Img.new(self.actor, self.payload)
                    self.session.rollback()
                self.session.close()
                with Session(self.engine) as other:
                    images = other.query(Img).all()
                    self.assertEqual(len(images), 2 if caller_commits else 1)
                    self.assertEqual(other.query(Log).count(), len(images))
                    for image in images:
                        self.assertTrue(Path(image.get_path()).is_file())
                self.actor = self.session.get(User, actor_id)

    def test_unavailable_outcome_probe_retains_file_and_logs_for_reconciliation(self):
        image = Img.new(self.actor, self.payload, commit=False)
        path = Path(image.get_path())
        with patch.object(self.engine.dialect, "do_commit", side_effect=OSError("commit rejected")):
            with self.assertRaisesRegex(OSError, "commit rejected"):
                self.session.commit()
        with patch.object(self.engine, "connect", side_effect=OSError("database unavailable")):
            with self.assertLogs(level="ERROR") as logs:
                self.session.rollback()
        self.assertTrue(path.is_file())
        self.assertTrue(any("retaining file" in line and str(path) in line for line in logs.output))
        with Session(self.engine) as other:
            self.assertEqual(other.query(Img).count(), 0)

    def test_flush_failure_after_file_creation_removes_file_after_rollback(self):
        image = Img.new(self.actor, self.payload, commit=False)
        path = Path(image.get_path())
        image.name = None
        with self.assertRaises(IntegrityError):
            self.session.commit()
        self.session.rollback()
        self.assertFalse(path.exists())
        with Session(self.engine) as other:
            self.assertEqual(other.query(Img).count(), 0)

    def test_failed_savepoint_release_defers_outcome_until_outer_transaction_ends(self):
        self.actor.name = "Outer transaction"
        self.session.flush()
        nested = self.session.begin_nested()
        image = Img.new(self.actor, self.payload, commit=False)
        path = Path(image.get_path())
        physical_release = self.engine.dialect.do_release_savepoint

        def release_then_fail(connection, name):
            physical_release(connection, name)
            raise OSError("lost savepoint acknowledgment")

        with patch.object(self.engine.dialect, "do_release_savepoint", release_then_fail):
            with self.assertRaisesRegex(OSError, "lost savepoint acknowledgment"):
                nested.commit()
        # The row is still an uncommitted outer write: do not probe or delete it.
        with patch.object(self.engine, "connect", side_effect=AssertionError("premature outcome probe")):
            nested.close()
        self.assertTrue(path.exists())
        self.session.rollback()
        self.assertFalse(path.exists())
        with Session(self.engine) as other:
            self.assertEqual(other.query(Img).count(), 0)

    def test_after_commit_callback_failure_keeps_committed_file_and_original_error(self):
        def failed_callback(_session):
            raise RuntimeError("injected after_commit failure")

        event.listen(Session, "after_commit", failed_callback, insert=True)
        try:
            with self.assertLogs(level="ERROR"):
                with self.assertRaisesRegex(RuntimeError, "injected after_commit failure"):
                    Img.new(self.actor, self.payload)
        finally:
            event.remove(Session, "after_commit", failed_callback)
        self.session.close()
        with Session(self.engine) as other:
            image = other.query(Img).one()
            self.assertTrue(Path(image.get_path()).is_file())

    def test_failed_savepoint_release_keeps_file_after_successful_outer_commit(self):
        self.actor.name = "Outer transaction"
        self.session.flush()
        nested = self.session.begin_nested()
        image = Img.new(self.actor, self.payload, commit=False)
        path = Path(image.get_path())
        physical_release = self.engine.dialect.do_release_savepoint

        def release_then_fail(connection, name):
            physical_release(connection, name)
            raise OSError("lost savepoint acknowledgment")

        with patch.object(self.engine.dialect, "do_release_savepoint", release_then_fail):
            with self.assertRaisesRegex(OSError, "lost savepoint acknowledgment"):
                nested.commit()
        nested.close()
        self.session.commit()
        self.assertTrue(path.is_file())
        with Session(self.engine) as other:
            self.assertEqual(other.query(Img).count(), 1)

    def test_tracking_another_orm_model_has_the_same_rollback_lifecycle(self):
        user = User(login="file-owner", name="Temporary", balance=0)
        user.password = "unused"
        self.session.add(user)
        self.session.flush()
        path = self.root / "owned.bin"
        with path.open("xb") as file:
            track_created_file(user, str(path))
            file.write(b"not an image")
        self.session.rollback()
        self.assertFalse(path.exists())
        self.assertIsNone(self.session.query(User).filter_by(login="file-owner").first())

    def test_write_failure_removes_the_partial_file(self):
        real_open = open

        class BrokenFile:
            def __init__(self, *args):
                self.file = real_open(*args)

            def __enter__(self):
                return self

            def write(self, data):
                self.file.write(data[:3])
                raise OSError("injected write failure")

            def __exit__(self, *_args):
                self.file.close()

        with patch("bafser.data.image.open", BrokenFile, create=True):
            with self.assertRaisesRegex(OSError, "injected"):
                Img.new(self.actor, self.payload, commit=False)
        self.assertEqual(list(self.root.iterdir()), [])
        self.assertEqual(self.session.query(Img).count(), 0)

    def test_existing_file_is_never_overwritten_or_removed(self):
        path = self.root / "1.png"
        path.write_bytes(b"existing image")
        with self.assertRaises(FileExistsError):
            Img.new(self.actor, self.payload)
        self.assertEqual(path.read_bytes(), b"existing image")
        self.assertEqual(self.session.query(Img).count(), 0)

    def test_validation_errors_are_public_and_create_no_files(self):
        invalid_payloads = [
            {**self.payload, "name": ""},
            {**self.payload, "name": "x" * 129},
            {**self.payload, "name": "bad\x00name"},
            *({key: value for key, value in self.payload.items() if key != field} for field in ("data", "name", "desc")),
            *({**self.payload, "data": data} for data in (
                "invalid",
                "data:image/png,AAAA",
                "data:image/png;raw,AAAA",
                "image/png;base64,AAAA",
                "data:image/bmp;base64,AAAA",
                "data:image/png;base64,!!!!",
                "data:image/png;base64,AAAA",
                "data:image/png;base64," + "A" * 2000,
                "data:image/png;base64," + base64.b64encode(b"x" * 1025).decode(),
            )),
        ]
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(ImageError) as caught:
                    Img.new(self.actor, payload, commit=False)
                self.assertIsInstance(caught.exception, PublicError)
                self.assertEqual(caught.exception.status, 400)
                self.assertEqual(caught.exception.get_dict(), {"msg": str(caught.exception), "code": "invalid_image"})
                self.assertEqual(self.session.query(Img).count(), 0)
                self.assertEqual(self.session.query(Log).count(), 0)
                self.assertEqual(list(self.root.iterdir()), [])
