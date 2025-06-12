def get_all_field_names(obj: object):
    return (attr for attr in dir(obj) if not callable(getattr(obj, attr)) and not attr.startswith("__"))


def get_all_values(obj: object):
    return (getattr(obj, field) for field in get_all_field_names(obj))


def get_all_fields(obj: object):
    return ((field, getattr(obj, field)) for field in get_all_field_names(obj))
