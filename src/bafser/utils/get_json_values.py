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
    from ..jsonobj import validate_type
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
            value, err = validate_type(value, field_type)
            if err is not None:
                rv = None if len(field_names) == 1 else list(map(lambda _: None, field_names))
                return rv, field_name + err
            r.append(value)
        elif have_default:
            r.append(default_value)
        else:
            rv = None if len(field_names) == 1 else list(map(lambda _: None, field_names))
            return rv, f"{field_name} is undefined"
    if len(r) == 1:
        return r[0], None
    return r, None


def get_json_list(l: list[Any], otype: type[T]) -> tuple[list[T], error]:
    from ..jsonobj import validate_type
    r: list[T] = []
    for i, el in enumerate(l):
        el, err = validate_type(el, otype)
        if err is not None:
            return [], f"[{i}]{err}"
        r.append(el)  # type: ignore
    return r, None
