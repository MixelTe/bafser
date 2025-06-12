import string
from random import choices

letters = string.ascii_uppercase + string.digits


def randstr(N: int):
    return ''.join(choices(letters, k=N))
