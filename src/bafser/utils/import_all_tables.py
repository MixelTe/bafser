import importlib
import os
import bafser_config


def import_all_tables():
    from ..data import image
    from ..data import log
    from ..data import operation
    from ..data import permission
    from ..data import role
    from ..data import user_role

    if not os.path.exists(bafser_config.data_tables_folder):
        return

    data_tables_module = bafser_config.data_tables_folder.replace("/", ".").replace("\\", ".")
    for file in os.listdir(bafser_config.data_tables_folder):
        if not file.endswith(".py"):
            continue
        module = data_tables_module + "." + file[:-3]
        importlib.import_module(module)
