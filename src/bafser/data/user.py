from typing import Any, Type, TypeVar

from sqlalchemy import Column, String
from sqlalchemy.orm import Session
from werkzeug.security import generate_password_hash, check_password_hash

from .. import SqlAlchemyBase, ObjMixin, UserRole
from ..utils import get_datetime_now
from ._roles import RolesBase
from ._tables import TablesBase
from .permission import Permission

T = TypeVar("T", bound="UserBase")
User: "Type[UserBase]" = None
TFieldName = str
TValue = Any


def get_user_table():
    if User is None:
        raise Exception("[bafser] No class inherited from UserBase")
    return User


class UserBase(SqlAlchemyBase, ObjMixin):
    __tablename__ = TablesBase.User

    login = Column(String(64), index=True, unique=True, nullable=False)
    password = Column(String(128), nullable=False)
    name = Column(String(64), nullable=False)

    def __repr__(self):
        return f"<{self.__class__.__name__}> [{self.id}] {self.login}"

    def __init_subclass__(cls, **kwargs):
        global User
        User = cls

    @classmethod
    def new(cls, creator: "UserBase", login: str, password: str, name: str, roles: list[int], db_sess: Session = None, **kwargs):
        from .. import Log
        db_sess = db_sess if db_sess else Session.object_session(creator)
        user, add_changes = cls._new(db_sess, {"login": login, "name": name}, **kwargs)
        user.set_password(password)
        db_sess.add(user)

        now = get_datetime_now()
        Log.added(user, creator, [
            ("login", user.login),
            ("name", user.name),
            ("password", "***"),
            *add_changes,
        ], now, db_sess=db_sess)

        for roleId in roles:
            UserRole.new(creator, user.id, roleId, now=now, commit=False, db_sess=db_sess)

        db_sess.commit()

        return user

    @classmethod
    def _new(cls: Type[T], db_sess: Session, user_kwargs: dict, **kwargs) -> tuple[T, list[tuple[TFieldName, TValue]]]:
        user = cls(**user_kwargs)
        return user, []

    @classmethod
    def get_by_login(cls, db_sess: Session, login: str, includeDeleted=False):
        return cls.query(db_sess, includeDeleted).filter(cls.login == login).first()

    @classmethod
    def create_admin(cls, db_sess: Session):
        fake_creator = UserBase.get_fake_system()
        return cls.new(fake_creator, "admin", "admin", "Админ", [RolesBase.admin], db_sess=db_sess)

    @staticmethod
    def _create_admin(db_sess: Session):
        User = get_user_table()
        admin = User.get_admin(db_sess)
        if admin:
            return admin
        return User.create_admin(db_sess)

    @classmethod
    def get_admin(cls, db_sess: Session):
        return db_sess.query(cls).join(UserRole).filter(UserRole.roleId == RolesBase.admin).first()

    _is_admin = None

    def is_admin(self):
        if self._is_admin is None:
            self._is_admin = self.has_role(RolesBase.admin)
        return self._is_admin

    @staticmethod
    def get_fake_system():
        return UserBase(id=1, name="System")

    @classmethod
    def all_of_role(cls, db_sess: Session, role: int, includeDeleted=False):
        return cls.query(db_sess, includeDeleted).join(UserRole).filter(UserRole.roleId == role).all()

    def update_password(self, actor: "UserBase", password: str):
        from .. import Log
        self.set_password(password)
        Log.updated(self, actor, [("password", "***", "***")])

    def update_name(self, actor: "UserBase", name: str):
        from .. import Log
        oldname = self.name
        self.name = name
        Log.updated(self, actor, [("name", oldname, name)])

    def set_password(self, password: str):
        self.password = generate_password_hash(password)

    def check_password(self, password: str):
        return check_password_hash(self.password, password)

    def check_permission(self, operation: tuple[str, str]):
        return operation[0] in self.get_operations()

    def add_role(self, actor: "UserBase", roleId: int):
        db_sess = Session.object_session(self)
        existing = UserRole.get(db_sess, self.id, roleId)
        if existing:
            return False

        UserRole.new(actor, self.id, roleId)
        if roleId == RolesBase.admin:
            self._is_admin = True
        return True

    def remove_role(self, actor: "UserBase", roleId: int):
        db_sess = Session.object_session(self)
        user_role = UserRole.get(db_sess, self.id, roleId)
        if not user_role:
            return False

        user_role.delete(actor)
        if roleId == RolesBase.admin:
            self._is_admin = False
        return True

    def get_roles(self):
        from .. import Role
        db_sess = Session.object_session(self)
        roles = db_sess\
            .query(Role)\
            .join(UserRole, UserRole.roleId == Role.id)\
            .filter(UserRole.userId == self.id)\
            .values(Role.name)

        return list(map(lambda v: v[0], roles))

    def has_role(self, roleId: int):
        db_sess = Session.object_session(self)
        ur = db_sess\
            .query(UserRole.roleId)\
            .filter(UserRole.roleId == roleId)\
            .filter(UserRole.userId == self.id)\
            .first()

        return ur is not None

    def get_operations(self):
        from .. import Role
        db_sess = Session.object_session(self)
        operations = db_sess\
            .query(Permission)\
            .join(Role, Permission.roleId == Role.id)\
            .join(UserRole, UserRole.roleId == Role.id)\
            .filter(UserRole.userId == self.id)\
            .values(Permission.operationId)

        return list(map(lambda v: v[0], operations))

    def get_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "login": self.login,
            "roles": self.get_roles(),
            "operations": self.get_operations(),
        }

    def get_dict_full(self):
        return {
            "id": self.id,
            "deleted": self.deleted,
            "name": self.name,
            "login": self.login,
            "roles": self.get_roles(),
            "operations": self.get_operations(),
        }
