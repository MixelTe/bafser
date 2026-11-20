"""Privacy, bounded diagnostics, rotation and dashboard regression tests."""

import io
import json
import logging
import sys
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask, g

import bafser_config
from bafser import logger as logs
from bafser.app import AppConfig, RequestPolicy
from bafser.dashboard import _recent_lines, render_dashboard_page


class LoggingPolicyTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.add_url_rule("/api/orders/<order_ref>", "order", lambda order_ref: {})

    @contextmanager
    def request(self, *, dev=False, details=True, policy=None, path="/api/orders/private-ref?accessToken=URL_SECRET", payload=None):
        policy = policy or RequestPolicy()
        config = SimpleNamespace(DEV_MODE=dev, LOG_ERROR_DETAILS=details, REQUEST_POLICY=policy)
        with patch.object(logs, "_get_config", return_value=config), self.app.test_request_context(path):
            g.request_policy = policy
            g.json = (payload, payload is not None)
            g.req_id = "request-test"
            g.userId = 7
            yield

    def test_reduced_production_omits_body_url_values_and_untrusted_message(self):
        payload = {"buyerEmail": "BODY_SECRET", "accessToken": "TOKEN_SECRET"}
        record = logging.makeLogRecord({"msg": "EXCEPTION_SECRET", "levelno": logging.ERROR})
        with self.request(details=False, payload=payload):
            self.assertIsNone(logs.format_log_data(payload))
            text = logs.RequestFormatter("%(url)s %(json)s %(message)s").format(record)
        for secret in ("BODY_SECRET", "TOKEN_SECRET", "URL_SECRET", "EXCEPTION_SECRET", "private-ref"):
            self.assertNotIn(secret, text)
        self.assertIn("/api/orders/<order_ref>", text)
        # Privacy formatting must not corrupt the shared LogRecord.
        self.assertEqual(record.msg, "EXCEPTION_SECRET")

    def test_dev_keeps_complete_data_and_query_despite_old_formatter_caps(self):
        value = "DEV_SECRET" * 2000
        record = logging.makeLogRecord({"msg": value})
        formatter = logs.RequestFormatter("%(url)s %(json)s %(message)s")
        formatter.max_msg_len = 8
        formatter.max_json_len = 8
        with self.request(dev=True, payload={"password": value}):
            text = formatter.format(record)
            self.assertEqual(json.loads(logs.format_log_data({"password": value})), {"password": value})
        self.assertIn(value, text)
        self.assertIn("accessToken=URL_SECRET", text)

    def test_default_production_keeps_messages_and_chained_exceptions_without_enabling_body_or_query(self):
        self.assertTrue(AppConfig().LOG_ERROR_DETAILS)
        try:
            try:
                raise KeyError("ticketId")
            except KeyError as error:
                raise ValueError("Payment failed: " + "details " * 1000) from error
        except ValueError:
            record = logging.makeLogRecord({"msg": "Order %s failed", "args": (42,), "exc_info": sys.exc_info()})
        formatter = logs.RequestFormatter("%(url)s %(json)s %(message)s")
        with self.request(policy=RequestPolicy(max_log_length=128), payload={"value": "BODY_SECRET"}):
            text = formatter.format(record)
        for expected in ("Order 42 failed", "KeyError: 'ticketId'", "ValueError: Payment failed: " + "details " * 1000, "Traceback"):
            self.assertIn(expected, text)
        for hidden in ("BODY_SECRET", "URL_SECRET", "private-ref"):
            self.assertNotIn(hidden, text)

    def test_default_details_do_not_remove_production_json_redaction_or_bounds(self):
        payload = {"password": "BODY_SECRET", "status": "paid", "large": "X" * 10000}
        with self.request(policy=RequestPolicy(log_body=True, max_log_length=128), payload=payload):
            text = logs.RequestFormatter("%(json)s %(message)s").format(logging.makeLogRecord({"msg": "Payment accepted"}))
        self.assertIn("Payment accepted", text)
        self.assertIn("paid", text)
        self.assertIn("truncated", text)
        self.assertNotIn("BODY_SECRET", text)
        self.assertLess(len(text), 180)

    def test_dev_keeps_error_details_even_when_production_details_are_disabled(self):
        with self.request(dev=True, details=False):
            self.assertEqual(logs.RequestFormatter("%(message)s").format(logging.makeLogRecord({"msg": "Full dev message"})), "Full dev message")

    def test_error_detail_switch_requires_bool(self):
        with self.assertRaises(TypeError):
            AppConfig(LOG_ERROR_DETAILS="false")  # type: ignore[arg-type]

    def test_explicit_message_cap_in_full_production_keeps_full_exception(self):
        try:
            raise ValueError("FULL_EXCEPTION_VALUE")
        except ValueError:
            record = logging.makeLogRecord({"msg": "Long message %s", "args": ("value",), "exc_info": sys.exc_info()})
        formatter = logs.RequestFormatter("%(message)s")
        formatter.max_msg_len = 8
        with self.request():
            text = formatter.format(record)
        self.assertTrue(text.startswith("Long mes[truncated]"))
        self.assertIn("ValueError: FULL_EXCEPTION_VALUE", text)
        self.assertEqual(record.msg, "Long message %s")
        self.assertEqual(record.args, ("value",))

    def test_formatter_failure_reports_its_own_exception_without_dumping_record(self):
        for details in (False, True):
            with self.subTest(details=details), self.request(details=details):
                record = logging.makeLogRecord({"msg": "%s %s", "args": ("RAW_ARGUMENT",), "bafser_safe_message": True})
                text = logs.RequestFormatter("%(message)s").format(record)
            self.assertTrue(text.startswith("[log formatting failed]"))
            self.assertEqual("TypeError" in text, details)
            self.assertEqual("Traceback" in text, details)
            self.assertNotIn("RAW_ARGUMENT", text)

    def test_production_outer_args_cannot_override_http_policy_fields(self):
        formatter = logs.RequestFormatter("%(json)s %(url)s %(uid)s %(job)s %(message)s")
        formatter.outer_args = ["json", "url", "uid", "job"]
        for details in (False, True):
            record = logging.makeLogRecord({
                "msg": "event %(tag)s", "bafser_safe_message": True,
                "args": {"tag": "ok", "json": "RAW_BODY", "url": "/raw?token=RAW_QUERY", "uid": "FAKE_USER", "job": "mail"},
            })
            with self.subTest(details=details), self.request(details=details, policy=RequestPolicy(log_body=False, log_query=False)):
                text = formatter.format(record)
            self.assertIn("/api/orders/<order_ref> 7 ", text)
            self.assertIn("event ok", text)
            self.assertEqual("mail" in text, details)
            for raw in ("RAW_BODY", "RAW_QUERY", "FAKE_USER", "private-ref"):
                self.assertNotIn(raw, text)
            self.assertEqual(record.args["uid"], "FAKE_USER")

    def test_production_explicit_body_fields_use_normalized_redaction(self):
        policy = RequestPolicy(log_body=True, body_fields=("status", "nested", "buyerEmail"), sensitive_fields=("specialSecret",))
        payload = {
            "status": "paid", "buyerEmail": "PRIVATE_EMAIL", "unapproved": "PRIVATE_OTHER",
            "nested": {"accessToken": "PRIVATE_TOKEN", "special_secret": "PRIVATE_CUSTOM", "count": 2},
        }
        with self.request(policy=policy):
            text = logs.format_log_data(payload)
        data = json.loads(text)
        self.assertEqual(data["status"], "paid")
        self.assertEqual(data["nested"]["count"], 2)
        self.assertNotIn("unapproved", data)
        for secret in ("PRIVATE_EMAIL", "PRIVATE_OTHER", "PRIVATE_TOKEN", "PRIVATE_CUSTOM"):
            self.assertNotIn(secret, text)

    def test_allowlist_matches_exact_unicode_keys_without_collapsing_other_names(self):
        payload = {"статус": "готово", "личныеДанные": "PRIVATE_VALUE", "状态": "PRIVATE_CHINESE", "!!!": "PRIVATE_PUNCTUATION"}
        with self.request(policy=RequestPolicy(log_body=True, body_fields=("статус",))):
            self.assertEqual(json.loads(logs.format_log_data(payload)), {"статус": "готово"})

    def test_allowlist_requires_explicit_ascii_aliases(self):
        payload = {"orderId": 1, "order_id": 2, "OrderId": 3, "order-id": 4}
        for allowed, expected in (
            (("orderId",), {"orderId": 1}),
            (("orderId", "order_id"), {"orderId": 1, "order_id": 2}),
        ):
            with self.subTest(allowed=allowed), self.request(policy=RequestPolicy(log_body=True, body_fields=allowed)):
                self.assertEqual(json.loads(logs.format_log_data(payload)), expected)

    def test_dev_ignores_body_allowlist_and_retains_complete_payload(self):
        payload = [{"статус": "готово", "личныеДанные": "DEV_VALUE", "password": "DEV_PASSWORD"}]
        with self.request(dev=True, policy=RequestPolicy(log_body=True, body_fields=("статус",))):
            self.assertEqual(json.loads(logs.format_log_data(payload)), payload)

    def test_body_field_allowlist_omits_non_object_roots(self):
        policy = RequestPolicy(log_body=True, body_fields=("status",))
        for payload in ([{"status": "ok", "private": "PRIVATE_VALUE"}], ["PRIVATE_VALUE"], "PRIVATE_VALUE", 7, None):
            with self.subTest(payload=payload), self.request(policy=policy):
                self.assertEqual(json.loads(logs.format_log_data(payload)), "[omitted by log policy]")

    def test_allowed_root_fields_keep_nested_objects_and_arrays_with_redaction(self):
        payload = {"status": [{"details": "allowed", "password": "PRIVATE_PASSWORD"}], "private": "PRIVATE_OTHER"}
        with self.request(policy=RequestPolicy(log_body=True, body_fields=("status",))):
            text = logs.format_log_data(payload)
        self.assertEqual(json.loads(text), {"status": [{"details": "allowed", "password": "***"}]})

    def test_overlong_field_names_are_omitted_without_disclosing_a_prefix(self):
        private_key = "PRIVATE_KEY_" + "x" * 1000000
        payload = {private_key: "PRIVATE_VALUE", "status": "ok"}
        for allowed in (None, ("status",), (private_key, "status")):
            with self.subTest(allowed=allowed):
                self.assertEqual(logs.redact_sensitive_data(payload, body_fields=allowed), {"status": "ok"})

    def test_allowlist_work_is_bounded_when_many_unapproved_keys_precede_allowed_fields(self):
        payload = {f"PRIVATE_KEY_{index}": "PRIVATE_VALUE" for index in range(10000)}
        payload["status"] = "ok"
        result = logs.redact_sensitive_data(payload, body_fields=("status",))
        self.assertEqual(result, {"[truncated]": True})

    def test_production_diagnostics_bound_cycles_large_values_and_traversal(self):
        cycle = {"status": "ok"}
        cycle["nested"] = cycle
        with self.request(policy=RequestPolicy(log_body=True, max_log_length=128)):
            text = logs.format_log_data({"cycle": cycle, "large": "X" * 1000000})
        self.assertLessEqual(len(text), 139)
        self.assertNotIn("X" * 128, text)
        self.assertIn("truncated", text)

    def test_production_exception_preserves_frames_and_type_without_value_or_source(self):
        try:
            raise ValueError("PRIVATE_EXCEPTION_VALUE")
        except ValueError:
            record = logging.makeLogRecord({
                "msg": "Request failed", "exc_info": sys.exc_info(), "levelno": logging.ERROR,
                "bafser_safe_message": True,
            })
        with self.request(details=False):
            text = logs.RequestFormatter("%(message)s").format(record)
        self.assertIn("Request failed", text)
        self.assertIn("ValueError", text)
        self.assertIn("test_production_exception_preserves_frames", text)
        self.assertNotIn("PRIVATE_EXCEPTION_VALUE", text)
        self.assertNotIn("raise ValueError", text)

    def test_dev_exception_keeps_value(self):
        try:
            raise ValueError("DEV_EXCEPTION_VALUE")
        except ValueError:
            record = logging.makeLogRecord({"msg": "failure", "exc_info": sys.exc_info()})
        with self.request(dev=True):
            text = logs.RequestFormatter("%(message)s").format(record)
        self.assertIn("DEV_EXCEPTION_VALUE", text)

    def test_production_trusted_message_requires_explicit_trust_and_is_bounded(self):
        formatter = logs.RequestFormatter("%(message)s")
        with self.request(details=False, policy=RequestPolicy(max_log_length=128)):
            for marker in (False, "untrusted"):
                record = logging.makeLogRecord({
                    "msg": "PRIVATE_RAW", "bafser_safe_message": marker,
                })
                self.assertEqual(formatter.format(record), "[omitted by log policy]")
            record = logging.makeLogRecord({
                "msg": "trusted " + "x" * 10000, "bafser_safe_message": True,
            })
            text = formatter.format(record)
        self.assertTrue(text.startswith("trusted "))
        self.assertLessEqual(len(text), 139)

    def test_production_trace_is_bounded_and_keeps_exception_type(self):
        def recurse(depth):
            if depth:
                return recurse(depth - 1)
            raise ValueError("PRIVATE_VALUE")

        try:
            recurse(100)
        except ValueError:
            record = logging.makeLogRecord({"msg": "failed", "exc_info": sys.exc_info()})
        with self.request(details=False, policy=RequestPolicy(max_log_length=128)):
            text = logs.RequestFormatter("%(message)s").format(record)
        self.assertIn("ValueError", text)
        self.assertNotIn("PRIVATE_VALUE", text)
        self.assertLess(len(text), 200)

    def test_explicit_query_logging_keeps_names_but_masks_unknown_provider_values(self):
        with self.request(policy=RequestPolicy(log_query=True), path="/api/orders/ref?providerCustom=PRIVATE&amount=123"):
            text = logs.format_log_url()
        self.assertIn("providerCustom=", text)
        self.assertIn("amount=", text)
        self.assertNotIn("PRIVATE", text)
        self.assertNotIn("123", text)

    def test_query_visibility_matches_explicit_policy_in_both_modes(self):
        path = "/api/orders/private-ref"
        full_path = path + "?accessToken=PRIVATE_QUERY&payload=" + "DEV_COMPLETE" * 50
        prod_path = "/api/orders/<order_ref>"
        for dev in (False, True):
            for log_query in (False, None, True):
                policy = RequestPolicy(log_query=log_query, max_log_length=128)
                with self.subTest(dev=dev, log_query=log_query), self.request(dev=dev, policy=policy, path=full_path):
                    if dev:
                        expected = path if log_query is False else full_path
                    else:
                        expected = prod_path + "?accessToken=%2A%2A%2A&payload=%2A%2A%2A" if log_query is True else prod_path
                    self.assertEqual(logs.format_log_url(), expected)
                    self.assertEqual(logs.RequestFormatter("%(url)s").format(logging.makeLogRecord({"msg": "test"})), expected)

    def test_proxy_ip_header_is_not_trusted_by_formatter(self):
        with self.request(), patch.object(logs.request, "headers", {"X-Real-IP": "FORGED_IP"}):
            record = logging.makeLogRecord({"msg": "test"})
            text = logs.RequestFormatter("%(ip)s").format(record)
        self.assertNotIn("FORGED_IP", text)

    def test_background_extra_payload_and_formatter_failure_remain_private(self):
        config = SimpleNamespace(DEV_MODE=False, LOG_ERROR_DETAILS=False, REQUEST_POLICY=RequestPolicy())
        with patch.object(logs, "_get_config", return_value=config):
            formatter = logs.RequestFormatter("%(url)s %(json)s %(message)s")
            record = logging.makeLogRecord({"msg": "secret", "json": "PRIVATE_EXTRA", "url": "PRIVATE_URL"})
            text = formatter.format(record)
            self.assertNotIn("PRIVATE_EXTRA", text)
            self.assertNotIn("PRIVATE_URL", text)
            malformed = logging.makeLogRecord({"msg": "%s %s", "args": ("PRIVATE_ARG",), "bafser_safe_message": True})
            self.assertEqual(formatter.format(malformed), "[log formatting failed]")


class LoggingFileTests(unittest.TestCase):
    def test_production_write_diagnostics_tolerate_restrictive_stderr_encoding(self):
        config = SimpleNamespace(DEV_MODE=False, LOG_ERROR_DETAILS=True)
        output = io.TextIOWrapper(io.BytesIO(), encoding="ascii", errors="strict")
        self.addCleanup(output.close)
        with tempfile.TemporaryDirectory() as directory:
            handler = logs.RotatingFileHandler(Path(directory) / "errors.log", encoding="utf8")
            handler.setFormatter(logs.RequestFormatter("%(message)s"))
            try:
                with (
                    patch.object(logs, "_get_config", return_value=config),
                    patch.object(handler.stream, "write", side_effect=OSError("Ошибка записи")),
                    patch.object(logs.sys, "stderr", output),
                ):
                    handler.emit(logging.makeLogRecord({"msg": "event"}))
                output.flush()
                self.assertIn(b"bafser log write failed", output.buffer.getvalue())
            finally:
                handler.close()

    def test_production_write_failure_reports_its_own_exception_without_dumping_record(self):
        with tempfile.TemporaryDirectory() as directory:
            handler = logs.RotatingFileHandler(Path(directory) / "errors.log", encoding="utf8")
            handler.setFormatter(logs.RequestFormatter("%(message)s"))
            try:
                for details in (False, True):
                    config = SimpleNamespace(DEV_MODE=False, LOG_ERROR_DETAILS=details)
                    output = io.StringIO()
                    with (
                        self.subTest(details=details),
                        patch.object(logs, "_get_config", return_value=config),
                        patch.object(handler.stream, "write", side_effect=OSError("DISK_FAILURE_REASON")),
                        patch.object(logs.sys, "stderr", output),
                    ):
                        handler.emit(logging.makeLogRecord({"msg": "Request;;%s", "args": ("RAW_BODY_ARGUMENT",)}))
                    text = output.getvalue()
                    self.assertIn("bafser log write failed", text)
                    self.assertIn("OSError", text)
                    self.assertEqual("DISK_FAILURE_REASON" in text, details)
                    self.assertEqual("Traceback" in text, details)
                    self.assertNotIn("RAW_BODY_ARGUMENT", text)
            finally:
                handler.close()

    def test_single_process_rotation_retains_only_configured_backups(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "requests.csv"
            handler = logs.RotatingFileHandler(path, maxBytes=100, backupCount=2, encoding="utf8")
            try:
                for index in range(20):
                    handler.emit(logging.makeLogRecord({"msg": f"event-{index}-" + "X" * 60}))
            finally:
                handler.close()
            self.assertLessEqual(len(list(Path(directory).glob("requests.csv*"))), 3)
            self.assertIn("event-19-", path.read_text(encoding="utf8"))
            self.assertTrue(Path(str(path) + ".1").is_file())

    def test_archive_discovery_accepts_legacy_names_and_numbering_gaps(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory) / "requests.csv"
            standard = Path(str(base) + ".2")
            legacy = Path(directory) / "requests.7.csv"
            unrelated = Path(directory) / "different.1.csv"
            for path in (base, standard, legacy, unrelated):
                path.write_text("line\n", encoding="utf8")
            self.assertEqual(set(logs.get_log_fpath_all(str(base))), {str(base), str(standard), str(legacy)})
            self.assertEqual(len(logs.get_log_fpath_all(str(base), limit=2)), 2)

    def test_multiprocess_rotation_uses_the_same_bounded_archive_format(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "requests.csv"
            config = SimpleNamespace(AUTO_SETUP=True, DEV_MODE=False, MULTIPROCESS_LOGGING=True)
            with patch.object(logs, "_get_config", return_value=config), patch.object(logs, "MaxBytes", 100), patch.object(logs, "BackupCount", 2):
                handler = logs.create_log_handler(str(path), "%(message)s")
                try:
                    for index in range(20):
                        handler.emit(logging.makeLogRecord({"msg": f"event-{index}-" + "X" * 60, "bafser_safe_message": True}))
                finally:
                    handler.close()
            self.assertLessEqual(len(logs.get_log_fpath_all(str(path))), 3)
            self.assertIn("event-19-", path.read_text(encoding="utf8"))

    def test_runtime_does_not_create_missing_log_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unexpected" / "requests.csv"
            config = SimpleNamespace(AUTO_SETUP=False, DEV_MODE=False)
            with patch.object(logs, "_get_config", return_value=config), patch.object(sys, "argv", ["runtime"]):
                with self.assertRaises(FileNotFoundError):
                    logs.create_log_handler(str(path))
            self.assertFalse(path.parent.exists())

    def test_reconfiguration_preserves_external_handler_and_closes_own_handlers(self):
        root = logging.getLogger()
        existing = list(root.handlers)
        previous_level = root.level
        external = logging.StreamHandler(io.StringIO())
        root.addHandler(external)
        try:
            with tempfile.TemporaryDirectory() as directory:
                paths = {name: str(Path(directory) / (name + ".log")) for name in (
                    "log_errors_path", "log_info_path", "log_requests_path", "log_frontend_path", "log_dashboard_path",
                )}
                config = SimpleNamespace(AUTO_SETUP=True, MULTIPROCESS_LOGGING=False, DEV_MODE=False)
                with patch.multiple(bafser_config, **paths), patch.object(logs, "_get_config", return_value=config):
                    logs.setLogging()
                    first = [handler for handler in root.handlers if getattr(handler, "_bafser_handler", False)]
                    logs.setLogging()
                    self.assertIn(external, root.handlers)
                    self.assertTrue(all(handler.stream is None for handler in first))
                    self.assertEqual(len([handler for handler in root.handlers if getattr(handler, "_bafser_handler", False)]), 2)
                    for name in ("", "requests", "frontend", "dashboard"):
                        logs._remove_owned_handlers(logging.getLogger(name))
        finally:
            root.removeHandler(external)
            external.close()
            for handler in list(root.handlers):
                if handler not in existing:
                    root.removeHandler(handler)
                    handler.close()
            root.setLevel(previous_level)


class DashboardTests(unittest.TestCase):
    def test_tail_reader_bounds_lines_and_skips_partial_first_line(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "dashboard.csv"
            path.write_bytes(b"PRIVATE_OLD" * 1000 + b"\nnewer\nnewest\n")
            self.assertEqual(list(_recent_lines([str(path)], 30, 1)), ["newest"])

    def test_dashboard_reads_recent_valid_bounded_rows_from_both_formats(self):
        app = Flask(__name__)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        recent = (now - timedelta(minutes=1)).isoformat()
        old = (now - timedelta(days=30)).isoformat()
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory) / "dashboard.csv"
            base.write_text(f"{old};too_old;1000000;200;r;ip;1\n{recent};current;2000000;200;r;ip;1\n", encoding="utf8")
            legacy = Path(directory) / "dashboard.3.csv"
            legacy.write_text(f"{recent};legacy;3000000;200;r;ip;1\n{recent};invalid;nan;200;r;ip;1\n", encoding="utf8")
            with (
                app.app_context(), patch.object(bafser_config, "datetime_utc", True),
                patch.object(bafser_config, "log_dashboard_path", str(base)),
                patch("bafser.dashboard.render_template", side_effect=lambda template, **values: values["dashboard"]),
            ):
                payload = render_dashboard_page()
        endpoints = {item["endpoint"]: item for item in payload["endpoints"]}
        self.assertEqual(set(endpoints), {"current", "legacy"})
        self.assertEqual(endpoints["current"]["p50"], 2.0)
        self.assertEqual(endpoints["legacy"]["p50"], 3.0)
