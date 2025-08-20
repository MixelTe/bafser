from typing import Callable, TypeVar


T = TypeVar("T")


def listfind(l: list[T], fn: Callable[[T], bool]) -> T | None:
    for el in l:
        if fn(el):
            return el
    return None
