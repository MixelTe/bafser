import os
import secrets
import tempfile

from .create_folder_for_file import create_folder_for_file


def get_secret_key_rnd(path: str) -> str:
    """Read an existing key or atomically publish a new 256-bit bootstrap key.

    The destination filesystem must support hard links (for example POSIX or
    NTFS). A completed private temporary file is linked without replacing an
    existing destination, so concurrent callers all receive the same ready key.
    Runtime startup should use get_secret_key instead of generating a key.
    """
    try:
        return get_secret_key(path)
    except FileNotFoundError:
        pass

    create_folder_for_file(path)
    destination = os.path.abspath(path)
    directory = os.path.dirname(destination)
    key = secrets.token_hex(32)
    file_descriptor, temporary_path = tempfile.mkstemp(prefix=f".{os.path.basename(destination)}.", dir=directory)
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf8") as file:
            file.write(key)
            file.flush()
            os.fsync(file.fileno())
        try:
            os.link(temporary_path, destination)
        except FileExistsError:
            return get_secret_key(destination)
        except OSError as error:
            raise OSError("Cannot atomically create secret key: the destination filesystem must support hard links") from error
        return key
    finally:
        os.unlink(temporary_path)


def get_secret_key(path: str) -> str:
    """Read a nonempty UTF-8 key verbatim; never create or replace it."""
    try:
        with open(path, "r", encoding="utf8", newline="") as f:
            key = f.read()
    except UnicodeDecodeError:
        raise ValueError("Secret key file must contain UTF-8 text") from None
    if not key.strip():
        raise ValueError("Secret key file must not be empty")
    return key
