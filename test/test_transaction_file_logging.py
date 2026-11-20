"""Full and reduced file diagnostics, including plain host formatters."""

import hashlib
import io
import logging
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from bafser import SqlAlchemyBase, track_created_file
from bafser import logger as logs
from bafser.app import RequestPolicy
from bafser.utils import transaction_files
from test.data.apple import Apple  # noqa: F401 -- register User.apples relationship target
from test.data.img import Img  # noqa: F401 -- register User.avatar relationship target
from test.data.user import User


class TransactionFileLoggingTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "PRIVATE_FILENAME.bin"
        self.engine = create_engine("sqlite:///:memory:")
        self.addCleanup(self.engine.dispose)
        SqlAlchemyBase.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.addCleanup(self.session.close)
        self.owner = User(login="file-owner", name="Private owner", balance=0)
        self.owner.password = "unused"
        self.session.add(self.owner)
        self.session.flush()
        self.owner_id = self.owner.id
        with self.path.open("xb") as file:
            track_created_file(self.owner, str(self.path))
            file.write(b"owned by the transaction")

    @contextmanager
    def capture(self, *, dev=False, details=False, request=False, configured=True):
        plain = io.StringIO()
        policy = io.StringIO()
        plain_handler = logging.StreamHandler(plain)
        plain_handler.setFormatter(logging.Formatter("%(message)s"))
        policy_handler = logging.StreamHandler(policy)
        policy_handler.setFormatter(logs.RequestFormatter("%(message)s"))
        root = logging.getLogger()
        root.addHandler(plain_handler)
        root.addHandler(policy_handler)
        config = SimpleNamespace(DEV_MODE=dev, LOG_ERROR_DETAILS=details, REQUEST_POLICY=RequestPolicy())
        config_context = patch.object(logs, "_get_config", return_value=config) if configured else patch("bafser.app._config", None)
        try:
            with config_context, patch.object(plain_handler, "emit", wraps=plain_handler.emit) as emit:
                captured = SimpleNamespace(plain=plain, policy=policy, emit=emit)
                if request:
                    with Flask(__name__).test_request_context("/private?token=PRIVATE_URL"):
                        yield captured
                else:
                    yield captured
        finally:
            for handler in (plain_handler, policy_handler):
                root.removeHandler(handler)
                handler.close()

    def assert_safe_records(self, captured):
        self.assertTrue(captured.emit.call_args_list)
        for call in captured.emit.call_args_list:
            record = call.args[0]
            self.assertIsNone(record.exc_info)
            self.assertIsNone(record.exc_text)
            self.assertIsNone(record.stack_info)
            for secret in (str(self.path), "PRIVATE_FILENAME", "PRIVATE_PROBE_VALUE", "PRIVATE_DELETE_VALUE", "PRIVATE_ERROR_VALUE"):
                self.assertNotIn(secret, repr(record.__dict__))

    def fail_commit(self):
        with patch.object(self.engine.dialect, "do_commit", side_effect=OSError("PRIVATE_COMMIT_VALUE")):
            with self.assertRaisesRegex(OSError, "PRIVATE_COMMIT_VALUE"):
                self.session.commit()

    def test_unknown_commit_outcome_logs_reproducible_reference_in_production(self):
        self.fail_commit()
        with self.capture(request=True) as output, patch.object(self.engine, "connect", side_effect=OSError("PRIVATE_PROBE_VALUE")):
            self.session.rollback()
        reference = hashlib.sha256(str(self.path).encode("utf8", errors="surrogatepass")).hexdigest()[:24]
        for text in (output.plain.getvalue(), output.policy.getvalue()):
            self.assertIn(f"file_commit_outcome_unknown ref={reference} row=User:{self.owner_id}", text)
            self.assertIn("retaining file for reconciliation", text)
            self.assertIn("error=OSError", text)
            for secret in (str(self.path), str(self.path.parent), "PRIVATE_FILENAME", "PRIVATE_PROBE_VALUE", "PRIVATE_COMMIT_VALUE", "PRIVATE_URL"):
                self.assertNotIn(secret, text)
        self.assert_safe_records(output)
        self.assertTrue(self.path.is_file())

    def test_rollback_deletion_failure_logs_reference_in_background_production(self):
        with self.capture() as output, patch.object(transaction_files.os, "remove", side_effect=OSError("PRIVATE_DELETE_VALUE")):
            self.session.rollback()
        for text in (output.plain.getvalue(), output.policy.getvalue()):
            self.assertIn("file_rollback_removal_failed ref=", text)
            self.assertIn(f"row=User:{self.owner_id}", text)
            self.assertIn("error=OSError", text)
            for secret in (str(self.path), "PRIVATE_FILENAME", "PRIVATE_DELETE_VALUE"):
                self.assertNotIn(secret, text)
        self.assert_safe_records(output)
        self.assertTrue(self.path.is_file())

    def test_dev_retains_full_path_and_exception_value(self):
        self.fail_commit()
        with self.capture(dev=True) as output, patch.object(self.engine, "connect", side_effect=OSError("DEV_PROBE_VALUE")):
            self.session.rollback()
        for text in (output.plain.getvalue(), output.policy.getvalue()):
            self.assertIn(str(self.path), text)
            self.assertIn("DEV_PROBE_VALUE", text)
            self.assertIn("Traceback", text)
        self.assertIsNotNone(output.emit.call_args.args[0].exc_info)
        self.assertTrue(self.path.is_file())

    def test_production_details_retain_full_path_and_exception_value(self):
        self.fail_commit()
        with self.capture(details=True) as output, patch.object(self.engine, "connect", side_effect=OSError("PROBE_VALUE")):
            self.session.rollback()
        for text in (output.plain.getvalue(), output.policy.getvalue()):
            self.assertIn(str(self.path), text)
            self.assertIn("PROBE_VALUE", text)
            self.assertIn("file_commit_outcome_unknown ref=", text)
            self.assertIn(f"row=User:{self.owner_id}", text)
            self.assertIn("Traceback", text)
        self.assertTrue(self.path.is_file())

    def test_dev_keeps_full_deletion_error_for_plain_host_handler(self):
        with self.capture(dev=True) as output, patch.object(transaction_files.os, "remove", side_effect=OSError("DEV_DELETE_VALUE")):
            self.session.rollback()
        for text in (output.plain.getvalue(), output.policy.getvalue()):
            self.assertIn(str(self.path), text)
            self.assertIn("DEV_DELETE_VALUE", text)
            self.assertIn("Traceback", text)
        self.assertTrue(self.path.is_file())

    def test_unknown_outcome_without_app_config_keeps_full_background_details(self):
        self.fail_commit()
        with self.capture(configured=False) as output, patch.object(self.engine, "connect", side_effect=OSError("PRIVATE_PROBE_VALUE")):
            self.assertIsNone(logs._get_config())
            self.assertFalse(logs._dev_mode())
            self.session.rollback()
        for text in (output.plain.getvalue(), output.policy.getvalue()):
            self.assertIn(str(self.path), text)
            self.assertIn("PRIVATE_PROBE_VALUE", text)
            self.assertIn("Traceback", text)
        self.assertTrue(self.path.is_file())

    def test_deletion_failure_without_app_config_keeps_full_background_details(self):
        with self.capture(configured=False) as output, patch.object(transaction_files.os, "remove", side_effect=OSError("PRIVATE_DELETE_VALUE")):
            self.session.rollback()
        for text in (output.plain.getvalue(), output.policy.getvalue()):
            self.assertIn(str(self.path), text)
            self.assertIn("PRIVATE_DELETE_VALUE", text)
            self.assertIn("Traceback", text)
        self.assertTrue(self.path.is_file())

    def test_production_omits_unsafe_exception_type_names(self):
        error_type = type("PRIVATE_TYPE\nINJECTED", (OSError,), {})
        with self.capture() as output, patch.object(transaction_files.os, "remove", side_effect=error_type("PRIVATE_ERROR_VALUE")):
            self.session.rollback()
        self.assert_safe_records(output)
        for text in (output.plain.getvalue(), output.policy.getvalue()):
            self.assertIn("error=Exception", text)
            self.assertNotIn("PRIVATE_TYPE", text)
            self.assertNotIn("INJECTED", text)
        self.assertTrue(self.path.is_file())

    def test_reference_omits_secret_keys_unusual_model_names_and_overlong_paths(self):
        reference = transaction_files._file_log_reference("/private/PRIVATE_PATH", "PRIVATE_MODEL\nINJECTED", ("PRIVATE_KEY",))
        self.assertRegex(reference, r"^ref=[0-9a-f]{24} row=\[omitted\]:\[omitted\]$")
        self.assertNotIn("PRIVATE", reference)
        reference = transaction_files._file_log_reference("PRIVATE_PATH" * 10000, "Owner", (1 << 1000,))
        self.assertEqual(reference, "ref=[omitted] row=Owner:[omitted]")
