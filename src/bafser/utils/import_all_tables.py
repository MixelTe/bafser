import bafser_config

from .package_modules import iter_package_modules


def import_all_tables():
    from ..data import (  # noqa: F401 -- importing the models registers their SQLAlchemy tables
        db_state,  # type: ignore
        image,  # type: ignore
        log,  # type: ignore
        operation,  # type: ignore
        permission,  # type: ignore
        role,  # type: ignore
        user,  # type: ignore
        user_role,  # type: ignore
    )

    for _ in iter_package_modules(bafser_config.data_tables_package):
        pass
