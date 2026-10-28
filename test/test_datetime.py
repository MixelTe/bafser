import importlib
import subprocess
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import bafser_config
from bafser import get_datetime_now, get_datetime_utc, parse_date, parse_datetime
from bafser.utils import get_datetime_utc as utils_utc
from bafser.utils import parse_date as utils_date, parse_datetime as utils_datetime


class DatetimeTests(unittest.TestCase):
    def test_first_import_creates_configuration_without_a_circular_import(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, "-c", "from bafser import get_datetime_utc, get_datetime_now; get_datetime_utc(); get_datetime_now()"],
                cwd=directory, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_utc_clock_returns_the_actual_utc_instant(self):
        before = datetime.now(timezone.utc)
        now = get_datetime_utc()
        after = datetime.now(timezone.utc)
        self.assertLessEqual(before, now)
        self.assertLessEqual(now, after)
        self.assertEqual(now.tzinfo, timezone.utc)
        self.assertIs(utils_utc, get_datetime_utc)

    def test_shared_models_can_opt_into_utc_without_changing_legacy_projects(self):
        instant = datetime(2026, 10, 12, 15, 0, tzinfo=timezone.utc)
        module = importlib.import_module("bafser.utils.get_datetime_now")
        with patch.object(module, "get_datetime_utc", return_value=instant):
            with patch.object(bafser_config, "datetime_utc", False, create=True):
                self.assertEqual(get_datetime_now(), instant + timedelta(hours=3))
            with patch.object(bafser_config, "datetime_utc", True, create=True):
                self.assertEqual(get_datetime_now(), instant)

    def test_utc_mode_normalizes_offsets_and_treats_naive_input_as_utc(self):
        with patch.object(bafser_config, "datetime_utc", True, create=True):
            for value in ("2026-10-12T18:00:00+03:00", "2026-10-12T15:00:00Z", "2026-10-12T15:00:00"):
                self.assertEqual(parse_datetime(value), datetime(2026, 10, 12, 15, 0))
            self.assertEqual(parse_datetime("invalid"), None)
            self.assertEqual(parse_datetime(date="2026-10-12T15:00:00Z"), datetime(2026, 10, 12, 15))

    def test_legacy_parser_keeps_its_behavior(self):
        with patch.object(bafser_config, "datetime_utc", False, create=True):
            self.assertEqual(parse_datetime("2026-10-12T18:00:00+03:00"), datetime(2026, 10, 12, 18, 0, tzinfo=timezone(timedelta(hours=3))))

    def test_calendar_parser_discards_time_without_timezone_conversion(self):
        self.assertIs(utils_date, parse_date)
        self.assertIs(utils_datetime, parse_datetime)
        self.assertEqual(parse_date(date="2028-02-29"), date(2028, 2, 29))
        cases = [
            ("2028-02-29", date(2028, 2, 29)),
            ("2026-12-31T23:30:12.123456-04:00", date(2026, 12, 31)),
            ("2027-01-01T00:30:00+14:00", date(2027, 1, 1)),
            ("2026-10-12 21:30:00", date(2026, 10, 12)),
            ("2026-10-12T21:30:00Z", date(2026, 10, 12)),
            ("0001-01-01T00:00:00+14:00", date.min),
            ("9999-12-31T23:59:59-12:00", date.max),
        ]
        for utc in (False, True):
            with patch.object(bafser_config, "datetime_utc", utc, create=True):
                for value, expected in cases:
                    with self.subTest(utc=utc, value=value):
                        parsed = parse_date(value)
                        self.assertIs(type(parsed), date)
                        self.assertEqual(parsed, expected)

    def test_parsers_reject_invalid_inputs(self):
        for parser in (parse_date, parse_datetime):
            for value in ("", "invalid", "2026-02-29", "2026-10-12T25:00:00", "2026-10-12junk", None, 123):
                with self.subTest(parser=parser.__name__, value=value):
                    self.assertIsNone(parser(value))

    def test_file_logs_use_utc_in_utc_mode(self):
        from bafser.logger import customTime

        with patch.object(bafser_config, "datetime_utc", True, create=True):
            self.assertLess(abs((datetime(*customTime()[:6], tzinfo=timezone.utc) - get_datetime_utc()).total_seconds()), 2)
