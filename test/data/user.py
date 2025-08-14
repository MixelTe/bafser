from typing import TYPE_CHECKING, List, Optional
from sqlalchemy import ForeignKey
from bafser import Image, UserBase
from sqlalchemy.orm import Mapped, mapped_column, relationship

from test.data._tables import Tables
if TYPE_CHECKING:
    from test.data.apple import Apple


class User(UserBase):
    # __tablename__ = Tables.User

    avatarId: Mapped[Optional[int]] = mapped_column(ForeignKey(f"{Tables.Image}.id"), init=False)

    avatar: Mapped[Image] = relationship(init=False, foreign_keys=f"{Tables.User}.avatarId")
    apples: Mapped[List["Apple"]] = relationship(back_populates="owner", default_factory=list)
