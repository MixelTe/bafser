from typing import TypeGuard, TypeVar

_T = TypeVar("_T")
_K = TypeVar("_K")


class UndefinedMeta(type):
    def __repr__(cls):
        return "Undefined"


class Undefined(metaclass=UndefinedMeta):
    """A shared class sentinel for an omitted value."""

    T = type["Undefined"]

    def __init__(self):
        raise Exception("bafser: Undefined cant be instantiated")

    @staticmethod
    def cast(v: "_T | type[Undefined]") -> "_T":
        """Remove Undefined from type hint."""
        return v  # type: ignore

    @staticmethod
    def defined(v: "_T | type[Undefined]") -> "TypeGuard[_T]":
        """Return true if value is not Undefined."""
        return v is not Undefined

    @staticmethod
    def default(v: "_T | type[Undefined]", default: "_K" = None) -> "_T | _K":
        """Return default if value is Undefined."""
        if v is Undefined:
            return default
        return Undefined.cast(v)


U = Undefined
UD = Undefined.default
