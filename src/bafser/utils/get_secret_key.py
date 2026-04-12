import os
import uuid


def get_secret_key_rnd(path):
    if os.path.exists(path):
        with open(path, "r", encoding="utf8") as f:
            return f.read()
    else:
        from bafser import create_folder_for_file

        create_folder_for_file(path)
        with open(path, "w", encoding="utf8") as f:
            key = str(uuid.uuid4())
            f.write(key)
            return key


def get_secret_key(path):
    if os.path.exists(path):
        with open(path, "r", encoding="utf8") as f:
            return f.read()
    else:
        raise Exception(f"Secret key not found! [{path}]")
