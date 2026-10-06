"""CLI configuration checks using real SQLite migrations."""

import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


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
            + 'data_tables_folder = "data"\nmigrations_folder = "alembic"\n',
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

    def run_upgrade(self, *, db_path=None, console=False):
        environment = os.environ.copy()
        environment.pop("DBPATH", None)
        environment.pop("PYTHONPATH", None)
        environment.pop("PYTHON_DOTENV_DISABLED", None)
        if db_path is not None:
            environment["DBPATH"] = db_path
        if console:
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
        with sqlite3.connect(database) as connection:
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

    def test_missing_dotenv_allows_environment_configuration(self):
        self.assert_migrated(self.run_upgrade(db_path="environment.db"), "environment.db")

    def test_parent_directory_dotenv_is_not_loaded(self):
        (self.project.parent / ".env").write_text("DBPATH='parent.db'\n", encoding="utf8")
        result = self.run_upgrade()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("env var not set: DBPATH", result.stderr)
        self.assertFalse((self.project / "parent.db").exists())


if __name__ == "__main__":
    unittest.main()
