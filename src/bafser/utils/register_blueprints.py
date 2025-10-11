import importlib
import os

from flask import Flask

import bafser_config


def register_blueprints(app: Flask):
    if not os.path.exists(bafser_config.blueprints_folder):
        return

    blueprints_module = bafser_config.blueprints_folder.replace("/", ".").replace("\\", ".")
    for file in os.listdir(bafser_config.blueprints_folder):
        if not file.endswith(".py"):
            continue
        module_name = blueprints_module + "." + file[:-3]
        module = importlib.import_module(module_name)
        blueprint = module.blueprint if hasattr(module, "blueprint") else module.bp
        app.register_blueprint(blueprint)
