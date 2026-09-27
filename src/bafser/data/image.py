import base64
import binascii
import builtins
import os
from datetime import datetime
from typing import Any, TypedDict, TypeVar, cast, override

from flask import current_app
from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, Session, mapped_column

from .. import Log, ObjMixin, SqlAlchemyBase, UserBase, create_file_response, get_datetime_now, get_json_values
from ._tables import TablesBase


class ImageJson(TypedDict):
    data: str
    name: str


class ImageKwargs(TypedDict):
    name: str
    type: str
    createdById: int
    creationDate: datetime


T = TypeVar("T", bound="Image")
TError = str
TFieldName = str
TValue = Any


def _detected_image_type(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    return None


class Image(SqlAlchemyBase, ObjMixin):
    __tablename__ = TablesBase.Image

    name: Mapped[str] = mapped_column(String(128))
    type: Mapped[str] = mapped_column(String(16))
    creationDate: Mapped[datetime]
    deletionDate: Mapped[datetime | None] = mapped_column(init=False)
    createdById: Mapped[int] = mapped_column(ForeignKey(f"{TablesBase.User}.id"))

    @classmethod
    def new(cls: builtins.type[T], creator: UserBase, json: ImageJson) -> tuple[T, None] | tuple[None, TError]:
        (data, name), values_error = get_json_values(json, ("data", str), ("name", str))
        if values_error:
            return None, values_error

        name = name.strip()
        if not 1 <= len(name) <= 128 or any(ord(char) < 32 for char in name):
            return None, "img name length must be between 1 and 128 and contain no control characters"

        data_splited = data.split(",")
        if len(data_splited) != 2:
            return None, "img data is not base64"

        img_header, img_data = data_splited
        img_header_splited = img_header.split(";")
        if len(img_header_splited) != 2 or img_header_splited[1] != "base64":
            return None, "img data is not base64"

        img_header_splited_splited = img_header_splited[0].split(":")
        if len(img_header_splited_splited) != 2:
            return None, "img data is not base64"
        mimetype = img_header_splited_splited[1]

        if mimetype not in ["image/png", "image/jpeg", "image/gif"]:
            return None, "img mimetype is not in [image/png, image/jpeg, image/gif]"

        type = mimetype.split("/")[1]
        max_image_bytes = cast(int, current_app.config["MAX_IMAGE_BYTES"])

        # Reject malformed content before creating a database record. Checking
        # magic bytes prevents arbitrary files from being served as images.
        if len(img_data) > ((max_image_bytes + 2) // 3) * 4:
            return None, "img data is too large"
        try:
            decoded_data = base64.b64decode(img_data, validate=True)
        except (ValueError, binascii.Error):
            return None, "img data is not valid base64"
        if len(decoded_data) > max_image_bytes:
            return None, "img data is too large"
        if _detected_image_type(decoded_data) != type:
            return None, "img content does not match its mimetype"

        now = get_datetime_now()
        img, err = cls._new(creator, json, {"name": name, "type": type, "createdById": creator.id, "creationDate": now})
        if err:
            return None, err
        assert img
        db_sess = creator.db_sess
        db_sess.add(img)
        db_sess.flush()

        path = img.get_path()
        try:
            with open(path, "wb") as f:
                f.write(decoded_data)
            Log.added(img, creator, now=now)
        except Exception:
            db_sess.rollback()
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
            raise

        return img, None

    @classmethod
    def new2(cls: builtins.type[T], json: ImageJson, *, creator: UserBase | None = None) -> tuple[T, None] | tuple[None, TError]:
        return cls.new(creator or UserBase.current, json)

    @classmethod
    def _new(cls: builtins.type[T], creator: UserBase, json: ImageJson, image_kwargs: ImageKwargs) -> tuple[None, TError] | tuple[T, None]:
        img = cls(**image_kwargs)
        return img, None

    @override
    def _on_delete(self, db_sess: Session, actor: UserBase, now: datetime, commit: bool):
        self.deletionDate = now
        return True

    @override
    def _on_restore(self, db_sess: Session, actor: UserBase, now: datetime, commit: bool):
        return os.path.exists(self.get_path())

    def create_file_response(self):
        return create_file_response(self.get_path(), f"image/{self.type}", self.get_filename())

    def get_path(self):
        return os.path.join(current_app.config["IMAGES_FOLDER"], f"{self.id}.{self.type}")  # type: ignore

    def get_filename(self):
        return self.name + "." + self.type

    def get_dict(self) -> "ImageDict":
        return self.to_dict(only=("name", "type", "creationDate", "deletionDate", "createdById"))  # type: ignore


class ImageDict(TypedDict):
    name: str
    type: str
    creationDate: datetime
    deletionDate: datetime
    createdById: int
