"""Bounded diagnostic samples, shared filters, cache isolation and safe HTML."""

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from flask import Flask

import bafser_config
from bafser.dashboard import _read_tails, render_dashboard_page


class DashboardTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "dashboard.csv"
        self.app = Flask(__name__)
        self.app.config["DASHBOARD_CACHE_SECONDS"] = 0
        self.app.add_url_rule("/dashboard", "dashboard", render_dashboard_page)
        for name, value in (("log_dashboard_path", str(self.path)), ("datetime_utc", True)):
            patcher = patch.object(bafser_config, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.now = datetime.now(timezone.utc)

    def row(self, endpoint="sample", *, duration=10, status=200, minutes=1, request_id="request-id", timestamp=None):
        stamp = timestamp if timestamp is not None else self.now - timedelta(minutes=minutes)
        return f"{stamp.isoformat()};{endpoint};{duration * 1_000_000};{status};{request_id};PRIVATE_IP;PRIVATE_UID\n"

    def write(self, *rows):
        self.path.write_text("".join(rows), encoding="utf8")

    def data(self, query="", *, app=None):
        with (
            (app or self.app).test_request_context("/dashboard" + query),
            patch("bafser.dashboard.render_template", side_effect=lambda template, **values: values["dashboard"]),
        ):
            return render_dashboard_page()

    def test_one_filter_set_controls_every_metric_and_recent_requests(self):
        self.write(
            self.row("orders", duration=100, status=500, request_id="matching"),
            self.row("orders", duration=10, status=200),
            self.row("orders", duration=50, status=404, minutes=120),
            self.row("other", duration=400, status=503),
        )
        result = self.data("?hours=1&endpoint=orders&status=errors")
        self.assertEqual(result["stats"]["count"], 1)
        self.assertEqual(result["stats"]["server_errors"], 1)
        self.assertEqual(result["stats"]["client_errors"], 0)
        self.assertEqual(result["stats"]["p50"], 100)
        self.assertEqual(result["stats"]["p95"], 100)
        self.assertEqual([item["endpoint"] for item in result["endpoints"]], ["orders"])
        self.assertEqual(sum(item["count"] for item in result["trend"]), 1)
        self.assertEqual(sum(item["errors"] for item in result["trend"]), 1)
        self.assertEqual([item["request_id"] for item in result["recent"]], ["matching"])

    def test_percentiles_are_interpolated_and_latency_is_not_capped(self):
        self.write(*(self.row(f"route{index}", duration=value) for index, value in enumerate((1, 2, 3, 4, 5, 100000))))
        result = self.data()
        self.assertEqual(result["stats"]["p50"], 3.5)
        self.assertAlmostEqual(result["stats"]["p95"], 75001.25)
        self.assertEqual(result["stats"]["max"], 100000)
        self.assertEqual(next(item for item in result["endpoints"] if item["endpoint"] == "route5")["max"], 100000)

    def test_legacy_missing_status_is_unknown_not_success_and_invalid_values_are_skipped(self):
        stamp = (self.now - timedelta(minutes=1)).isoformat()
        self.write(
            f"{stamp};old;1000000\n",
            f"{stamp};older;2000000;500\n",
            self.row("modern", status=404),
            self.row("bad", duration=float("nan")),
            self.row("bad", duration=-1),
            self.row("future", minutes=-10),
            self.row("expired", minutes=60 * 30),
            "malformed\n",
        )
        result = self.data()
        self.assertEqual(result["stats"]["count"], 3)
        self.assertEqual(result["stats"]["unknown_status"], 1)
        self.assertEqual(result["stats"]["client_errors"], 1)
        self.assertEqual(result["stats"]["server_errors"], 1)
        self.assertEqual(result["legacy_rows"], 2)
        self.assertEqual(result["invalid_rows"], 3)
        self.assertEqual(result["future_rows"], 1)
        self.assertIsNone(next(item for item in result["recent"] if item["endpoint"] == "older")["request_id"])
        unknown = self.data("?status=unknown")
        self.assertEqual(unknown["stats"]["count"], 1)
        self.assertEqual(unknown["recent"], [])

    def test_bounded_reader_reports_partial_bytes_and_line_limits(self):
        self.path.write_bytes(b"private-prefix" * 1000 + b"\nolder\nnewer\nnewest\n")
        lines, info = _read_tails([str(self.path)], 30, 1)
        self.assertEqual(lines, ["newest"])
        self.assertLessEqual(info.bytes_read, 30)
        self.assertEqual(info.lines_read, 1)
        self.assertTrue(info.bytes_limited)
        self.assertTrue(info.lines_limited)

    def test_unfinished_modern_records_are_not_misread_as_complete_legacy_rows(self):
        stamp = (self.now - timedelta(minutes=1)).isoformat()
        legacy = f"{stamp};legacy;1000000\n"
        modern = f"{stamp};modern;1234;500;request-id;ip;1"
        for fields in (3, 4, 7):
            with self.subTest(fields=fields):
                self.write(legacy, ";".join(modern.split(";")[:fields]))
                result = self.data()
                self.assertEqual(result["stats"]["count"], 1)
                self.assertEqual(result["stats"]["p50"], 1)
                self.assertEqual(result["stats"]["unknown_status"], 1)
                self.assertEqual(result["read"].partial_rows, 1)
                self.assertEqual(result["read"].lines_read, 1)
                self.assertEqual(result["legacy_rows"], 1)
        html = self.app.test_client().get("/dashboard").get_data(as_text=True)
        self.assertIn("1 unfinished trailing log rows were ignored", html)
        self.write(legacy, modern + "\n")
        self.assertEqual(self.data()["stats"]["count"], 2)
        self.assertEqual(self.data()["read"].partial_rows, 0)

    def test_file_budget_is_visible_and_both_archive_names_are_supported(self):
        self.write(self.row("current"))
        standard = Path(str(self.path) + ".1")
        legacy = self.path.with_name("dashboard.2.csv")
        standard.write_text(self.row("standard"), encoding="utf8")
        legacy.write_text(self.row("legacy"), encoding="utf8")
        os.utime(legacy, (1, 1))
        result = self.data()
        self.assertEqual({item["endpoint"] for item in result["endpoints"]}, {"current", "standard", "legacy"})
        self.app.config["DASHBOARD_MAX_FILES"] = 1
        limited = self.data()
        self.assertTrue(limited["read"].files_limited)
        self.assertEqual(limited["stats"]["count"], 1)
        html = self.app.test_client().get("/dashboard").get_data(as_text=True)
        self.assertIn("Limited sample", html)

    def test_a_rotated_file_alias_cannot_be_counted_twice(self):
        self.write(self.row("once"))
        alias = Path(str(self.path) + ".1")
        os.link(self.path, alias)
        lines, info = _read_tails([str(self.path), str(alias)], 10000, 100)
        self.assertEqual(len(lines), 1)
        self.assertEqual(info.files_read, 1)

    def test_cache_reuses_one_snapshot_but_refresh_settings_and_expiry_rebuild_it(self):
        self.app.config["DASHBOARD_CACHE_SECONDS"] = 3
        self.write(self.row("first"))
        with patch("bafser.dashboard.time.monotonic", return_value=100) as clock:
            self.assertEqual(self.data()["stats"]["count"], 1)
            self.write(self.row("first"), self.row("second"))
            clock.return_value = 102
            self.assertEqual(self.data("?endpoint=second")["stats"]["count"], 0)
            self.assertEqual(self.data("?refresh=1")["stats"]["count"], 2)
            self.write(self.row("third"))
            clock.return_value = 106
            self.assertEqual(self.data()["stats"]["count"], 1)
            self.write(self.row("third"), self.row("fourth"))
            self.app.config["DASHBOARD_MAX_LINES"] = 1
            self.assertEqual(self.data()["endpoints"][0]["endpoint"], "fourth")
            other = Flask("other")
            other.config["DASHBOARD_CACHE_SECONDS"] = 3
            self.assertEqual(self.data(app=other)["stats"]["count"], 2)

    def test_naive_legacy_time_and_explicit_offsets_share_the_configured_timezone(self):
        with patch.object(bafser_config, "datetime_utc", False):
            local = (self.now + timedelta(hours=3) - timedelta(minutes=1)).replace(tzinfo=None)
            self.write(self.row("local", timestamp=local), self.row("aware"))
            result = self.data()
        self.assertEqual(result["stats"]["count"], 2)
        self.assertEqual(result["timezone"], "UTC+03:00")

    def test_native_logging_timestamp_with_comma_milliseconds_is_supported(self):
        stamp = (self.now - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S,123")
        self.write(f"{stamp};native;1000000;200;request;ip;1\n")
        result = self.data()
        self.assertEqual(result["stats"]["count"], 1)
        self.assertEqual(result["invalid_rows"], 0)

    def test_disabling_cache_takes_effect_immediately(self):
        self.app.config["DASHBOARD_CACHE_SECONDS"] = 3
        self.write(self.row("first"))
        with patch("bafser.dashboard.time.monotonic", return_value=100):
            self.assertEqual(self.data()["stats"]["count"], 1)
            self.write(self.row("first"), self.row("second"))
            self.app.config["DASHBOARD_CACHE_SECONDS"] = 0
            self.assertEqual(self.data()["stats"]["count"], 2)
            self.write(self.row("third"))
            self.assertEqual(self.data()["stats"]["count"], 1)

    def test_render_clock_is_chosen_after_receiving_a_newer_cached_snapshot(self):
        self.app.config["DASHBOARD_CACHE_SECONDS"] = 30
        early = self.now
        later = early + timedelta(seconds=5)
        self.write(self.row("concurrent", timestamp=later))
        with (
            patch("bafser.dashboard.time.monotonic", return_value=100),
            patch("bafser.dashboard.datetime", wraps=datetime) as clock,
        ):
            clock.now.return_value = later
            self.assertEqual(self.data()["stats"]["count"], 1)
            clock.now.side_effect = [early, later + timedelta(seconds=1)]
            result = self.data()
        self.assertEqual(result["stats"]["count"], 1)
        self.assertEqual(result["snapshot_age"], 1)
        self.assertEqual(result["window_end"], (later + timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S"))
        self.assertLessEqual(result["observed_end"], result["window_end"])
        self.assertEqual(sum(bucket["count"] for bucket in result["trend"]), 1)

    def test_multiday_trend_labels_include_dates(self):
        self.app.config["DASHBOARD_WINDOW_HOURS"] = 48
        self.write(self.row("yesterday", minutes=30 * 60), self.row("today"))
        result = self.data("?hours=48")
        for bucket in result["trend"]:
            self.assertRegex(bucket["label"], r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")
        self.assertNotEqual(result["trend"][0]["label"][:10], result["trend"][-1]["label"][:10])

    def test_recent_failures_are_newest_first_and_bounded(self):
        self.app.config["DASHBOARD_RECENT_LIMIT"] = 2
        self.write(
            self.row(status=500, minutes=3, request_id="old"),
            self.row(status=404, minutes=2, request_id="middle"),
            self.row(status=503, minutes=1, request_id="new"),
            self.row(status=200, minutes=0, request_id="success"),
        )
        result = self.data()
        self.assertEqual([item["request_id"] for item in result["recent"]], ["new", "middle"])

    def test_html_escapes_log_content_and_omits_personal_columns_and_remote_assets(self):
        endpoint = '</option><script>alert("endpoint")</script>'
        request_id = '<img src=x onerror="alert(1)">'
        self.write(self.row(endpoint, status=500, request_id=request_id))
        response = self.app.test_client().get("/dashboard")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertNotIn(endpoint, html)
        self.assertNotIn(request_id, html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("&lt;img", html)
        for private in ("PRIVATE_IP", "PRIVATE_UID", "cdn.jsdelivr", "unpkg.com", "|safe"):
            self.assertNotIn(private, html)
        self.assertIn('name="refresh" value="1"', html)

    def test_empty_and_unreadable_sources_are_honest(self):
        empty = self.data()
        self.assertEqual(empty["stats"]["count"], 0)
        self.assertIsNone(empty["stats"]["p50"])
        html = self.app.test_client().get("/dashboard").get_data(as_text=True)
        self.assertIn("No requests match these filters", html)
        self.write(self.row())
        with patch("bafser.dashboard.open", side_effect=PermissionError("private reason")):
            failed = self.data()
        self.assertEqual(failed["read"].read_errors, 1)
        self.assertEqual(failed["stats"]["count"], 0)
        with patch("bafser.dashboard.get_log_fpath_all", side_effect=PermissionError("private directory")):
            failed_directory = self.data()
        self.assertEqual(failed_directory["read"].read_errors, 1)

    def test_invalid_filters_are_rejected_before_reading_logs(self):
        for query in ("?hours=0", "?hours=25", "?hours=bad", "?status=600", "?status=bad", "?endpoint=" + "a" * 257):
            with self.subTest(query=query), patch("bafser.dashboard._load_snapshot") as load:
                self.assertEqual(self.app.test_client().get("/dashboard" + query).status_code, 400)
                load.assert_not_called()
