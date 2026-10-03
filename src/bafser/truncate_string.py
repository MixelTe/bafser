from typing import Any

from sqlalchemy import String
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator


class TruncateString(TypeDecorator[str]):
    """Store at most ``length`` characters in a string column."""

    impl = String
    cache_ok = True

    def __init__(self, length: int, **kwargs: Any):
        if length < 1:
            raise ValueError("TruncateString length must be positive")
        super().__init__(length=length, **kwargs)

    def process_bind_param(self, value: str | None, dialect: Dialect) -> str | None:
        if value is None:
            return None
        return value[: self.impl.length]  # type: ignore
