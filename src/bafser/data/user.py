from collections.abc import Callable, Iterable
from typing import Any, ClassVar, TypedDict, TypeVar, final

from flask import abort, g, has_request_context
from flask_jwt_extended import get_jwt_identity, unset_jwt_cookies, verify_jwt_in_request  # type: ignore
from flask_jwt_extended.exceptions import JWTExtendedException
from jwt.exceptions import PyJWTError
from sqlalchemy import String, inspect, select
from sqlalchemy.orm import Mapped, Session, declared_attr, lazyload, mapped_column, relationship, validates
from sqlalchemy.orm.attributes import flag_dirty, set_committed_value
from werkzeug.security import check_password_hash, generate_password_hash

from .. import ObjMixin, SqlAlchemyBase, TOperation, TruncateString, UserRole
from ..utils import get_datetime_now
from ._roles import RolesBase
from ._tables import TablesBase

T = TypeVar("T", bound="UserBase")
_User: "type[UserBase] | None" = None
TFieldName = str
TValue = Any

DefaultGetter = Callable[[bool, bool], "UserBase | None"]
_current_user_getter: Callable[[DefaultGetter, bool, bool], "UserBase | None"] = lambda get, lazyload, for_update: get(lazyload, for_update)  # noqa: E731


class _CurrentUser:
    """Resolve the current user while preserving the owner's type."""

    def __get__(self, instance: T | None, owner: type[T]) -> T:
        from .. import response_msg

        user = owner.get_current()
        if user is not None:
            return user

        if has_request_context():
            response = response_msg("The JWT has expired", 401)
            unset_jwt_cookies(response)
            abort(response)
        raise Exception("[bafser] No current user")


class UserKwargs(TypedDict):
    login: str
    name: str


def get_user_table():
    if _User is None:
        raise Exception("[bafser] No class inherited from UserBase")
    return _User


def override_get_current_user(getter: Callable[[DefaultGetter, bool, bool], "UserBase | None"]):
    """def get_current_user(getter: defaultGetter, lazyload: bool, for_update: bool)"""
    global _current_user_getter
    _current_user_getter = getter


class UserBase(ObjMixin, SqlAlchemyBase):
    __tablename__ = TablesBase.User
    __abstract__ = True
    __fields_hidden_in_log__: ClassVar[list[str]] = ["password"]

    login: Mapped[str] = mapped_column(String(64), index=True, unique=True)
    password: Mapped[str] = mapped_column(String(256), init=False)
    name: Mapped[str] = mapped_column(TruncateString(128))

    @validates("login")
    def convert_to_lower(self, key: str, value: Any):
        if isinstance(value, str):
            return value.lower()
        return value

    @declared_attr
    def roles(self) -> Mapped[list[UserRole]]:
        return relationship(UserRole, lazy="joined", init=False)

    def __repr__(self):
        return f"<{self.__class__.__name__}> [{self.id}] {self.login}"

    def __init_subclass__(cls, *args: Any, **kwargs: Any):
        super().__init_subclass__(*args, **kwargs)
        global _User
        _User = cls

    @classmethod
    def new(
        cls,
        creator: "UserBase | None",
        login: str,
        password: str,
        name: str,
        roles: list[int],
        *_: Any,
        db_sess: Session | None = None,
        commit: bool = True,
        **kwargs: Any,
    ):
        from .. import Log, get_db_session

        if db_sess is None:
            db_sess = creator.db_sess if creator is not None else get_db_session()
        user = cls._new(db_sess, {"login": login, "name": name}, **kwargs)
        user.set_password(password)
        db_sess.add(user)

        now = get_datetime_now()
        Log.added(user, creator, None, now, commit=False, db_sess=db_sess)

        for roleId in roles:
            UserRole.new(creator, user.id, roleId, now=now, commit=False, db_sess=db_sess)

        if commit:
            db_sess.commit()

        return user

    @classmethod
    def _new(cls: type[T], db_sess: Session, user_kwargs: UserKwargs, **kwargs: Any) -> T:
        return cls(**user_kwargs)

    @classmethod
    def get_lazy(cls, id: int, includeDeleted: bool = False, *, for_update: bool = False, db_sess: Session | None = None):
        return cls.query(includeDeleted, for_update=for_update, db_sess=db_sess).filter(cls.id == id).options(lazyload(cls.roles)).first()

    @classmethod
    def get_by_login(cls, login: str, includeDeleted: bool = False, *, for_update: bool = False, db_sess: Session | None = None):
        return cls.query(includeDeleted, for_update=for_update, db_sess=db_sess).filter(cls.login == login.lower()).first()

    @final
    @classmethod
    def get_current(cls: type[T], *, lazyload: bool = False, for_update: bool = False) -> T | None:
        return _current_user_getter(UserBase._get_current, lazyload, for_update)  # pyright: ignore[reportReturnType]

    @final
    @staticmethod
    def _get_current(lazyload: bool, for_update: bool) -> "UserBase | None":
        from .. import get_db_session, get_user_by_jwt_identity

        if not has_request_context():
            return None
        policy = g.get("request_policy")
        if policy is not None and policy.authenticate is False:
            return None
        # A cached ORM object is not proof that its row is locked. Re-run
        # the query when a caller explicitly requests SELECT ... FOR UPDATE.
        if "user" in g and not for_update:
            return g.user
        try:
            verify_jwt_in_request()
        except (JWTExtendedException, PyJWTError):
            g.user = None
            return None
        db_sess = get_db_session()
        user = get_user_by_jwt_identity(db_sess, get_jwt_identity(), lazyload=lazyload, for_update=for_update)
        g.user = user
        return user  # type: ignore

    current = _CurrentUser()

    @classmethod
    def create_admin(cls, db_sess: Session, *, commit: bool = True):
        return cls.new(None, "admin", "admin", "Admin", [RolesBase.admin], db_sess=db_sess, commit=commit)

    @final
    @staticmethod
    def _create_admin(db_sess: Session, *, commit: bool = True):
        User = get_user_table()
        admin = User.get_admin(db_sess=db_sess)
        if admin:
            return admin
        return User.create_admin(db_sess, commit=commit)

    @classmethod
    def get_admin(cls, *, db_sess: Session | None = None):
        return cls.query(db_sess=db_sess).join(UserRole).filter(UserRole.roleId == RolesBase.admin).options(lazyload(cls.roles)).first()

    def is_admin(self):
        return self.has_role(RolesBase.admin)

    @classmethod
    def all_of_role(cls, role: int, includeDeleted: bool = False, *, for_update: bool = False, db_sess: Session | None = None):
        return cls.query(includeDeleted, for_update=for_update, db_sess=db_sess).join(UserRole).filter(UserRole.roleId == role).all()

    def update_password(self, actor: "UserBase | None", password: str, *, db_sess: Session | None = None, commit: bool = True):
        from .. import Log

        db_sess = self._get_write_session(db_sess)
        self.set_password(password)
        Log.updated(self, actor, commit=False, db_sess=db_sess)
        if commit:
            db_sess.commit()

    def update_name(self, actor: "UserBase | None", name: str, *, db_sess: Session | None = None, commit: bool = True):
        from .. import Log

        db_sess = self._get_write_session(db_sess)
        self.name = name
        Log.updated(self, actor, commit=False, db_sess=db_sess)
        if commit:
            db_sess.commit()

    def set_password(self, password: str):
        self.password = generate_password_hash(password)

    def check_password(self, password: str):
        return check_password_hash(self.password, password)

    def check_permission(self, operation: TOperation):
        return operation[0] in self.get_operations()

    def has_permissions(self, operations: Iterable[TOperation]) -> bool:
        """Require every operation; an empty iterable succeeds."""
        return self._check_permissions(operations, any_match=False)

    def has_any_permissions(self, operations: Iterable[TOperation]) -> bool:
        """Require at least one operation; an empty iterable fails."""
        return self._check_permissions(operations, any_match=True)

    def _check_permissions(self, operations: Iterable[TOperation], *, any_match: bool) -> bool:
        required = tuple(operations)
        if not required:
            return not any_match
        checker = self.check_permission
        if getattr(checker, "__func__", None) is UserBase.check_permission:
            available = set(self.get_operations())
            matches = (operation[0] in available for operation in required)
        else:
            matches = (checker(operation) for operation in required)
        return any(matches) if any_match else all(matches)

    def has_operation(self, operation: TOperation):
        return self.check_permission(operation)

    def add_role(self, actor: "UserBase | None", roleId: int, *, db_sess: Session | None = None, commit: bool = True):
        """Add a role in the caller's transaction; serialize with other role writes."""
        desired = self._normalize_role_ids((roleId,))
        db_sess = self._get_write_session(db_sess)
        current = self._get_roles_for_write(db_sess)
        return self._apply_roles(actor, set(current) | desired, current, db_sess, commit)

    def remove_role(self, actor: "UserBase | None", roleId: int, *, db_sess: Session | None = None, commit: bool = True):
        """Remove a role without committing when it is absent."""
        removed = self._normalize_role_ids((roleId,))
        db_sess = self._get_write_session(db_sess)
        current = self._get_roles_for_write(db_sess)
        return self._apply_roles(actor, set(current) - removed, current, db_sess, commit)

    def set_roles(self, actor: "UserBase | None", role_ids: Iterable[int], *, db_sess: Session | None = None, commit: bool = True) -> bool:
        """Replace roles atomically, auditing only added/removed memberships."""
        desired = self._normalize_role_ids(role_ids)
        db_sess = self._get_write_session(db_sess)
        current = self._get_roles_for_write(db_sess)
        return self._apply_roles(actor, desired, current, db_sess, commit)

    @staticmethod
    def _normalize_role_ids(role_ids: Iterable[int]) -> set[int]:
        result: set[int] = set()
        for role_id in role_ids:
            if type(role_id) is not int:
                raise TypeError("Role IDs must be integers")
            if role_id <= 0:
                raise ValueError("Role IDs must be positive")
            result.add(role_id)
        return result

    def _get_roles_for_write(self, db_sess: Session) -> dict[int, UserRole]:
        state = inspect(self)
        if state.identity is None:
            db_sess.flush()
        identity = inspect(self).identity
        if identity is None:
            raise ValueError("User must be persisted before changing roles")
        user_id = identity[0]
        User = type(self)
        # Scalar current reads preserve pending user attributes and bypass old
        # MySQL snapshots. SQLite keeps its normal database write-lock behavior.
        locked_id = db_sess.scalar(
            select(User.id).where(User.id == user_id).with_for_update(),
            execution_options={"autoflush": False},
        )
        if locked_id is None:
            raise ValueError("User no longer exists")
        db_sess.flush()
        memberships = db_sess.scalars(
            select(UserRole).where(UserRole.userId == user_id).options(lazyload(UserRole.role)).with_for_update(),
            execution_options={"populate_existing": True},
        ).all()
        # Ordinary expiration/lazy loading could re-read an earlier RR snapshot.
        self._set_roles_cache(memberships, db_sess)
        return {membership.roleId: membership for membership in memberships}

    def _set_roles_cache(self, memberships: Iterable[UserRole], db_sess: Session) -> None:
        set_committed_value(self, "roles", list(memberships))
        # Current reads may include pending membership writes, even when the
        # requested operation becomes a no-op or fails validation afterwards.
        # Track every cache assignment in the current transaction/SAVEPOINT.
        flag_dirty(self)
        db_sess.flush()

    def _apply_roles(self, actor: "UserBase | None", desired: set[int], current: dict[int, UserRole], db_sess: Session, commit: bool) -> bool:
        from .. import Role

        added = desired - current.keys()
        removed = current.keys() - desired
        if not added and not removed:
            return False
        if added:
            # Shared row locks retain role validity until commit without making
            # unrelated users contend for an exclusive role-definition lock.
            available = set(
                db_sess.scalars(
                    select(Role.id).where(Role.id.in_(added), Role.deleted.is_(False)).order_by(Role.id).with_for_update(read=True),
                    execution_options={"autoflush": False},
                )
            )
            if missing := added - available:
                raise ValueError(f"Unknown or deleted role IDs: {sorted(missing)}")
        now = get_datetime_now()
        for role_id in sorted(removed):
            current.pop(role_id).delete(actor, now=now, commit=False, db_sess=db_sess)
        for role_id in sorted(added):
            current[role_id] = UserRole.new(actor, self.id, role_id, now=now, commit=False, db_sess=db_sess)
        db_sess.flush()
        self._set_roles_cache((current[role_id] for role_id in sorted(current)), db_sess)
        if commit:
            db_sess.commit()
        return True

    def get_roles(self) -> list[tuple[int, str]]:
        return [(r.roleId, r.role.name) for r in self.roles]

    def get_roles_ids(self):
        return [v[0] for v in self.get_roles()]

    def get_roles_names(self):
        return [v[1] for v in self.get_roles()]

    def has_role(self, roleId: int):
        return roleId in self.get_roles_ids()

    def has_any_role(self, role_ids: Iterable[int]) -> bool:
        """Return whether at least one requested role is assigned."""
        requested = tuple(role_ids)
        if not requested:
            return False
        assigned = set(self.get_roles_ids())
        return any(role_id in assigned for role_id in requested)

    def get_operations(self) -> list[str]:
        return [v.operationId for r in self.roles for v in r.role.permissions]

    def get_dict(self) -> "UserDict":
        return {
            "id": self.id,
            "name": self.name,
            "login": self.login,
            "roles": self.get_roles_names(),
            "operations": self.get_operations(),
        }

    def get_dict_full(self) -> "UserDictFull":
        return {
            "id": self.id,
            "deleted": self.deleted,
            "name": self.name,
            "login": self.login,
            "roles": self.get_roles(),
            "operations": self.get_operations(),
        }


class UserDict(TypedDict):
    id: int
    name: str
    login: str
    roles: list[str]
    operations: list[str]


class UserDictFull(TypedDict):
    id: int
    deleted: bool
    name: str
    login: str
    roles: list[tuple[int, str]]
    operations: list[str]
