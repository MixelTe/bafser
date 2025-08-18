from typing import get_type_hints
from typing import Any, Mapping, TypeVar, overload

T = TypeVar("T")
T1 = TypeVar("T1")
T2 = TypeVar("T2")
T3 = TypeVar("T3")
T4 = TypeVar("T4")
T5 = TypeVar("T5")
T6 = TypeVar("T6")

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
                return rv, f"{field_name} {err}"
            r.append(value)
        elif have_default:
            r.append(default_value)
        else:
            rv = None if len(field_names) == 1 else list(map(lambda _: None, field_names))
            return rv, f"{field_name} is undefined"
    if len(r) == 1:
        return r[0], None
    return r, None


type SimpleType = Mapping[str, SimpleType] | int | float | bool | str
TC = TypeVar("TC", bound=SimpleType)


def validate_type(obj: Any, otype: type[TC]) -> tuple[TC, None] | tuple[None, str]:
    if otype in (int, float, bool, str):
        if isinstance(obj, otype):
            return obj, None
        else:
            return None, f"is not {otype}"
    if not isinstance(obj, dict):
        return None, f"is not {otype}"

    type_hints = get_type_hints(otype)
    for k, t in type_hints.items():
        if k not in obj:
            return None, f"field is missing {k}: {t}"
        v = obj[k]  # type: ignore
        _, err = validate_type(v, t)
        if err is not None:
            return None, f"field {k} {err}"

    return obj, None  # type: ignore
