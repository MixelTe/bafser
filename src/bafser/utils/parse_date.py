from datetime import date as calendar_date
from datetime import datetime, timezone


def parse_datetime(date: str) -> datetime | None:
    """Parse an ISO timestamp using the configured UTC or legacy behavior."""
    try:
        import bafser_config

        if getattr(bafser_config, "datetime_utc", False):
            parsed = datetime.fromisoformat(date[:-1] + "+00:00" if date.endswith("Z") else date)
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone(timezone.utc)
            return parsed.replace(tzinfo=None)
        if date[-1] == "Z":
            date = date[:-1]
        return datetime.fromisoformat(date)
    except Exception:
        return None


def parse_date(date: str) -> calendar_date | None:
    """Parse an ISO date or timestamp, discarding time without shifting its day."""
    try:
        return datetime.fromisoformat(date[:-1] + "+00:00" if date.endswith("Z") else date).date()
    except Exception:
        return None
