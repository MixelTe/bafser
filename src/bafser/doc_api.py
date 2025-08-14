from typing import Any, get_type_hints
from flask import Flask

_docs: list[tuple[str, Any]] = []


def init_api_docs(app: Flask):
    for rule in app.url_map.iter_rules():
        fn = app.view_functions[rule.endpoint]
        reqtype: Any = None
        restype: Any = None
        desc: Any = None
        if hasattr(fn, "_doc_api_reqtype"):
            reqtype = fn._doc_api_reqtype  # type: ignore
        if hasattr(fn, "_doc_api_restype"):
            restype = fn._doc_api_restype  # type: ignore
        if hasattr(fn, "_doc_api_desc"):
            desc = fn._doc_api_desc  # type: ignore

        route = str(rule)
        d: Any = {}
        if desc is not None:
            d["__desc__"] = desc
        if reqtype is not None:
            route += " POST"
            d["request"] = type_to_json(reqtype)
        if restype is not None:
            d["response"] = type_to_json(restype)
        if d == {}:
            continue
        _docs.append((route, d))


def get_api_docs():
    _docs.sort(key=lambda v: v[0])
    return {k: v for (k, v) in _docs}


def doc_api(req: Any = None, res: Any = None, desc: str | None = None):
    def decorator(fn: Any) -> Any:
        fn._doc_api_reqtype = req
        fn._doc_api_restype = res
        fn._doc_api_desc = desc
        return fn
    return decorator


def type_to_json(otype: Any):
    if otype in (int, float):
        return "number"
    if otype == bool:
        return "boolean"
    if otype == str:
        return "string"
    if otype is None:
        return "null"

    r: dict[str, Any] = {}
    type_hints = get_type_hints(otype)
    for k, t in type_hints.items():
        r[k] = type_to_json(t)

    return r
