from datetime import datetime, timezone


def parse_date(date: str):
    try:
        import bafser_config

        if getattr(bafser_config, "datetime_utc", False):
            parsed = datetime.fromisoformat(date[:-1] + "+00:00" if date.endswith("Z") else date)
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone(timezone.utc)
            return parsed.replace(tzinfo=None), True
        if date[-1] == "Z":
            date = date[:-1]
        return datetime.fromisoformat(date), True
    except Exception:
        return None, False
