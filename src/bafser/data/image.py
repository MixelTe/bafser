from datetime import datetime
from typing import Any, TypedDict, Union
import base64
import os

from flask import current_app
from sqlalchemy import Column, String, orm, ForeignKey, Integer, DateTime
from sqlalchemy.orm import Session

from .. import SqlAlchemyBase, ObjMixin, UserBase, Log, get_json_values, get_datetime_now, create_file_response
from ._tables import TablesBase


class ImageJson(TypedDict):
    data: str
    name: str


TError = str
TFieldName = str
TValue = Any


class Image(SqlAlchemyBase, ObjMixin):
    __tablename__ = TablesBase.Image

    name = Column(String(128), nullable=False)
    type = Column(String(16), nullable=False)
    creationDate = Column(DateTime, nullable=False)
    deletionDate = Column(DateTime, nullable=True)
    createdById = Column(Integer, ForeignKey("User.id"), nullable=False)

    creator = orm.relationship("User")

    @classmethod
    def new(cls, creator: UserBase, json: ImageJson) -> Union[tuple[None, TError], tuple["Image", None]]:
        (data, name), values_error = get_json_values(json, "data", "name")
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
        now = get_datetime_now()
        img, add_changes, err = cls._new(creator, json, {"name": name, "type": type, "createdById": creator.id, "creationDate": now})
        if err:
            return None, err
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

    @staticmethod
    def _new(creator: UserBase, json: ImageJson, image_kwargs: dict) -> \
            Union[tuple[None, None, TError], tuple["Image", list[tuple[TFieldName, TValue]], None]]:
        img = Image(**image_kwargs)
        return img, [], None

    def create_file_response(self):
        return create_file_response(self.get_path(), f"image/{self.type}", self.get_filename())

    def delete(self, actor: UserBase, commit=True, now: datetime = None, db_sess: Session = None):
        now = get_datetime_now() if now is None else now
        self.deletionDate = now
        super().delete(actor, commit, now, db_sess)

    def restore(self, actor: UserBase, commit=True, now: datetime = None, db_sess: Session = None):
        if not os.path.exists(self.get_path()):
            return False
        super().restore(actor, commit, now, db_sess)
        return True

    def get_path(self):
        return os.path.join(current_app.config["IMAGES_FOLDER"], f"{self.id}.{self.type}")

    def get_filename(self):
        return self.name + "." + self.type

    def get_dict(self):
        return self.to_dict(only=("name", "type", "creationDate", "deletionDate", "createdById"))
