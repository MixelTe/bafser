from datetime import datetime
from test.data._tables import Tables
from test.data.user import User
from typing import Optional

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bafser import Log, ObjMixin, SqlAlchemyBase


class Apple(SqlAlchemyBase, ObjMixin):
    __tablename__ = Tables.Apple

    name: Mapped[str] = mapped_column(String(128))
    eatDate: Mapped[Optional[datetime]] = mapped_column(init=False)
    ownerId: Mapped[int] = mapped_column(ForeignKey(f"{Tables.User}.id"))

    owner: Mapped["User"] = relationship(back_populates="apples", init=False)

    @staticmethod
    def new(name: str):
        apple = Apple(name=name, ownerId=1)
        Log.added(apple)
        return apple
