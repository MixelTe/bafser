from typing import TypedDict, override
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from bafser import Image as ImageBase, ImageKwargs, get_json_values
from test.data.user import User


class ImageJson(TypedDict):
    data: str
    name: str
    desc: str


class Img(ImageBase):
    desc: Mapped[str] = mapped_column(String(128))

    @classmethod
    @override
    def new(cls, creator: User, json: ImageJson):  # type: ignore
        return super().new(creator, json)

    @classmethod
    @override
    def _new(cls, creator: User, json: ImageJson, image_kwargs: ImageKwargs):  # type: ignore
        desc, values_error = get_json_values(json, ("desc", str))
        if values_error:
            return None, None, values_error
        img = Img(**image_kwargs, desc=desc)
        changes = [("desc", desc)]
        return img, changes, None
