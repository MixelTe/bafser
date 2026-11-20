"""Application setup and runtime remain separate without losing simple startup."""

import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock, Mock, call, patch

from flask import current_app, has_app_context

import bafser_config
from bafser import AppConfig, create_app, get_db_session


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        directory = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.root = Path(directory)
        self.key = self.root / "keys" / "jwt.key"
        self.images = self.root / "images"
        self.stack.enter_context(patch.multiple(
            bafser_config,
            jwt_key_file_path=str(self.key),
            images_folder=str(self.images),
            use_alembic=True,
            allow_unsupported_for_update_clause=None,
        ))
        self.stack.enter_context(patch.object(sys, "argv", ["lifecycle-test"]))
        self.stack.enter_context(patch("bafser.app._config", None))
        self.logging = self.stack.enter_context(patch("bafser.app.setLogging"))
        self.stack.enter_context(patch("bafser.app.get_logger_requests", return_value=Mock()))
        self.stack.enter_context(patch("bafser.app.get_logger_dashboard", return_value=Mock()))
        self.stack.enter_context(patch("bafser.app.register_blueprints"))
        self.stack.enter_context(patch("bafser.app.init_api_docs"))
        self.engine_init = self.stack.enter_context(patch("bafser.db_session.global_init"))
        self.alembic = self.stack.enter_context(patch("bafser.app.alembic_upgrade"))
        self.session = MagicMock(name="setup_session")
        self.session.__enter__.return_value = self.session
        self.create_session = self.stack.enter_context(patch("bafser.db_session.create_session", return_value=self.session))
        self.is_initialized = self.stack.enter_context(patch("bafser.data.db_state.DBState.is_initialized", return_value=False))
        self.mark_initialized = self.stack.enter_context(patch("bafser.data.db_state.DBState.mark_as_initialized"))
        self.sync_roles = self.stack.enter_context(patch("bafser.Role.update_roles_permissions"))
        self.create_admin = self.stack.enter_context(patch("bafser.UserBase._create_admin"))
        user_table = Mock()
        user_table.get_by_login.return_value = None
        self.stack.enter_context(patch("bafser.data.user.get_user_table", return_value=user_table))

    def prepare_runtime_files(self):
        self.key.parent.mkdir()
        self.key.write_text("existing-runtime-key", encoding="utf8")
        self.images.mkdir()

    def test_runtime_neither_initializes_database_nor_creates_keys_or_directories(self):
        self.prepare_runtime_files()
        for alembic in (True, False):
            with self.subTest(use_alembic=alembic), patch.object(bafser_config, "use_alembic", alembic):
                self.engine_init.reset_mock()
                with (
                    patch("bafser.app.get_secret_key_rnd", side_effect=AssertionError("runtime generated a key")),
                    patch("bafser.app.os.makedirs", side_effect=AssertionError("runtime created a directory")),
                    patch("bafser.db_session.SqlAlchemyBase.metadata.create_all") as create_tables,
                ):
                    app, run = create_app(__name__, AppConfig(AUTO_SETUP=False, MULTIPROCESS_LOGGING=True))
                    run(False)
                self.assertEqual(app.config["JWT_SECRET_KEY"], "existing-runtime-key")
                self.engine_init.assert_called_once_with(False)
                create_tables.assert_not_called()
        self.alembic.assert_not_called()
        self.create_session.assert_not_called()
        self.sync_roles.assert_not_called()
        self.create_admin.assert_not_called()
        self.session.commit.assert_not_called()

    def test_runtime_missing_key_fails_without_creating_any_files(self):
        self.images.mkdir()
        before = set(self.root.rglob("*"))
        with self.assertRaises(FileNotFoundError):
            create_app(__name__, AppConfig(AUTO_SETUP=False))
        self.assertEqual(set(self.root.rglob("*")), before)
        self.engine_init.assert_not_called()

    def test_runtime_missing_data_directory_is_not_created(self):
        self.key.parent.mkdir()
        self.key.write_text("existing-runtime-key", encoding="utf8")
        with self.assertRaisesRegex(FileNotFoundError, "configured data directory"):
            create_app(__name__, AppConfig(AUTO_SETUP=False))
        self.assertFalse(self.images.exists())

    def test_explicit_setup_bootstraps_even_with_auto_setup_disabled_and_never_starts_server(self):
        for use_alembic in (True, False):
            with self.subTest(use_alembic=use_alembic):
                self.engine_init.reset_mock()
                self.alembic.reset_mock()
                self.session.commit.reset_mock()
                with patch.object(sys, "argv", ["application", "--setup"]), patch.object(bafser_config, "use_alembic", use_alembic):
                    app, run = create_app(__name__, AppConfig(AUTO_SETUP=False))
                    with patch.object(app, "run") as server:
                        run(True)
                server.assert_not_called()
                self.assertTrue(self.key.is_file())
                self.assertTrue(self.images.is_dir())
                self.assertEqual(app.config["JWT_SECRET_KEY"], self.key.read_text(encoding="utf8"))
                self.assertIn(call(False, create_tables=not use_alembic), self.engine_init.call_args_list)
                self.session.commit.assert_called_once_with()
                if use_alembic:
                    self.alembic.assert_called_once_with(False)
                else:
                    self.alembic.assert_not_called()

    def test_default_simple_startup_seeds_once_and_owns_one_commit(self):
        init = Mock()
        seed = Mock()
        app, run = create_app(__name__, AppConfig(DEV_MODE=True))
        with patch.object(app, "run") as server:
            run(True, init_db=init, init_dev_values=seed, host="127.0.0.2", port=5010)
        server.assert_called_once_with(debug=True, port=5010, host="127.0.0.2")
        self.assertTrue(self.key.is_file())
        self.assertTrue(self.images.is_dir())
        self.is_initialized.assert_called_once_with(self.session, commit=False)
        self.sync_roles.assert_called_once_with(self.session, commit=False)
        self.create_admin.assert_called_once_with(self.session, commit=False)
        self.mark_initialized.assert_called_once_with(self.session, commit=False)
        init.assert_called_once_with(self.session, app.extensions["bafser_config"])
        seed.assert_called_once_with(self.session, app.extensions["bafser_config"])
        self.session.commit.assert_called_once_with()

    def test_initialized_database_does_not_repeat_seed_or_admin_creation(self):
        self.is_initialized.return_value = True
        init = Mock()
        seed = Mock()
        _, run = create_app(__name__, AppConfig(DEV_MODE=True))
        run(False, init_db=init, init_dev_values=seed)
        self.sync_roles.assert_called_once_with(self.session, commit=False)
        init.assert_not_called()
        seed.assert_not_called()
        self.create_admin.assert_not_called()
        self.mark_initialized.assert_not_called()
        self.session.commit.assert_called_once_with()

    def test_setup_callback_uses_app_context_and_the_owned_session(self):
        observed = []

        def init(session, config):
            observed.append((has_app_context(), current_app.config["EXAMPLE"], get_db_session() is session))

        app, run = create_app(__name__, AppConfig().add("EXAMPLE", "configured"))
        run(False, init_db=init)
        self.assertEqual(observed, [(True, "configured", True)])
        self.assertIs(app.extensions["bafser_config"].AUTO_SETUP, True)

    def test_seed_failure_does_not_mark_initialized_or_commit(self):
        _, run = create_app(__name__, AppConfig(DEV_MODE=True))
        with self.assertRaisesRegex(ValueError, "seed failed"):
            run(False, init_db=Mock(side_effect=ValueError("seed failed")))
        self.mark_initialized.assert_not_called()
        self.session.commit.assert_not_called()

    def test_root_logger_setting_is_forwarded_independently(self):
        self.prepare_runtime_files()
        for configure_root in (True, False):
            with self.subTest(configure_root=configure_root):
                self.logging.reset_mock()
                create_app(__name__, AppConfig(AUTO_SETUP=False, CONFIGURE_ROOT_LOGGING=configure_root))
                self.logging.assert_called_once_with(configure_root=configure_root)

    def test_extra_secret_runtime_loading_is_also_strict(self):
        extra = self.root / "missing" / "api.key"
        with self.assertRaises(FileNotFoundError):
            AppConfig(AUTO_SETUP=False).add_secret_key_rnd("API_SECRET", str(extra))
        self.assertFalse(extra.parent.exists())
