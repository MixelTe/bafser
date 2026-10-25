from datetime import datetime

from typing_extensions import assert_type

from bafser import ForUpdateRequiredError, LockNotSupportedError, UserBase, get_datetime_utc


class User(UserBase):
    __abstract__ = True


assert_type(UserBase.current, UserBase)
assert_type(User.current, User)
assert_type(get_datetime_utc(), datetime)


def check_instance(user: User) -> None:
    assert_type(user.current, User)
    assert_type(user.is_for_update, bool)
    assert_type(user.require_for_update(), None)
    assert_type(ForUpdateRequiredError(), ForUpdateRequiredError)
    assert_type(LockNotSupportedError(), LockNotSupportedError)
