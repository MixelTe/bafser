from datetime import date, datetime

from typing_extensions import assert_type

from bafser import ForUpdateRequiredError, LockNotSupportedError, PublicError, Undefined, UserBase, get_datetime_utc, parse_date, parse_datetime, validate_config


class User(UserBase):
    __abstract__ = True


assert_type(UserBase.current, UserBase)
assert_type(User.current, User)
assert_type(get_datetime_utc(), datetime)
assert_type(parse_date("2026-10-12"), date | None)
assert_type(parse_datetime("2026-10-12T15:00:00Z"), datetime | None)
assert_type(validate_config(), None)
assert_type(PublicError("Invalid input", status=409), PublicError)
assert_type(PublicError("Invalid input").status, int)
assert_type(PublicError("Invalid input", status=409, code="conflict", details={"remaining": 0}).code, str | None)
assert_type(PublicError("Inherited fields", code=Undefined, details=Undefined).code, str | None)


def check_undefined(value: str | type[Undefined]) -> None:
    assert_type(Undefined.cast(value), str)
    assert_type(Undefined.default(value, "fallback"), str)
    if Undefined.defined(value):
        assert_type(value, str)


def check_instance(user: User) -> None:
    assert_type(user.current, User)
    assert_type(user.is_for_update, bool)
    assert_type(user.require_for_update(), None)
    assert_type(ForUpdateRequiredError(), ForUpdateRequiredError)
    assert_type(LockNotSupportedError(), LockNotSupportedError)
