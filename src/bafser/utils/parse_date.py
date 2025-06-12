from datetime import datetime


def parse_date(date: str):
    try:
        if date[-1] == "Z":
            date = date[:-1]
        return datetime.fromisoformat(date), True
    except Exception:
        return None, False
