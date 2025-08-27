from collections.abc import Callable as CallableClass
from types import NoneType, UnionType
from typing import Any, Mapping, get_args, get_origin, get_type_hints

from flask import Flask

from bafser.jsonobj import JsonObj, type_name

type JsonSingleKey[K: str, V] = Mapping[K, V]

_docs: list[tuple[str, Any]] = []
_types: dict[str, Any] = {}


def init_api_docs(app: Flask):
    for rule in app.url_map.iter_rules():
        fn = app.view_functions[rule.endpoint]
        reqtype: Any = None
        restype: Any = None
        desc: Any = None
        perms: Any = None
        nojwt: Any = None
        if hasattr(fn, "_doc_api_reqtype"):
            reqtype = fn._doc_api_reqtype  # type: ignore
        if hasattr(fn, "_doc_api_restype"):
            restype = fn._doc_api_restype  # type: ignore
        if hasattr(fn, "_doc_api_desc"):
            desc = fn._doc_api_desc  # type: ignore
        if hasattr(fn, "_doc_api_perms"):
            perms = fn._doc_api_perms  # type: ignore
        if hasattr(fn, "_doc_api_nojwt"):
            nojwt = fn._doc_api_nojwt  # type: ignore

        route = str(rule)
        d: Any = {}
        if desc is not None:
            d["__desc__"] = desc
        if reqtype is not None:
            route += " POST"
            d["request"] = type_to_json(reqtype, _types, toplvl=True)
        if restype is not None:
            d["response"] = type_to_json(restype, _types, toplvl=True)
        if perms is not None:
            d["__permsions__"] = perms
        if nojwt is True:
            d["__nojwt__"] = True
        if d == {}:
            continue
        _docs.append((route, d))


def get_api_docs() -> dict[str, Any]:
    _docs.sort(key=lambda v: v[0])
    return {**{k: v for (k, v) in _docs}, **_types}


def doc_api(*, req: Any = None, res: Any = None, desc: str | None = None, nojwt: bool = False):
    def decorator(fn: Any) -> Any:
        fn._doc_api_reqtype = req
        fn._doc_api_restype = res
        fn._doc_api_desc = desc
        fn._doc_api_nojwt = nojwt
        return fn
    return decorator


def type_to_json(otype: Any, types: dict[str, Any], verbose: bool = True, toplvl: bool = False) -> Any:
    if otype in (int, float):
        return "number"
    if otype == bool:
        return "boolean"
    if otype == str:
        return "string"
    if otype in (None, NoneType):
        return "null"

    torigin = get_origin(otype)
    targs = get_args(otype)
    if torigin is list and len(targs) == 1:
        t = targs[0]
        to = get_origin(t)
        r = type_to_json(t, types)
        if isinstance(r, str):
            if to in (UnionType, CallableClass):
                return f"({r})[]"
            return r + "[]"
        if verbose:
            return [r]
        return type_name(otype, json=True)
    if torigin is dict:
        type_to_json(targs[1], types, False)
        return type_name(otype, json=True)
    if torigin is UnionType:
        for t in targs:
            type_to_json(t, types, False)
        return type_name(otype, json=True)
    if torigin is JsonSingleKey:
        k = targs[0]
        t = targs[1]
        return {k: type_to_json(t, types, verbose)}

    r: dict[str, Any] = {}
    optional_fields: list[str] = []
    try:
        try:
            if issubclass(otype, JsonObj):
                type_hints = otype.get_field_types()
                optional_fields = otype.get_optional_fields()
            else:
                type_hints = get_type_hints(otype)
        except Exception:
            type_hints = get_type_hints(otype)
    except Exception:
        return type_name(otype, json=True)

    if not toplvl and otype.__name__ not in types and otype.__name__ != "dict":
        types[otype.__name__] = {}
        types[otype.__name__] = type_to_json(otype, types)
    if not verbose:
        return type_name(otype, json=True)

    for k, t in type_hints.items():
        if k in optional_fields:
            k += "?"
        r[k] = type_to_json(t, types, False)

    return r
