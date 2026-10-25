import importlib
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import bafser_config
from bafser import get_datetime_now, get_datetime_utc, parse_date
from bafser.utils import get_datetime_utc as utils_utc


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
                self.assertEqual(parse_date(value), datetime(2026, 10, 12, 15, 0))
            self.assertEqual(parse_date("invalid"), None)

    def test_legacy_parser_keeps_its_behavior(self):
        with patch.object(bafser_config, "datetime_utc", False, create=True):
            self.assertEqual(parse_date("2026-10-12T18:00:00+03:00"), datetime(2026, 10, 12, 18, 0, tzinfo=timezone(timedelta(hours=3))))

    def test_file_logs_use_utc_in_utc_mode(self):
        from bafser.logger import customTime

        with patch.object(bafser_config, "datetime_utc", True, create=True):
            self.assertLess(abs((datetime(*customTime()[:6], tzinfo=timezone.utc) - get_datetime_utc()).total_seconds()), 2)
