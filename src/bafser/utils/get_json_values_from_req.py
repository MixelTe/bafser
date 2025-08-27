from typing import Any, TypeVar, overload

from flask import abort, g

from . import get_json_list, get_json_values, response_msg
from .get_json_values import field_desc

T = TypeVar("T")
T1 = TypeVar("T1")
T2 = TypeVar("T2")
T3 = TypeVar("T3")
T4 = TypeVar("T4")
T5 = TypeVar("T5")
T6 = TypeVar("T6")
T7 = TypeVar("T7")
T8 = TypeVar("T8")


@overload
def get_json_values_from_req(f1: field_desc[T1]) -> T1: ...  # noqa: E704
@overload
def get_json_values_from_req(f1: field_desc[T1], f2: field_desc[T2]) -> tuple[T1, T2]: ...  # noqa: E704
@overload
def get_json_values_from_req(f1: field_desc[T1], f2: field_desc[T2], f3: field_desc[T3]) -> tuple[T1, T2, T3]: ...  # noqa: E704
@overload
def get_json_values_from_req(f1: field_desc[T1], f2: field_desc[T2], f3: field_desc[T3], f4: field_desc[T4]) -> tuple[T1, T2, T3, T4]: ...  # noqa: E704, E501
@overload
def get_json_values_from_req(f1: field_desc[T1], f2: field_desc[T2], f3: field_desc[T3], f4: field_desc[T4], f5: field_desc[T5]) -> tuple[T1, T2, T3, T4, T5]: ...  # noqa: E704, E501
@overload
def get_json_values_from_req(f1: field_desc[T1], f2: field_desc[T2], f3: field_desc[T3], f4: field_desc[T4], f5: field_desc[T5], f6: field_desc[T6]) -> tuple[T1, T2, T3, T4, T5, T6]: ...  # noqa: E704, E501
@overload
def get_json_values_from_req(f1: field_desc[T1], f2: field_desc[T2], f3: field_desc[T3], f4: field_desc[T4], f5: field_desc[T5], f6: field_desc[T6], f7: field_desc[T7]) -> tuple[T1, T2, T3, T4, T5, T6, T7]: ...  # noqa: E704, E501
@overload
def get_json_values_from_req(f1: field_desc[T1], f2: field_desc[T2], f3: field_desc[T3], f4: field_desc[T4], f5: field_desc[T5], f6: field_desc[T6], f7: field_desc[T7], f8: field_desc[T8]) -> tuple[T1, T2, T3, T4, T5, T6, T7, T8]: ...  # noqa: E704, E501
@overload
def get_json_values_from_req(*field_names: field_desc[Any]) -> list[Any]: ...  # noqa: E704


def get_json_values_from_req(*field_names: field_desc[Any], **kwargs: Any):
    if kwargs != {}:
        raise Exception("dont support kwargs")
    data = get_json_from_req(dict)  # type: ignore

    values, values_error = get_json_values(data, *field_names)  # type: ignore

    if values_error:
        abort(response_msg(values_error, 400))

    return values


def get_json_list_from_req(otype: type[T]) -> list[T]:
    data = get_json_from_req(list)  # type: ignore

    values, values_error = get_json_list(data, otype)  # type: ignore

    if values_error:
        abort(response_msg(values_error, 400))

    return values


def get_json_from_req(otype: type[T]) -> T:
    data, is_json = g.json
    if not is_json:
        abort(response_msg("body is not json", 415))

    if not isinstance(data, otype):
        tname = otype.__name__
        if otype is dict:
            tname = "object"
        abort(response_msg(f"body json is not {tname}", 400))

    return data
