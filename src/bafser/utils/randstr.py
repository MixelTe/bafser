import string
from secrets import choice

letters = string.ascii_uppercase + string.digits


def randstr(N: int) -> str:
    """Generate an alphanumeric string using the operating system's CSPRNG."""
    return "".join(choice(letters) for _ in range(N))
