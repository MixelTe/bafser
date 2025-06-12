from sqlalchemy import Column, ForeignKey, Integer, String, orm

from .. import SqlAlchemyBase


class Permission(SqlAlchemyBase):
    __tablename__ = "Permission"

    roleId = Column(Integer, ForeignKey("Role.id"), primary_key=True)
    operationId = Column(String(32), ForeignKey("Operation.id"), primary_key=True)

    operation = orm.relationship("Operation")

    def __repr__(self):
        return f"<Permission> role: {self.roleId} oper: {self.operationId}"

    def get_dict(self):
        return self.to_dict(only=("roleId", "operationId"))
