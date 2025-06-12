from datetime import datetime
from typing import Union

from sqlalchemy import Column, ForeignKey, Integer, orm
from sqlalchemy.orm import Session

from .. import SqlAlchemyBase
from ._tables import TablesBase


class UserRole(SqlAlchemyBase):
    __tablename__ = TablesBase.UserRole

    userId = Column(Integer, ForeignKey("User.id"), primary_key=True)
    roleId = Column(Integer, ForeignKey("Role.id"), primary_key=True)

    role = orm.relationship("Role")

    def __repr__(self):
        return f"<UserRole> user: {self.userId} role: {self.roleId}"

    def get_dict(self):
        return self.to_dict(only=("userId", "roleId"))

    @staticmethod
    def new(creator, userId: int, roleId: int, now: datetime = None, commit=True, db_sess: Session = None):
        from .. import Log
        db_sess = db_sess if db_sess else Session.object_session(creator)

        user_role = UserRole(userId=userId, roleId=roleId)
        db_sess.add(user_role)

        Log.added(user_role, creator, [
            ("userId", user_role.userId),
            ("roleId", user_role.roleId),
        ], now, commit, db_sess)
        return user_role

    @staticmethod
    def get(db_sess: Session, userId: int, roleId: int) -> Union["UserRole", None]:
        return db_sess.query(UserRole).filter(UserRole.userId == userId, UserRole.roleId == roleId).first()

    def delete(self, actor):
        from .. import Log
        db_sess = Session.object_session(self)
        db_sess.delete(self)
        Log.deleted(self, actor, [
            ("userId", self.userId),
            ("roleId", self.roleId),
        ])
