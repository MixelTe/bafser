"""Check the installed distribution without relying on the source checkout."""

import importlib
import importlib.metadata
import importlib.resources
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def check_console_projects(console: Path, resources, root: Path) -> None:
    unrelated = root / "unrelated"
    unrelated.mkdir()
    (unrelated / "bafser_config.py").write_text('raise RuntimeError("unrelated cwd config must not load")\n', encoding="utf8")
    target = root / "selected"
    command = [str(console), "init_project", "--directory", "../selected"]
    subprocess.run(command, cwd=unrelated, check=True, capture_output=True, text=True)
    if [path.name for path in target.iterdir()] != ["bafser_config.py"]:
        raise RuntimeError("The first init_project pass must only create the selected config")
    template = resources.joinpath("bafser_config.example.py").read_text(encoding="utf8")
    config_source = (
        "from __future__ import annotations\n" + template
        + "\nfrom dataclasses import dataclass\n"
        + "from project_settings import use_alembic\n"
        + "@dataclass\nclass ProjectSettings:\n    migrations: bool = use_alembic\n"
        + "use_alembic = ProjectSettings().migrations\n"
    )
    (target / "bafser_config.py").write_text(config_source, encoding="utf8")
    (target / "project_settings.py").write_text(
        'import os\nassert os.environ["BAFSER_ARTIFACT_TARGET"] == "selected"\nuse_alembic = False\n', encoding="utf8",
    )
    (target / ".env").write_text("BAFSER_ARTIFACT_TARGET=selected\n", encoding="utf8")
    environment = os.environ.copy()
    environment.pop("BAFSER_ARTIFACT_TARGET", None)
    environment.pop("PYTHON_DOTENV_DISABLED", None)
    subprocess.run(command, cwd=unrelated, env=environment, input="n\n", check=True, capture_output=True, text=True)
    if not (target / "main.py").is_file() or (target / "alembic").exists() or (unrelated / "main.py").exists():
        raise RuntimeError("The selected target config did not control scaffolding")
    environment["PYTHONPATH"] = os.pathsep.join((str(unrelated), str(target)))
    subprocess.run(command, cwd=unrelated, env=environment, input="n\n", check=True, capture_output=True, text=True)
    subprocess.run([str(console)], cwd=target, env=environment, check=True, capture_output=True, text=True)
    (target / "bafser_config.py").write_text("import bafser_artifact_missing_target_dependency\n", encoding="utf8")
    result = subprocess.run(command, cwd=unrelated, env=environment, capture_output=True, text=True)
    if result.returncode == 0 or "bafser_artifact_missing_target_dependency" not in result.stderr:
        raise RuntimeError("The console script swallowed a selected config error")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="bafser-artifact-") as directory:
        previous = Path.cwd()
        try:
            os.chdir(directory)
            previous_import_path = sys.path.copy()
            package = importlib.import_module("bafser")
            if sys.path != previous_import_path:
                raise RuntimeError("Importing bafser changed sys.path")
            distribution = importlib.metadata.distribution("bafser")
            installed_package = Path(distribution.locate_file("bafser")).resolve()
            if not Path(package.__file__).resolve().is_relative_to(installed_package):
                raise RuntimeError("The smoke check imported the source checkout")
            resources = importlib.resources.files("bafser")
            for name in ("py.typed", "templates/docs.html", "templates/dashboard.html"):
                if not resources.joinpath(name).is_file():
                    raise RuntimeError(f"Missing package resource: {name}")
            if list(Path(directory).iterdir()):
                raise RuntimeError("Importing bafser created files in an empty working directory")
            subprocess.run([sys.executable, "-m", "bafser"], check=True, cwd=directory)
            console = Path(sys.executable).with_name("bafser.exe" if os.name == "nt" else "bafser")
            subprocess.run([str(console)], check=True, cwd=directory)
            if list(Path(directory).iterdir()):
                raise RuntimeError("CLI help created files in an empty working directory")
            check_console_projects(console, resources, Path(directory))
        finally:
            os.chdir(previous)
    print("Installed package, resources, import/help and console project selection: OK")


if __name__ == "__main__":
    main()
