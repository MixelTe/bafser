from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from .. import SqlAlchemyBase
from ._tables import TablesBase

if TYPE_CHECKING:
    from .. import Role, UserBase


class UserRole(SqlAlchemyBase):
    """Low-level membership rows.

    Concurrent standalone new/delete calls must first lock the parent User row,
    as UserBase.add_role/remove_role/set_roles do. These primitives do not choose
    a multi-row locking order or synchronize an already loaded User.roles cache.
    """

    __tablename__ = TablesBase.UserRole

    userId: Mapped[int] = mapped_column(ForeignKey(f"{TablesBase.User}.id"), primary_key=True)
    roleId: Mapped[int] = mapped_column(ForeignKey(f"{TablesBase.Role}.id"), primary_key=True)

    role: Mapped["Role"] = relationship(lazy="joined", init=False)

    def __repr__(self):
        return f"<UserRole> user: {self.userId} role: {self.roleId}"

    @staticmethod
    def new(creator: "UserBase | None", userId: int, roleId: int, now: datetime | None = None, commit: bool = True, db_sess: Session | None = None):
        from .. import Log, get_db_session

        if db_sess is None:
            db_sess = creator.db_sess if creator is not None else get_db_session()

        user_role = UserRole(userId=userId, roleId=roleId)
        db_sess.add(user_role)

        Log.added(
            user_role,
            creator,
            [
                ("userId", user_role.userId),
                ("roleId", user_role.roleId),
            ],
            now,
            False,
            db_sess,
        )
        if commit:
            db_sess.commit()
        return user_role

    @staticmethod
    def get(db_sess: Session, userId: int, roleId: int) -> "UserRole | None":
        return db_sess.query(UserRole).filter(UserRole.userId == userId, UserRole.roleId == roleId).first()

    def delete(self, actor: "UserBase | None", *, now: datetime | None = None, commit: bool = True, db_sess: Session | None = None):
        from .. import Log

        db_sess = self._get_write_session(db_sess)
        db_sess.delete(self)
        Log.deleted(
            self,
            actor,
            [
                ("userId", self.userId),
                ("roleId", self.roleId),
            ],
            now=now,
            commit=False,
            db_sess=db_sess,
        )
        if commit:
            db_sess.commit()
