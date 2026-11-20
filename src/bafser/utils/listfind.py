from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


def listfind(lst: list[T], fn: Callable[[T], bool]) -> T | None:
    for el in lst:
        if fn(el):
            return el
    return None
