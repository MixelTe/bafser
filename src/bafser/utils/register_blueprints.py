import importlib
import os
import bafser_config


def register_blueprints(app):
    if not os.path.exists(bafser_config.blueprints_folder):
        return

    blueprints_module = bafser_config.blueprints_folder.replace("/", ".").replace("\\", ".")
    for file in os.listdir(bafser_config.blueprints_folder):
        if not file.endswith(".py"):
            continue
        module = blueprints_module + "." + file[:-3]
        blueprint = importlib.import_module(module).blueprint
        app.register_blueprint(blueprint)
