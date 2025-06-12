from . import response_msg


def response_not_found(name: str, id: int):
    return response_msg(f"{name.capitalize()} with '{name}Id={id}' not found", 400)
