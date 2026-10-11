from typing_extensions import assert_type

from bafser import UserBase


class User(UserBase):
    __abstract__ = True


assert_type(UserBase.current, UserBase)
assert_type(User.current, User)


def check_instance(user: User) -> None:
    assert_type(user.current, User)
