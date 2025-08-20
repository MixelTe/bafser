from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .. import SqlAlchemyBase
from ._tables import TablesBase
from .operation import Operation


class Permission(SqlAlchemyBase):
    __tablename__ = "Permission"

    roleId: Mapped[int] = mapped_column(ForeignKey(f"{TablesBase.Role}.id"), primary_key=True)
    operationId: Mapped[str] = mapped_column(String(32), ForeignKey("Operation.id"), primary_key=True)

    operation: Mapped[Operation] = relationship(init=False)

    def __repr__(self):
        return f"<Permission> role: {self.roleId} oper: {self.operationId}"
