from datetime import datetime
from typing import Any, Optional, Type, TypeVar, TypedDict, override
import base64
import os

from flask import current_app
from sqlalchemy import String, ForeignKey
from sqlalchemy.orm import Session, Mapped, mapped_column

from .. import SqlAlchemyBase, ObjMixin, UserBase, Log, get_json_values, get_datetime_now, create_file_response
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


class Image(SqlAlchemyBase, ObjMixin):
    __tablename__ = TablesBase.Image

    name: Mapped[str] = mapped_column(String(128))
    type: Mapped[str] = mapped_column(String(16))
    creationDate: Mapped[datetime]
    deletionDate: Mapped[Optional[datetime]] = mapped_column(init=False)
    createdById: Mapped[int] = mapped_column(ForeignKey(f"{TablesBase.User}.id"))

    @classmethod
    def new(cls: Type[T], creator: UserBase, json: ImageJson) -> tuple[T, None] | tuple[None, TError]:
        (data, name), values_error = get_json_values(json, ("data", str), ("name", str))
        if values_error:
            return None, values_error

        data_splited = data.split(',')
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

        db_sess = Session.object_session(creator)
        assert db_sess
        now = get_datetime_now()
        img, add_changes, err = cls._new(creator, json, {"name": name, "type": type, "createdById": creator.id, "creationDate": now})
        if err:
            return None, err
        assert img
        assert add_changes is not None
        db_sess.add(img)
        db_sess.commit()

        path = img.get_path()
        with open(path, "wb") as f:
            f.write(base64.b64decode(img_data + '=='))

        Log.added(img, creator, [
            ("name", img.name),
            ("type", img.type),
            ("creationDate", img.creationDate.isoformat()),
            ("createdById", img.createdById),
            *add_changes,
        ], now)

        return img, None

    @classmethod
    def _new(cls: Type[T], creator: UserBase, json: ImageJson, image_kwargs: ImageKwargs) -> \
            tuple[None, None, TError] | tuple[T, list[tuple[TFieldName, TValue]], None]:
        img = cls(**image_kwargs)
        return img, [], None

    def create_file_response(self):
        return create_file_response(self.get_path(), f"image/{self.type}", self.get_filename())

    @override
    def _on_delete(self, db_sess: Session, actor: UserBase, now: datetime, commit: bool):
        self.deletionDate = now
        return True

    @override
    def _on_restore(self, db_sess: Session, actor: UserBase, now: datetime, commit: bool):
        return os.path.exists(self.get_path())

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
