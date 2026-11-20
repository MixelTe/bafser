"""Discover direct modules through Python's package import protocol."""

import importlib
import pkgutil
from collections.abc import Iterator
from types import ModuleType


def iter_package_modules(package_name: str | None, *, skip_private: bool = False) -> Iterator[ModuleType]:
    if package_name is None:
        return
    package = importlib.import_module(package_name)
    package_path = getattr(package, "__path__", None)
    if package_path is None:
        raise ValueError(f"Configured module is not a package: {package_name}")
    modules = sorted(pkgutil.iter_modules(package_path, package.__name__ + "."), key=lambda item: item.name)
    for module in modules:
        name = module.name.rsplit(".", 1)[-1]
        if skip_private and name.startswith("_"):
            continue
        yield importlib.import_module(module.name)
