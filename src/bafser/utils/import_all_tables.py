import importlib
import os
import bfs_config


def import_all_tables():
    from ..data import image
    from ..data import log
    from ..data import operation
    from ..data import permission
    from ..data import role
    from ..data import user_role

    for file in os.listdir(bfs_config.data_tables_folder):
        if not file.endswith(".py"):
            continue
        module = bfs_config.data_tables_folder + "." + file[:-3]
        importlib.import_module(module)
