from datetime import datetime, timedelta, timezone


def get_datetime_now():
    return datetime.now(timezone.utc) + timedelta(hours=3)
