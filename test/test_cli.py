"""CLI configuration checks using real SQLite migrations."""

import importlib
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch


class CliEnvironmentTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.project = Path(directory.name) / "project"
        self.project.mkdir()
        config = Path(__file__).resolve().parents[1] / "src/bafser/bafser_config.example.py"
        (self.project / "bafser_config.py").write_text(
            config.read_text(encoding="utf8")
            + '\ndb_mysql = False\ndb_path = "ENV:DBPATH"\n'
            + 'data_tables_package = None\nmigrations_folder = "alembic"\n',
            encoding="utf8",
        )
        migrations = self.project / "alembic"
        (migrations / "versions").mkdir(parents=True)
        (migrations / "env.py").write_text("from bafser.alembic import run\nrun()\n", encoding="utf8")
        (migrations / "versions/initial.py").write_text(
            'from alembic import op\nimport sqlalchemy as sa\n'
            'revision = "cli_env_test"\ndown_revision = None\n'
            'def upgrade():\n    op.create_table("cli_probe", sa.Column("id", sa.Integer, primary_key=True))\n'
            'def downgrade():\n    op.drop_table("cli_probe")\n',
            encoding="utf8",
        )

    def run_upgrade(self, *, db_path=None, console=False, bootstrap=False):
        environment = os.environ.copy()
        environment.pop("DBPATH", None)
        environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
        environment.pop("PYTHON_DOTENV_DISABLED", None)
        if db_path is not None:
            environment["DBPATH"] = db_path
        if bootstrap:
            command = [sys.executable, "-c", "from bafser_cli import cli; cli()"]
        elif console:
            executable = Path(sys.executable).with_name("bafser.exe" if os.name == "nt" else "bafser")
            command = [str(executable)]
        else:
            command = [sys.executable, "-m", "bafser"]
        return subprocess.run(
            command + ["alembic", "upgrade", "--prod"],
            cwd=self.project,
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def assert_migrated(self, result, filename):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        database = self.project / filename
        self.assertTrue(database.is_file())
        with closing(sqlite3.connect(database)) as connection:
            self.assertEqual(connection.execute("SELECT version_num FROM alembic_version").fetchone(), ("cli_env_test",))
            self.assertEqual(connection.execute("SELECT count(*) FROM cli_probe").fetchone(), (0,))

    def test_both_entry_points_load_current_directory_dotenv(self):
        for console in (False, True):
            with self.subTest(console=console):
                filename = "console.db" if console else "module.db"
                (self.project / ".env").write_text(f"DBPATH='{filename}'\n", encoding="utf8")
                self.assert_migrated(self.run_upgrade(console=console), filename)

    def test_environment_takes_precedence_over_dotenv(self):
        (self.project / ".env").write_text("DBPATH='dotenv.db'\n", encoding="utf8")
        self.assert_migrated(self.run_upgrade(db_path="environment.db"), "environment.db")
        self.assertFalse((self.project / "dotenv.db").exists())

    def test_console_bootstrap_prepares_sibling_imports_before_loading_config(self):
        config = self.project / "bafser_config.py"
        config.write_text(config.read_text(encoding="utf8") + "\nfrom project_settings import db_path\n", encoding="utf8")
        (self.project / "project_settings.py").write_text('db_path = "ENV:DBPATH"\n', encoding="utf8")
        (self.project / ".env").write_text("DBPATH='sibling.db'\n", encoding="utf8")
        self.assert_migrated(self.run_upgrade(bootstrap=True), "sibling.db")

    def test_missing_dotenv_allows_environment_configuration(self):
        self.assert_migrated(self.run_upgrade(db_path="environment.db"), "environment.db")

    def test_parent_directory_dotenv_is_not_loaded(self):
        (self.project.parent / ".env").write_text("DBPATH='parent.db'\n", encoding="utf8")
        result = self.run_upgrade()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("env var not set: DBPATH", result.stderr)
        self.assertFalse((self.project / "parent.db").exists())


class ProjectGeneratorTests(unittest.TestCase):
    def test_telegram_config_paths_are_anchored_to_the_selected_project(self):
        from bafser.scripts.init_project import init_project

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "target"
            with patch("importlib.util.find_spec", return_value=object()):
                init_project(directory=root)
            path = root / "bafser_config.py"
            values = {"__file__": str(path)}
            exec(compile(path.read_text(encoding="utf8"), str(path), "exec"), values)
            for key, relative in (
                ("config_path", "config.txt"),
                ("config_dev_path", "config_dev.txt"), ("log_bot_path", "storage/logs/bot.csv"),
            ):
                with self.subTest(key=key):
                    self.assertEqual(Path(values[key]), root / relative)
            # The current optional integration uses bot_folder as both a relative
            # directory and an import prefix; an absolute path breaks discovery.
            bot = root / values["bot_folder"]
            bot.mkdir()
            (bot / "handler.py").write_text("registered = True\n", encoding="utf8")
            with patch.dict(sys.modules), patch.object(sys, "path", [str(root), *sys.path]):
                sys.modules.pop("bot", None)
                sys.modules.pop("bot.handler", None)
                handler = importlib.import_module(values["bot_folder"] + ".handler")
                self.assertTrue(handler.registered)

    def test_explicit_target_config_can_import_sibling_modules(self):
        from bafser.scripts.init_project import init_project

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            template = Path(__file__).resolve().parents[1] / "src/bafser/bafser_config.example.py"
            (root / "bafser_config.py").write_text(
                template.read_text(encoding="utf8") + "\nfrom bafser_generator_settings import use_alembic\n",
                encoding="utf8",
            )
            (root / "bafser_generator_settings.py").write_text("use_alembic = False\n", encoding="utf8")
            original_path = sys.path.copy()
            try:
                with patch("importlib.util.find_spec", return_value=None), patch("builtins.input", return_value="n"):
                    init_project(directory=root)
                self.assertTrue((root / "main.py").is_file())
                self.assertFalse((root / "alembic").exists())
                self.assertEqual(sys.path, original_path)
            finally:
                sys.modules.pop("bafser_generator_settings", None)

    def test_explicit_target_bootstraps_config_then_scaffolds_dotted_packages(self):
        from bafser.scripts.init_project import init_project

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "target"
            with patch("importlib.util.find_spec", return_value=None):
                init_project(directory=root)
                self.assertEqual([path.name for path in root.iterdir()], ["bafser_config.py"])
                config = root / "bafser_config.py"
                config.write_text(
                    config.read_text(encoding="utf8")
                    + '\nblueprints_package = "project.routes"\ndata_tables_package = "project.models"\nuse_alembic = False\n',
                    encoding="utf8",
                )
                with patch("builtins.input", return_value="n"):
                    init_project(directory=root)
                    self.assertTrue((root / "project/models/user.py").is_file())
                    self.assertTrue((root / "project/routes/docs.py").is_file())
                    self.assertTrue((root / "project/__init__.py").is_file())
                    self.assertIn("from project.models", (root / "project/models/_roles.py").read_text(encoding="utf8"))
                    self.assertIn("/storage/secret_key_jwt.txt", (root / ".gitignore").read_text(encoding="utf8"))
                    entry = root / "main.py"
                    entry.write_text("# keep user changes\n", encoding="utf8")
                    init_project(directory=root)
                    self.assertEqual(entry.read_text(encoding="utf8"), "# keep user changes\n")
                    init_project(directory=root, force=True)
                    self.assertIn("create_app", entry.read_text(encoding="utf8"))


if __name__ == "__main__":
    unittest.main()
