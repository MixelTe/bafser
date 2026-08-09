import importlib
import os

import bafser_config


def import_all_tables():
    from ..data import (
        db_state,  # type: ignore
        image,  # type: ignore
        log,  # type: ignore
        operation,  # type: ignore
        permission,  # type: ignore
        role,  # type: ignore
        user,  # type: ignore
        user_role,  # type: ignore
    )

    if not os.path.exists(bafser_config.data_tables_folder):
        return

    data_tables_module = bafser_config.data_tables_folder.replace("/", ".").replace("\\", ".")
    for file in os.listdir(bafser_config.data_tables_folder):
        if not file.endswith(".py"):
            continue
        module = data_tables_module + "." + file[:-3]
        importlib.import_module(module)
