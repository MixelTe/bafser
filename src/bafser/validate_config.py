"""Validate the base configuration before importing configuration consumers."""

import keyword
import math
from types import ModuleType


def validate_config(config: ModuleType | None = None) -> None:
    """Raise ValueError for missing or invalid base settings, without exposing values.

    Extra project settings are allowed. Environment values and filesystem state
    are checked by their consumers, after application/CLI initialization.
    """
    if config is None:
        import bafser_config

        config = bafser_config

    errors: list[str] = []
    string_fields = (
        "db_dev_path",
        "db_path",
        "migrations_folder",
        "log_info_path",
        "log_requests_path",
        "log_errors_path",
        "log_frontend_path",
        "log_dashboard_path",
        "jwt_key_file_path",
        "images_folder",
        "login_page_url",
        "api_url",
    )
    bool_fields = ("db_mysql", "sql_echo", "datetime_utc", "use_alembic")
    bool_none_fields = ("allow_unsupported_for_update_clause",)
    for old_name in ("blueprints_folder", "data_tables_folder"):
        if hasattr(config, old_name):
            errors.append(f"{old_name}: replaced by {old_name.removesuffix('_folder')}_package")
    for name in (*string_fields, *bool_fields, *bool_none_fields):
        if not hasattr(config, name):
            errors.append(f"{name}: required field is missing")
            continue
        value = getattr(config, name)
        if name in string_fields:
            if not isinstance(value, str):
                errors.append(f"{name}: expected str")
            elif "\0" in value:
                errors.append(f"{name}: must not contain NUL characters")
            elif name == "db_path" and value == "" and getattr(config, "db_mysql", None) is True:
                # MySQL credentials can come entirely from DB_* environment settings.
                pass
            elif not value.strip():
                errors.append(f"{name}: expected a non-empty string")
            elif name in ("db_dev_path", "db_path") and value.startswith("ENV:") and not value[4:].strip():
                errors.append(f"{name}: ENV: requires a variable name")
            elif name == "api_url" and (not value.startswith("/") or "?" in value or "#" in value):
                errors.append(f"{name}: expected a URL path prefix starting with /, without query or fragment")
        elif name in bool_fields:
            if type(value) is not bool:
                errors.append(f"{name}: expected bool")
        elif name in bool_none_fields:
            if value is not None and type(value) is not bool:
                errors.append(f"{name}: expected bool or None")
        else:
            raise ValueError("validate_config is broken")

    for name in ("blueprints_package", "data_tables_package"):
        if not hasattr(config, name):
            errors.append(f"{name}: required field is missing")
            continue
        value = getattr(config, name)
        if value is not None and (
            not isinstance(value, str) or not value or any(not part.isidentifier() or keyword.iskeyword(part) for part in value.split("."))
        ):
            errors.append(f"{name}: expected an absolute Python package name or None")

    optional_numbers = {
        "db_pool_size": (1, True),
        "db_max_overflow": (0, True),
        "db_pool_timeout": (0, False),
        "db_pool_recycle": (-1, True),
        "db_connect_timeout": (0, False),
        "db_read_timeout": (0, False),
        "db_write_timeout": (0, False),
    }
    for name, (minimum, integer) in optional_numbers.items():
        if not hasattr(config, name):
            continue
        value = getattr(config, name)
        if isinstance(value, bool) or not isinstance(value, int if integer else (int, float)):
            errors.append(f"{name}: expected {'int' if integer else 'number'}")
        elif (isinstance(value, float) and not math.isfinite(value)) or value < minimum or (minimum == 0 and not integer and value == 0):
            errors.append(f"{name}: invalid numeric limit")
    if (
        hasattr(config, "db_hide_parameters")
        and getattr(config, "db_hide_parameters") is not None
        and type(getattr(config, "db_hide_parameters")) is not bool
    ):
        errors.append("db_hide_parameters: expected bool or None")

    if errors:
        raise ValueError("Invalid bafser_config:\n" + "\n".join(f"- {error}" for error in errors))
