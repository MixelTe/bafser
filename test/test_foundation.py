"""Package discovery and process-owned engine contracts."""

import importlib
import os
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import sqlalchemy as sa
from flask import Flask

import bafser_config
from bafser import db_session
from bafser.utils.import_all_tables import import_all_tables
from bafser.utils.package_modules import iter_package_modules
from bafser.utils.register_blueprints import register_blueprints


class PackageDiscoveryTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.name = "bafser_discovery_" + uuid.uuid4().hex
        self.package = self.root / self.name
        self.package.mkdir()
        sys.path.insert(0, str(self.root))
        self.addCleanup(self.clear_modules)

    def clear_modules(self):
        sys.path.remove(str(self.root))
        for name in list(sys.modules):
            if name == self.name or name.startswith(self.name + "."):
                sys.modules.pop(name)
        importlib.invalidate_caches()

    def write(self, name, source):
        (self.package / name).write_text(source, encoding="utf8")

    def test_regular_package_imports_direct_modules_in_stable_order(self):
        self.write("__init__.py", "")
        self.write("zeta.py", "value = 2\n")
        self.write("alpha.py", "value = 1\n")
        modules = list(iter_package_modules(self.name))
        self.assertEqual([module.__name__ for module in modules], [self.name + ".alpha", self.name + ".zeta"])
        self.assertEqual([module.value for module in modules], [1, 2])

    def test_namespace_package_works_from_an_unrelated_working_directory(self):
        self.write("model.py", "value = 42\n")
        original = Path.cwd()
        other = self.root / "elsewhere"
        other.mkdir()
        try:
            os.chdir(other)
            self.assertEqual([module.value for module in iter_package_modules(self.name)], [42])
        finally:
            os.chdir(original)

    def test_internal_import_error_is_not_treated_as_disabled_package(self):
        self.write("broken.py", "import bafser_dependency_that_does_not_exist\n")
        with self.assertRaises(ModuleNotFoundError) as error:
            list(iter_package_modules(self.name))
        self.assertEqual(error.exception.name, "bafser_dependency_that_does_not_exist")

    def test_missing_package_and_plain_module_are_errors_but_none_is_explicit(self):
        self.assertEqual(list(iter_package_modules(None)), [])
        with self.assertRaises(ModuleNotFoundError):
            list(iter_package_modules(self.name + ".missing"))
        self.write("plain.py", "")
        with self.assertRaisesRegex(ValueError, "not a package"):
            list(iter_package_modules(self.name + ".plain"))

    def test_model_discovery_preserves_underscore_modules(self):
        self.write("_roles.py", "loaded = True\n")
        with patch.object(bafser_config, "data_tables_package", self.name):
            import_all_tables()
        self.assertTrue(sys.modules[self.name + "._roles"].loaded)

    def test_blueprint_aliases_private_modules_and_per_app_registration(self):
        self.write("__init__.py", "")
        self.write("first.py", 'from flask import Blueprint\nblueprint = Blueprint("first", __name__)\nbp = blueprint\n')
        self.write("second.py", 'from flask import Blueprint\nbp = Blueprint("second", __name__)\n')
        self.write("_helper.py", 'raise RuntimeError("helper must not be discovered")\n')
        with patch.object(bafser_config, "blueprints_package", self.name):
            for app in (Flask("first_app"), Flask("second_app")):
                register_blueprints(app)
                self.assertEqual(set(app.blueprints), {"first", "second"})

    def test_duplicate_blueprint_name_fails_before_partial_registration(self):
        self.write("a.py", 'from flask import Blueprint\nbp = Blueprint("duplicate", __name__)\n')
        self.write("b.py", 'from flask import Blueprint\nbp = Blueprint("duplicate", __name__)\n')
        app = Flask("duplicates")
        with patch.object(bafser_config, "blueprints_package", self.name):
            with self.assertRaisesRegex(ValueError, "Duplicate blueprint"):
                register_blueprints(app)
        self.assertEqual(app.blueprints, {})

    def test_conflicting_exports_and_non_blueprint_are_explicit_errors(self):
        self.write("routes.py", 'from flask import Blueprint\nbp = Blueprint("alias", __name__)\nblueprint = Blueprint("other", __name__)\n')
        with patch.object(bafser_config, "blueprints_package", self.name):
            with self.assertRaisesRegex(ValueError, "Conflicting blueprint"):
                register_blueprints(Flask("conflict"))
        module = sys.modules[self.name + ".routes"]
        module.blueprint = None
        module.bp = object()
        with patch.object(bafser_config, "blueprints_package", self.name):
            with self.assertRaisesRegex(ValueError, "Expected a Flask Blueprint"):
                register_blueprints(Flask("invalid"))


class EngineLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "database.db"
        db_session.dispose_engine()
        self.addCleanup(db_session.dispose_engine)
        config = patch.multiple(bafser_config, db_dev_path=str(self.path), db_path=str(self.path), db_mysql=False)
        config.start()
        self.addCleanup(config.stop)
        tables = patch.object(db_session, "import_all_tables")
        tables.start()
        self.addCleanup(tables.stop)

    def test_runtime_initialization_is_lazy_and_does_not_create_schema(self):
        with patch.object(db_session.SqlAlchemyBase.metadata, "create_all") as create:
            db_session.global_init(True)
            self.assertFalse(self.path.exists())
            create.assert_not_called()
            db_session.global_init(True, create_tables=True)
            create.assert_called_once_with(db_session.get_engine())

    def test_explicit_setup_after_lazy_runtime_creates_missing_sqlite_parent(self):
        path = self.path.parent / "missing" / "nested" / "database.db"
        metadata = sa.MetaData()
        sa.Table("setup_probe", metadata, sa.Column("id", sa.Integer, primary_key=True))
        with (
            patch.multiple(bafser_config, db_dev_path=str(path), db_path=str(path)),
            patch.object(db_session.SqlAlchemyBase, "metadata", metadata),
        ):
            db_session.global_init(True)
            engine = db_session.get_engine()
            self.assertFalse(path.parent.exists())
            db_session.global_init(True, create_tables=True)
            self.assertTrue(path.is_file())
            self.assertIs(db_session.get_engine(), engine)
            with engine.connect() as connection:
                self.assertEqual(connection.scalar(sa.text("PRAGMA foreign_keys")), 1)
                self.assertEqual(connection.scalar(sa.text("SELECT name FROM sqlite_master WHERE name='setup_probe'")), "setup_probe")
            db_session.global_init(True, create_tables=True)

    def test_mismatched_setup_does_not_prepare_another_database_directory(self):
        db_session.global_init(True)
        path = self.path.parent / "different" / "database.db"
        with patch.object(bafser_config, "db_dev_path", str(path)):
            with self.assertRaisesRegex(RuntimeError, "different settings"):
                db_session.global_init(True, create_tables=True)
        self.assertFalse(path.parent.exists())

    def test_sqlite_connection_hooks_do_not_affect_other_engines(self):
        db_session.global_init(True)
        unrelated = sa.create_engine("sqlite:///:memory:")
        try:
            with db_session.get_engine().connect() as connection:
                self.assertEqual(connection.scalar(sa.text("SELECT lower('ЁЖ')")), "ёж")
                self.assertEqual(connection.scalar(sa.text("PRAGMA foreign_keys")), 1)
            with unrelated.connect() as connection:
                self.assertEqual(connection.scalar(sa.text("SELECT lower('ЁЖ')")), "ЁЖ")
                self.assertEqual(connection.scalar(sa.text("PRAGMA foreign_keys")), 0)
        finally:
            unrelated.dispose()

    def test_reinitialization_requires_same_settings_or_explicit_dispose(self):
        db_session.global_init(True)
        engine = db_session.get_engine()
        db_session.global_init(True)
        self.assertIs(db_session.get_engine(), engine)
        with patch.object(bafser_config, "db_dev_path", str(self.path.with_name("other.db"))):
            with self.assertRaisesRegex(RuntimeError, "different settings"):
                db_session.global_init(True)
            db_session.dispose_engine()
            db_session.global_init(True)
            self.assertIsNot(db_session.get_engine(), engine)

    def test_pool_limits_bound_concurrent_connections(self):
        with patch.multiple(bafser_config, db_pool_size=1, db_max_overflow=0, db_pool_timeout=0.05, create=True):
            db_session.global_init(True)
        with db_session.get_engine().connect():
            with self.assertRaises(sa.exc.TimeoutError):
                db_session.get_engine().connect()

    def test_production_statement_errors_hide_values(self):
        db_session.global_init(False)
        with db_session.get_engine().connect() as connection:
            with self.assertRaises(sa.exc.StatementError) as error:
                connection.execute(sa.text("SELECT :value FROM missing_table"), {"value": "PRIVATE-value"})
        self.assertNotIn("PRIVATE-value", str(error.exception))
        self.assertTrue(db_session.get_engine().hide_parameters)

    def test_memory_sqlite_is_supported_without_queue_pool_options(self):
        with patch.object(bafser_config, "db_dev_path", ":memory:"):
            db_session.global_init(True)
        with db_session.create_session() as session:
            self.assertEqual(session.scalar(sa.text("SELECT 1")), 1)

    def test_use_before_initialization_has_clear_errors(self):
        with self.assertRaisesRegex(RuntimeError, "not initialized"):
            db_session.create_session()
        with self.assertRaisesRegex(RuntimeError, "not initialized"):
            db_session.get_engine()
