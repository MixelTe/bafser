import importlib
import os
import bfs_config


def register_blueprints(app):
    for file in os.listdir(bfs_config.blueprints_folder):
        if not file.endswith(".py"):
            continue
        module = bfs_config.blueprints_folder + "." + file[:-3]
        blueprint = importlib.import_module(module).blueprint
        app.register_blueprint(blueprint)
