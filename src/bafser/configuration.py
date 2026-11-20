"""Load project configuration without creating files or changing import paths."""

import importlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType


def load_config() -> ModuleType:
    """Use the project module, or in-memory defaults for explicit project setup.

    The explicit CLI bootstrap prepares project imports before loading the
    facade. Library loading can find a config by its cwd path without changing
    sys.path. Errors raised by configuration and its dependencies are never
    replaced by defaults.
    """
    try:
        return importlib.import_module("bafser_config")
    except ModuleNotFoundError as error:
        if error.name != "bafser_config":
            raise

    project_path = Path.cwd() / "bafser_config.py"
    if project_path.is_file():
        spec = importlib.util.spec_from_file_location("bafser_config", project_path)
        if spec is None or spec.loader is None:
            raise ImportError("Could not load bafser_config.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules["bafser_config"] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            sys.modules.pop("bafser_config", None)
            raise
        return module

    module = ModuleType("bafser_config")
    module.__file__ = str(project_path)
    template = Path(__file__).with_name("bafser_config.example.py")
    exec(compile(template.read_text(encoding="utf8"), str(template), "exec"), vars(module))
    module.__bafser_defaults__ = True  # pyright: ignore[reportAttributeAccessIssue]
    sys.modules["bafser_config"] = module
    return module
