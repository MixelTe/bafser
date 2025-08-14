from typing import Any, Type

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from .. import SqlAlchemyBase
from ..utils import get_all_values


class Operation(SqlAlchemyBase):
    __tablename__ = "Operation"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, unique=True)
    name: Mapped[str] = mapped_column(String(32))

    def __repr__(self):
        return f"<Operation> [{self.id}] {self.name}"

    def get_dict(self):
        return self.to_dict(only=("id", "name"))


class OperationsBase:
    @classmethod
    def get_all(cls):
        return list(get_all_values(cls()))

    def __init_subclass__(cls, **kwargs: Any):
        global _Operations
        # TODO check all for correct type
        _Operations = cls


_Operations: Type[OperationsBase] | None = None


def get_operations():
    if _Operations is None:
        raise Exception("[bafser] No class inherited from OperationsBase")
    return _Operations
