import os

from flask import make_response, send_file


def create_file_response(fpath: str, ftype: str, fname: str, as_attachment: bool = False, *, cache_control: str = "private, no-store"):
    """Serve a private, non-stored file unless the caller explicitly sets a cache policy."""
    if not os.path.exists(fpath):
        return make_response("", 404)
    response = send_file(fpath, download_name=fname, as_attachment=as_attachment)
    response.headers.set("Content-Type", ftype)
    response.headers.set("Cache-Control", cache_control)
    return response
