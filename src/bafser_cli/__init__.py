"""Prepare the explicit CLI lifecycle before importing the library facade."""

import argparse
import os
import sys
from pathlib import Path


def parse_init_project_args(args: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="bafser init_project")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--directory", type=Path)
    return parser.parse_args(args)


def cli() -> None:
    from dotenv import load_dotenv

    previous_directory = Path.cwd()
    previous_arguments = sys.argv
    project_directory = previous_directory.resolve()
    if len(sys.argv) > 1 and sys.argv[1] == "init_project":
        options = parse_init_project_args(sys.argv[2:])
        if options.directory is not None:
            project_directory = options.directory.resolve()
            project_directory.mkdir(parents=True, exist_ok=True)
            sys.argv = [sys.argv[0], "init_project", "--directory", str(project_directory)]
            if options.force:
                sys.argv.append("--force")

    previous_import_path = sys.path.copy()
    sys.path.insert(0, str(project_directory))
    try:
        os.chdir(project_directory)
        load_dotenv(project_directory / ".env", override=False)
        from bafser.cli import cli as run_cli

        run_cli()
    finally:
        os.chdir(previous_directory)
        sys.argv = previous_arguments
        sys.path[:] = previous_import_path
