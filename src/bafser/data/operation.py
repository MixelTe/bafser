from typing import Generator, Type

from sqlalchemy import Column, String

from .. import SqlAlchemyBase
from ..utils import get_all_values


class Operation(SqlAlchemyBase):
    __tablename__ = "Operation"

    id = Column(String(32), primary_key=True, unique=True)
    name = Column(String(32), nullable=False)

    def __repr__(self):
        return f"<Operation> [{self.id}] {self.name}"

    def get_dict(self):
        return self.to_dict(only=("id", "name"))


class OperationsBase:
    @classmethod
    def get_all(cls) -> Generator[tuple[str, str], None, None]:
        return get_all_values(cls())

    def __init_subclass__(cls, **kwargs):
        global Operations
        Operations = cls


Operations: Type[OperationsBase] = None


def get_operations():
    if Operations is None:
        raise Exception("[bafser] No class inherited from OperationsBase")
    return Operations
