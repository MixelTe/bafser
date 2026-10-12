from datetime import datetime, timedelta, timezone


def get_datetime_utc() -> datetime:
    """Return the current instant with an explicit UTC timezone."""
    return datetime.now(timezone.utc)


def get_datetime_now() -> datetime:
    import bafser_config

    now = get_datetime_utc()
    return now if getattr(bafser_config, "datetime_utc", False) else now + timedelta(hours=3)
