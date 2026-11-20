from flask import Blueprint, Flask

import bafser_config

from .package_modules import iter_package_modules


def register_blueprints(app: Flask):
    blueprints: list[Blueprint] = []
    names = set(app.blueprints)
    for module in iter_package_modules(bafser_config.blueprints_package, skip_private=True):
        blueprint = getattr(module, "blueprint", None)
        alias = getattr(module, "bp", None)
        if blueprint is not None and alias is not None and blueprint is not alias:
            raise ValueError(f"Conflicting blueprint and bp in {module.__name__}")
        blueprint = blueprint if blueprint is not None else alias
        if not isinstance(blueprint, Blueprint):
            raise ValueError(f"Expected a Flask Blueprint named blueprint or bp in {module.__name__}")
        if blueprint.name in names:
            raise ValueError(f"Duplicate blueprint name: {blueprint.name}")
        names.add(blueprint.name)
        blueprints.append(blueprint)
    for blueprint in blueprints:
        app.register_blueprint(blueprint)
