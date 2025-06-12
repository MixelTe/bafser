import os


def create_folder_for_file(fpath: str):
    dirname = os.path.dirname(fpath)
    if dirname != "":
        os.makedirs(dirname, exist_ok=True)
