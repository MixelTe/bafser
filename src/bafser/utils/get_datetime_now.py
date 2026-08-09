from datetime import UTC, datetime, timedelta


def get_datetime_now():
    return datetime.now(UTC) + timedelta(hours=3)
