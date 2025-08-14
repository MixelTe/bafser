from typing import Any, Type, TypedDict

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from .. import SqlAlchemyBase
from ..utils import get_all_fields, get_all_values


class Operation(SqlAlchemyBase):
    __tablename__ = "Operation"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, unique=True)
    name: Mapped[str] = mapped_column(String(32))

    def __repr__(self):
        return f"<Operation> [{self.id}] {self.name}"

    def get_dict(self) -> "OperationDict":
        return self.to_dict(only=("id", "name"))  # type: ignore


class OperationDict(TypedDict):
    id: int
    name: str


class OperationsBase:
    @classmethod
    def get_all(cls) -> list[tuple[str, str]]:
        return list(get_all_values(cls()))

    def __init_subclass__(cls, **kwargs: Any):
        global _Operations
        for key, v in get_all_fields(cls()):
            if isinstance(v, tuple) and len(v) == 2 and isinstance(v[0], str) and isinstance(v[1], str):  # type: ignore
                pass
            else:
                raise Exception(f"[bafser] Wrong type of operation {key}: {type(v)} != tuple[str, str]")  # type: ignore
        _Operations = cls


_Operations: Type[OperationsBase] | None = None


def get_operations():
    if _Operations is None:
        raise Exception("[bafser] No class inherited from OperationsBase")
    return _Operations
