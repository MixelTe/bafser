from datetime import datetime

from typing_extensions import assert_type

from bafser import UserBase, get_datetime_utc


class User(UserBase):
    __abstract__ = True


assert_type(UserBase.current, UserBase)
assert_type(User.current, User)
assert_type(get_datetime_utc(), datetime)


def check_instance(user: User) -> None:
    assert_type(user.current, User)
