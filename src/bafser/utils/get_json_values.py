from typing import Any, Union

field_name = str
default_value = Any
values = Union[list[Any], Any]
error = str


def get_json_values(d: dict, *field_names: Union[field_name, tuple[field_name, default_value]]) -> tuple[values, error]:
    r = []
    for field in field_names:
        if isinstance(field, tuple) and len(field) == 2:
            field_name, default_value = field
            have_default = True
        else:
            field_name = field
            have_default = False

        if field_name in d:
            r.append(d[field_name])
        elif have_default:
            r.append(default_value)
        else:
            r = None if len(field_names) == 1 else list(map(lambda _: None, field_names))
            return r, f"{field_name} is undefined"
    if len(r) == 1:
        return r[0], None
    return r, None
