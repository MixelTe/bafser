from datetime import datetime
from typing import Optional

from sqlalchemy import ForeignKey, String
from bafser import SqlAlchemyBase, ObjMixin
from sqlalchemy.orm import Mapped, mapped_column, relationship

from test.data._tables import Tables
from test.data.user import User


class Apple(SqlAlchemyBase, ObjMixin):
    __tablename__ = Tables.Apple

    name: Mapped[str] = mapped_column(String(128))
    eatDate: Mapped[Optional[datetime]] = mapped_column(init=False)
    ownerId: Mapped[int] = mapped_column(ForeignKey(f"{Tables.User}.id"))

    owner: Mapped["User"] = relationship(back_populates="apples", init=False)
