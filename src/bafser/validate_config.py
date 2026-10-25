"""Validate the base configuration before importing configuration consumers."""

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
        "blueprints_folder",
        "data_tables_folder",
    )
    bool_fields = ("db_mysql", "sql_echo", "datetime_utc", "use_alembic")
    bool_none_fields = ("allow_unsupported_for_update_clause",)
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

    if errors:
        raise ValueError("Invalid bafser_config:\n" + "\n".join(f"- {error}" for error in errors))
