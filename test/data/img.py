from typing import TypedDict

from typing_extensions import override

from sqlalchemy import String
from sqlalchemy.orm import Mapped, Session, mapped_column

from bafser import Image as ImageBase
from bafser import ImageError, ImageKwargs, get_json_values
from test.data.user import User


class ImageJson(TypedDict):
    data: str
    name: str
    desc: str


class Img(ImageBase):
    desc: Mapped[str] = mapped_column(String(128))

    @classmethod
    @override
    def new(cls, creator: User, json: ImageJson, *, db_sess: Session | None = None, commit: bool = True):  # type: ignore
        return super().new(creator, json, db_sess=db_sess, commit=commit)

    @classmethod
    @override
    def _new(cls, creator: User, json: ImageJson, image_kwargs: ImageKwargs):  # type: ignore
        desc, values_error = get_json_values(json, ("desc", str))
        if values_error:
            raise ImageError(values_error)
        img = Img(**image_kwargs, desc=desc)
        return img
