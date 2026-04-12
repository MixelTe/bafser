import os


def get_db_path(path: str):
    if not path.startswith("ENV:"):
        return path
    path = path[len("ENV:"):]
    v = os.environ.get(path)
    if v is None:
        raise Exception(f"env var not set: {path}")
    return v
