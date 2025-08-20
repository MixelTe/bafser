from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Session, Mapped, mapped_column, relationship

from .. import SqlAlchemyBase
from ._tables import TablesBase
if TYPE_CHECKING:
    from .. import Role, UserBase


class UserRole(SqlAlchemyBase):
    __tablename__ = TablesBase.UserRole

    userId: Mapped[int] = mapped_column(ForeignKey(f"{TablesBase.User}.id"), primary_key=True)
    roleId: Mapped[int] = mapped_column(ForeignKey(f"{TablesBase.Role}.id"), primary_key=True)

    role: Mapped["Role"] = relationship(lazy="joined", init=False)

    def __repr__(self):
        return f"<UserRole> user: {self.userId} role: {self.roleId}"

    @staticmethod
    def new(creator: "UserBase", userId: int, roleId: int, now: datetime | None = None, commit: bool = True, db_sess: Session | None = None):
        from .. import Log
        db_sess = db_sess if db_sess else Session.object_session(creator)
        assert db_sess

        user_role = UserRole(userId=userId, roleId=roleId)
        db_sess.add(user_role)

        Log.added(user_role, creator, [
            ("userId", user_role.userId),
            ("roleId", user_role.roleId),
        ], now, commit, db_sess)
        return user_role

    @staticmethod
    def get(db_sess: Session, userId: int, roleId: int) -> "UserRole | None":
        return db_sess.query(UserRole).filter(UserRole.userId == userId, UserRole.roleId == roleId).first()

    def delete(self, actor: "UserBase"):
        from .. import Log
        db_sess = Session.object_session(self)
        assert db_sess
        db_sess.delete(self)
        Log.deleted(self, actor, [
            ("userId", self.userId),
            ("roleId", self.roleId),
        ])
