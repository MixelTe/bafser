"""Exercise explicit project selection before the package facade is imported."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock, patch


class ExplicitProjectBootstrapTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.cwd = self.root / "unrelated"
        self.cwd.mkdir()
        (self.cwd / "bafser_config.py").write_text('raise RuntimeError("unrelated config was loaded")\n', encoding="utf8")
        self.target = self.root / "target"
        self.environment = os.environ.copy()
        self.environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")

    def run_setup(self, *args):
        return subprocess.run(
            [sys.executable, "-c", "import sys; sys.path.remove(''); from bafser_cli import cli; cli()", "init_project", *args],
            cwd=self.cwd, env=self.environment, input="n\n", capture_output=True, text=True, timeout=30,
        )

    def test_selected_directory_ignores_unrelated_config_and_uses_its_env_and_siblings(self):
        result = self.run_setup("--directory", "../target")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual([path.name for path in self.target.iterdir()], ["bafser_config.py"])
        (self.target / ".env").write_text("BAFSER_CLI_TARGET=selected\n", encoding="utf8")
        self.environment.pop("BAFSER_CLI_TARGET", None)
        self.environment.pop("PYTHON_DOTENV_DISABLED", None)
        config = self.target / "bafser_config.py"
        config.write_text(config.read_text(encoding="utf8") + "\nfrom selected_settings import use_alembic\n", encoding="utf8")
        (self.target / "selected_settings.py").write_text(
            'import os\nassert os.environ["BAFSER_CLI_TARGET"] == "selected"\nuse_alembic = False\n', encoding="utf8",
        )
        result = self.run_setup("--directory=../target")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.target / "main.py").is_file())
        self.assertFalse((self.target / "alembic").exists())
        self.assertFalse((self.cwd / "main.py").exists())

    def test_selected_config_dependency_error_is_not_replaced_by_defaults(self):
        self.target.mkdir()
        source = "import bafser_selected_target_missing_dependency\n"
        config = self.target / "bafser_config.py"
        config.write_text(source, encoding="utf8")
        result = self.run_setup("--directory", str(self.target))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("bafser_selected_target_missing_dependency", result.stderr)
        self.assertNotIn("unrelated config was loaded", result.stderr)
        self.assertEqual(config.read_text(encoding="utf8"), source)
        self.assertFalse((self.target / "main.py").exists())

    def test_selected_directory_already_on_pythonpath_takes_precedence(self):
        self.target.mkdir()
        template = Path(__file__).resolve().parents[1] / "src/bafser/bafser_config.example.py"
        (self.target / "bafser_config.py").write_text(template.read_text(encoding="utf8") + "\nuse_alembic = False\n", encoding="utf8")
        self.environment["PYTHONPATH"] = os.pathsep.join((str(self.cwd), str(self.target), self.environment["PYTHONPATH"]))
        result = self.run_setup("--directory", str(self.target))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.target / "main.py").is_file())
        self.assertFalse((self.cwd / "main.py").exists())

    def test_dataclass_config_can_be_loaded_again_during_project_setup(self):
        self.target.mkdir()
        template = Path(__file__).resolve().parents[1] / "src/bafser/bafser_config.example.py"
        (self.target / "bafser_config.py").write_text(
            "from __future__ import annotations\n" + template.read_text(encoding="utf8")
            + "\nfrom dataclasses import dataclass\n"
            + "@dataclass\nclass ProjectSettings:\n    use_alembic: bool = False\n"
            + "use_alembic = ProjectSettings().use_alembic\n",
            encoding="utf8",
        )
        result = self.run_setup("--directory", str(self.target))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.target / "main.py").is_file())
        self.assertFalse((self.target / "alembic").exists())


class ImportLifecycleTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.unrelated = self.root / "unrelated"
        self.unrelated.mkdir()
        self.target = self.root / "target"
        self.target.mkdir()
        self.template = Path(__file__).resolve().parents[1] / "src/bafser/bafser_config.example.py"

    def test_cli_restores_full_import_path_arguments_and_cwd_after_success_or_error(self):
        from bafser_cli import cli

        import bafser.cli

        original_directory = Path.cwd()
        failure = RuntimeError("command failed")
        for error in (None, failure):
            with self.subTest(error=error):
                import_path = [str(self.unrelated), str(self.target), *sys.path]
                arguments = ["bafser", "init_project", "--directory", str(self.target)]

                def run_cli(error=error):
                    self.assertEqual(Path.cwd(), self.target)
                    self.assertEqual(sys.path[0], str(self.target))
                    sys.path[:] = ["command changed the import path"]
                    if error is not None:
                        raise error

                with patch.object(sys, "path", import_path.copy()), patch.object(sys, "argv", arguments):
                    with patch.object(bafser.cli, "cli", side_effect=run_cli):
                        if error is None:
                            cli()
                        else:
                            with self.assertRaises(RuntimeError) as raised:
                                cli()
                            self.assertIs(raised.exception, error)
                    self.assertEqual(sys.path, import_path)
                    self.assertIs(sys.argv, arguments)
                    self.assertEqual(Path.cwd(), original_directory)

    def test_direct_config_load_prioritizes_target_already_on_import_path(self):
        from bafser.scripts.init_project import _read_project_config

        module_name = "bafser_setup_priority_settings"
        (self.unrelated / (module_name + ".py")).write_text('raise RuntimeError("wrong settings")\n', encoding="utf8")
        (self.target / (module_name + ".py")).write_text("use_alembic = False\n", encoding="utf8")
        config_path = self.target / "bafser_config.py"
        config_path.write_text(self.template.read_text(encoding="utf8") + f"\nfrom {module_name} import use_alembic\n", encoding="utf8")
        import_path = [str(self.unrelated), str(self.target), *sys.path]
        try:
            with patch.object(sys, "path", import_path.copy()):
                config = _read_project_config(config_path)
                self.assertFalse(config.use_alembic)
                self.assertEqual(sys.path, import_path)
        finally:
            sys.modules.pop(module_name, None)

    def test_config_load_restores_temporary_module_and_import_path_on_success_or_error(self):
        from bafser.scripts.init_project import _read_project_config

        temporary_name = "_bafser_project_setup_config"
        source = (
            "from __future__ import annotations\n" + self.template.read_text(encoding="utf8")
            + "\nfrom dataclasses import dataclass\n"
            + "@dataclass\nclass ProjectSettings:\n    use_alembic: bool = False\n"
            + "use_alembic = ProjectSettings().use_alembic\n"
            + 'import sys\nassert vars(sys.modules[__name__]) is globals()\n'
            + 'sys.path.append("config changed the import path")\n'
        )
        absent = object()
        previous_module = ModuleType(temporary_name)
        config_path = self.target / "bafser_config.py"
        for previous in (absent, previous_module, None):
            for fail in (False, True):
                with self.subTest(previous=previous, fail=fail):
                    config_path.write_text(source + ('raise RuntimeError("config failed")\n' if fail else ""), encoding="utf8")
                    import_path = [str(self.unrelated), str(self.target), *sys.path]
                    with patch.dict(sys.modules), patch.object(sys, "path", import_path.copy()):
                        sys.modules.pop(temporary_name, None)
                        if previous is not absent:
                            sys.modules[temporary_name] = previous
                        if fail:
                            with self.assertRaisesRegex(RuntimeError, "^config failed$"):
                                _read_project_config(config_path)
                        else:
                            config = _read_project_config(config_path)
                            self.assertFalse(config.ProjectSettings().use_alembic)
                        self.assertIs(sys.modules.get(temporary_name, absent), previous)
                        self.assertEqual(sys.path, import_path)


class TelegramEntryTemplateTests(unittest.TestCase):
    def run_template(self, arguments, *, module_name="__main__"):
        from bafser.scripts.init_project import main_tgapi

        calls = []
        telegram = ModuleType("bafser_tgapi")
        for name in ("setup", "set_webhook", "run_long_polling"):
            setattr(telegram, name, Mock(side_effect=lambda *args, _name=name, **kwargs: calls.append(_name)))
        facade = ModuleType("bafser")
        facade.AppConfig = Mock()
        run = Mock(side_effect=lambda serve: calls.append(("run", serve)))
        facade.create_app = Mock(return_value=(object(), run))
        bot = ModuleType("bot.bot")
        bot.Bot = type("Bot", (), {})
        with patch.dict(sys.modules, {"bafser": facade, "bafser_tgapi": telegram, "bot": ModuleType("bot"), "bot.bot": bot}):
            with patch.object(sys, "argv", ["main.py", *arguments]), patch("dotenv.load_dotenv"):
                exec(compile(main_tgapi, "generated-main.py", "exec"), {"__name__": module_name, "__file__": __file__})
        return calls

    def test_setup_only_never_starts_polling_or_configures_webhooks(self):
        for arguments, module_name in (
            (["--setup"], "__main__"),
            (["--setup", "devServer"], "__main__"),
            (["--setup"], "project_main"),
        ):
            with self.subTest(arguments=arguments, module_name=module_name):
                self.assertEqual(self.run_template(arguments, module_name=module_name), ["setup", ("run", False)])

    def test_runtime_preserves_polling_and_webhook_modes(self):
        self.assertEqual(self.run_template([]), ["setup", ("run", False), "run_long_polling"])
        self.assertEqual(self.run_template([], module_name="project_main"), ["setup", ("run", False), "set_webhook"])
        self.assertEqual(self.run_template(["devServer"]), ["setup", "set_webhook", ("run", True)])


if __name__ == "__main__":
    unittest.main()
