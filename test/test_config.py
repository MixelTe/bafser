"""Configuration validation and package bootstrap checks."""

import os
import runpy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType

from bafser import validate_config


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.example = Path(__file__).resolve().parents[1] / "src/bafser/bafser_config.example.py"
        self.config = ModuleType("bafser_config")
        vars(self.config).update(runpy.run_path(str(self.example)))

    def test_example_and_current_config_are_valid(self):
        self.assertIsNone(validate_config(self.config))
        self.assertIsNone(validate_config())

    def test_each_base_field_is_required(self):
        fields = [name for name in vars(self.config) if not name.startswith("_")]
        for name in fields:
            with self.subTest(name=name):
                value = vars(self.config).pop(name)
                with self.assertRaisesRegex(ValueError, f"{name}: required field is missing"):
                    validate_config(self.config)
                setattr(self.config, name, value)

    def test_types_empty_paths_and_invalid_values_are_rejected(self):
        for name, values in (
            ("db_mysql", (0, 1, None, "true")),
            ("datetime_utc", (0, "False", None)),
            ("use_alembic", (1, "True", None)),
            ("sql_echo", (0, 1, "true", None)),
            ("allow_unsupported_for_update_clause", (0, 1, "False")),
            ("db_dev_path", (None, "", " ", "ENV:", "ENV: ")),
            ("api_url", (None, "", "api/", "/api?x=1", "/api#fragment")),
            ("jwt_key_file_path", (None, Path("key.txt"), "", "\0")),
        ):
            original = getattr(self.config, name)
            for value in values:
                with self.subTest(name=name, value=value):
                    setattr(self.config, name, value)
                    with self.assertRaisesRegex(ValueError, name + ":"):
                        validate_config(self.config)
            setattr(self.config, name, original)

    def test_errors_are_aggregated_without_config_values(self):
        del self.config.datetime_utc
        self.config.db_mysql = "secret-db-value"
        self.config.jwt_key_file_path = "\0secret-key-value"
        with self.assertRaises(ValueError) as error:
            validate_config(self.config)
        message = str(error.exception)
        for name in ("datetime_utc", "db_mysql", "jwt_key_file_path"):
            self.assertIn(name + ":", message)
        self.assertNotIn("secret-db-value", message)
        self.assertNotIn("secret-key-value", message)

    def test_extra_fields_and_explicit_supported_options_are_allowed(self):
        self.config.project_setting = object()
        self.config.sql_echo = "debug"
        for value in (None, True, False):
            self.config.allow_unsupported_for_update_clause = value
            self.assertIsNone(validate_config(self.config))

    def test_environment_and_files_are_not_required_at_import(self):
        self.config.db_dev_path = "ENV:BAFSER_UNSET_TEST_DATABASE"
        self.config.jwt_key_file_path = "not-created-yet/key.txt"
        self.config.db_path = ""
        self.assertIsNone(validate_config(self.config))
        self.config.db_mysql = False
        with self.assertRaisesRegex(ValueError, "db_path:"):
            validate_config(self.config)

    def run_import(self, directory, command="import bafser"):
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(self.example.parents[1])
        return subprocess.run(
            [sys.executable, "-c", command], cwd=directory, env=environment,
            capture_output=True, text=True, timeout=30,
        )

    def test_invalid_imported_config_fails_before_consumers_load(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "bafser_config.py"
            config_path.write_text("db_mysql = 'secret-value'\n", encoding="utf8")
            result = self.run_import(directory)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Invalid bafser_config:", result.stderr)
            self.assertIn("db_mysql: expected bool", result.stderr)
            self.assertIn("db_path: required field is missing", result.stderr)
            self.assertNotIn("secret-value", result.stderr)
            self.assertEqual(config_path.read_text(encoding="utf8"), "db_mysql = 'secret-value'\n")

    def test_config_found_after_path_fallback_is_also_validated(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "bafser_config.py").write_text("db_mysql = False\n", encoding="utf8")
            result = self.run_import(directory, "import sys; sys.path.remove(''); import bafser")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Invalid bafser_config:", result.stderr)

    def test_missing_dependency_does_not_overwrite_config(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "bafser_config.py"
            source = "import bafser_missing_config_dependency\n"
            config_path.write_text(source, encoding="utf8")
            result = self.run_import(directory)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("bafser_missing_config_dependency", result.stderr)
            self.assertEqual(config_path.read_text(encoding="utf8"), source)

    def test_missing_config_is_created_and_can_be_validated(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_import(directory, "from bafser import validate_config; validate_config()")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((Path(directory) / "bafser_config.py").is_file())
