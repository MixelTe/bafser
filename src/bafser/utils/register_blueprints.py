import importlib
import os
import bafser_config


def register_blueprints(app):
    for file in os.listdir(bafser_config.blueprints_folder):
        if not file.endswith(".py"):
            continue
        module = bafser_config.blueprints_folder + "." + file[:-3]
        blueprint = importlib.import_module(module).blueprint
        app.register_blueprint(blueprint)
