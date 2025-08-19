from types import UnionType
from typing import get_type_hints, get_origin, get_args
from typing import Any, Mapping, TypeVar, overload

T = TypeVar("T")
T1 = TypeVar("T1")
T2 = TypeVar("T2")
T3 = TypeVar("T3")
T4 = TypeVar("T4")
T5 = TypeVar("T5")
T6 = TypeVar("T6")
T7 = TypeVar("T7")
T8 = TypeVar("T8")

field_desc = tuple[str, type[T]] | tuple[str, type[T], T]
# field_desc: (field_name, field_type) | (field_name, field_type, default_value)
values = list[Any] | Any
error = str | None


@overload
def get_json_values(d: Mapping[str, Any], f1: field_desc[T1]) -> tuple[T1, error]: ...  # noqa: E704
@overload
def get_json_values(d: Mapping[str, Any], f1: field_desc[T1], f2: field_desc[T2]) -> tuple[tuple[T1, T2], error]: ...  # noqa: E704
@overload
def get_json_values(d: Mapping[str, Any], f1: field_desc[T1], f2: field_desc[T2], f3: field_desc[T3]) -> tuple[tuple[T1, T2, T3], error]: ...  # noqa: E704, E501
@overload
def get_json_values(d: Mapping[str, Any], f1: field_desc[T1], f2: field_desc[T2], f3: field_desc[T3], f4: field_desc[T4]) -> tuple[tuple[T1, T2, T3, T4], error]: ...  # noqa: E704, E501
@overload
def get_json_values(d: Mapping[str, Any], f1: field_desc[T1], f2: field_desc[T2], f3: field_desc[T3], f4: field_desc[T4], f5: field_desc[T5]) -> tuple[tuple[T1, T2, T3, T4, T5], error]: ...  # noqa: E704, E501
@overload
def get_json_values(d: Mapping[str, Any], f1: field_desc[T1], f2: field_desc[T2], f3: field_desc[T3], f4: field_desc[T4], f5: field_desc[T5], f6: field_desc[T6]) -> tuple[tuple[T1, T2, T3, T4, T5, T6], error]: ...  # noqa: E704, E501
@overload
def get_json_values(d: Mapping[str, Any], f1: field_desc[T1], f2: field_desc[T2], f3: field_desc[T3], f4: field_desc[T4], f5: field_desc[T5], f6: field_desc[T6], f7: field_desc[T7]) -> tuple[tuple[T1, T2, T3, T4, T5, T6, T7], error]: ...  # noqa: E704, E501
@overload
def get_json_values(d: Mapping[str, Any], f1: field_desc[T1], f2: field_desc[T2], f3: field_desc[T3], f4: field_desc[T4], f5: field_desc[T5], f6: field_desc[T6], f7: field_desc[T7], f8: field_desc[T8]) -> tuple[tuple[T1, T2, T3, T4, T5, T6, T7, T8], error]: ...  # noqa: E704, E501
@overload
def get_json_values(d: Mapping[str, Any], *field_names: field_desc[Any]) -> tuple[values, error]: ...  # noqa: E704


def get_json_values(d: Mapping[str, Any], *field_names: field_desc[Any], **kwargs: Any) -> tuple[values, error]:
    if kwargs != {}:
        raise Exception("dont support kwargs")
    r: list[Any] = []
    for field in field_names:
        if len(field) == 2:
            field_name, field_type = field
            default_value = None
            have_default = False
        else:
            field_name, field_type, default_value = field
            have_default = True

        if field_name in d:
            value = d[field_name]
            _, err = validate_type(value, field_type)
            if err is not None:
                rv = None if len(field_names) == 1 else list(map(lambda _: None, field_names))
                return rv, f"'{field_name}' {err}"
            r.append(value)
        elif have_default:
            r.append(default_value)
        else:
            rv = None if len(field_names) == 1 else list(map(lambda _: None, field_names))
            return rv, f"'{field_name}' is undefined"
    if len(r) == 1:
        return r[0], None
    return r, None


type ValidateType = Mapping[str, ValidateType] | int | float | bool | str | object | list[Any]
TC = TypeVar("TC", bound=ValidateType)


def validate_type(obj: Any, otype: type[TC]) -> tuple[TC, None] | tuple[None, str]:
    """Supports int, float, bool, str, object, list, dict, list[<type>], Union[], TypedDict"""
    # simple type
    if otype in (int, float, bool, str, object, list, dict):
        if type(obj) is bool:  # couse isinstance(True, int) is True
            if otype is bool:
                return obj, None  # type: ignore
        elif isinstance(obj, otype):
            return obj, None  # type: ignore
        return None, f"is not {otype}"

    # generic list
    torigin = get_origin(otype)
    targs = get_args(otype)
    if torigin is list and len(targs) == 1:
        t = targs[0]
        if not isinstance(obj, list):
            return None, f"is not {otype}"
        for i, el in enumerate(obj):  # type: ignore
            _, err = validate_type(el, t)
            if err is not None:
                return None, f"[{i}] {err}"
        return obj, None  # type: ignore

    # generic dict
    if torigin is dict and len(targs) == 2:
        tk = targs[0]
        tv = targs[1]
        if not isinstance(obj, dict):
            return None, f"is not {otype}"
        for k, v in obj.items():  # type: ignore
            if tk != Any:
                _, err = validate_type(k, tk)
                if err is not None:
                    return None, f"key '{k}' {err}"
            if tv != Any:
                _, err = validate_type(v, tv)
                if err is not None:
                    return None, f"field '{k}' {err}"
        return obj, None  # type: ignore

    # Union
    if torigin is UnionType:
        for t in targs:
            _, err = validate_type(obj, t)
            if err is None:
                return obj, None  # type: ignore
        return None, f"is not {otype}"

    # TypedDict
    try:
        type_hints = get_type_hints(otype)
        opt_keys: frozenset[str] = otype.__optional_keys__  # type: ignore
    except (TypeError, AttributeError):
        raise Exception("[bafser] validate_type: unsupported type")

    if not isinstance(obj, dict):
        return None, f"is not {otype}"
    for k, t in type_hints.items():
        if k not in obj:
            if k in opt_keys:
                continue
            return None, f"field is missing '{k}': {t}"
        v = obj[k]  # type: ignore
        _, err = validate_type(v, t)
        if err is not None:
            return None, f"field '{k}' {err}"

    return obj, None  # type: ignore
