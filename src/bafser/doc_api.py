import inspect
import json
import os
from collections.abc import Callable as CallableClass
from types import NoneType, UnionType
from typing import Any, Literal, Mapping, Union, get_args, get_origin, get_type_hints

import jinja2
from flask import Flask, render_template

from .jsonobj import JsonObj, JsonOpt, Undefined, type_name

type JsonSingleKey[K: str, V] = Mapping[K, V]

_docs: list[tuple[str, Any]] = []
_types: dict[str, Any] = {}
_endpoints: list["EndpointInfo"] = []
_types_full: dict[str, "TypeInfo"] = {}

_loc = os.path.abspath(os.path.dirname(__file__))
_templateEnv = jinja2.Environment(loader=jinja2.FileSystemLoader(os.path.join(_loc, "templates")))
template_docs = _templateEnv.get_template("docs.html")


def init_api_docs(app: Flask):
    from . import M
    for rule in app.url_map.iter_rules():
        fn = app.view_functions[rule.endpoint]
        _, line = inspect.getsourcelines(fn)
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
        d: dict[str, Any] = {}
        methods = ""
        if rule.methods is not None:
            methods = " ".join(rule.methods - set([M.HEAD, M.OPTIONS]))
        endpoint = EndpointInfo(route=rule.endpoint, url=route, name=fn.__module__ + "." + fn.__name__, line=line, methods=methods)
        if desc is not None:
            d["__desc__"] = desc
            endpoint.desc = desc
        if nojwt is True:
            d["__nojwt__"] = True
            endpoint.nojwt = True
        if reqtype is not None:
            d["request"] = type_to_json(reqtype, _types, toplvl=True)
            endpoint.reqtype = type_info(reqtype, _types_full)
        if restype is not None:
            d["response"] = type_to_json(restype, _types, toplvl=True)
            endpoint.restype = type_info(restype, _types_full)
        if d == {}:
            continue
        if perms is not None:
            d["__permsions__"] = perms
            endpoint.perms = perms
        _docs.append((route + f" {methods}", d))
        _endpoints.append(endpoint)


def get_api_docs() -> dict[str, Any]:
    _docs.sort(key=lambda v: v[0])
    return {**{k: v for (k, v) in _docs}, **_types}


def render_docs_page():
    from . import get_app_config

    template_docs = _templateEnv.get_template("docs.html")
    routes = [e.json() for e in _endpoints]
    types = {k: v.json() for k, v in _types_full.items()}
    dev = get_app_config().DEV_MODE
    return render_template(template_docs,
                           routes=json.dumps(routes),
                           types=json.dumps(types),
                           loc=os.getcwd().replace("\\", "/") if dev else "",
                           locb=_loc.replace("\\", "/") if dev else "",
                           dev=dev
                           )


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
    if torigin is tuple:
        l = [type_to_json(t, types) for t in targs]
        if verbose:
            return l
        return type_name(otype, json=True)
    if torigin is dict:
        type_to_json(targs[1], types, False)
        return type_name(otype, json=True)
    if torigin in (UnionType, Union):
        for t in targs:
            type_to_json(t, types, False)
        return type_name(otype, json=True)
    if torigin is Literal:
        return type_name(otype, json=True)
    if torigin is JsonSingleKey:
        k = targs[0]
        if get_origin(k) is Literal:
            k = get_args(k)[0]
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
                optional_fields = otype.__optional_keys__  # type: ignore
        except Exception:
            type_hints = get_type_hints(otype)
            optional_fields = otype.__optional_keys__  # type: ignore
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


class EndpointInfo(JsonObj):
    url: str
    route: str
    name: str
    methods: str
    line: int
    reqtype: JsonOpt["TypeInfo"] = Undefined
    restype: JsonOpt["TypeInfo"] = Undefined
    desc: JsonOpt[str] = Undefined
    perms: JsonOpt[str] = Undefined
    nojwt: JsonOpt[bool] = Undefined


class TypeInfo(JsonObj):
    name: JsonOpt[str] = Undefined
    line: JsonOpt[int] = Undefined
    type: Literal["tlink", "int", "float", "bool", "str", "null", "any", "literal", "list", "tuple", "dict", "union", "object"]
    list_type: JsonOpt["TypeInfo"] = Undefined
    tuple_type: JsonOpt[list["TypeInfo"]] = Undefined
    dict_type: JsonOpt[tuple["TypeInfo", "TypeInfo"]] = Undefined
    union_type: JsonOpt[list["TypeInfo"]] = Undefined
    literal: JsonOpt[list[str | int | bool | None]] = Undefined
    object_fields: JsonOpt[list["TypeInfoField"]] = Undefined


class TypeInfoField(JsonObj):
    name: str
    type: TypeInfo
    optional: bool = False
    desc: str | None = None
    default: JsonOpt[Any] = Undefined


def type_info(otype: Any, types: dict[str, TypeInfo]) -> TypeInfo:
    if otype == int:
        return TypeInfo(type="int")
    if otype == float:
        return TypeInfo(type="float")
    if otype == bool:
        return TypeInfo(type="bool")
    if otype == str:
        return TypeInfo(type="str")
    if otype in (None, NoneType):
        return TypeInfo(type="null")
    if otype == Any:
        return TypeInfo(type="any")

    torigin = get_origin(otype)
    targs = get_args(otype)
    if torigin is list or otype is list:
        if len(targs) != 1:
            return TypeInfo(type="list", list_type=type_info(Any, types))
        return TypeInfo(type="list", list_type=type_info(targs[0], types))
    if torigin is tuple or otype is tuple:
        return TypeInfo(type="tuple", tuple_type=[type_info(t, types) for t in targs])
    if torigin is dict or otype is dict:
        if len(targs) != 2:
            return TypeInfo(type="dict", dict_type=(type_info(Any, types), type_info(Any, types)))
        return TypeInfo(type="dict", dict_type=(type_info(targs[0], types), type_info(targs[1], types)))
    if torigin in (UnionType, Union):
        return TypeInfo(type="union", union_type=[type_info(t, types) for t in targs])
    if torigin is Literal:
        return TypeInfo(type="literal", literal=[(v if type(v) in (str, int, bool, None) else str(v)) for v in targs])
    if torigin is JsonSingleKey:
        k = targs[0]
        if get_origin(k) is Literal:
            k = get_args(k)[0]
        return TypeInfo(type="object", object_fields=[
            TypeInfoField(name=k, type=type_info(targs[1], types))
        ])

    optional_fields: list[str] = []
    field_descriptions: dict[str, str] = {}
    field_defaults: dict[str, Any] = {}
    try:
        if issubclass(otype, JsonObj):
            type_hints = otype.get_field_types()
            optional_fields = otype.get_optional_fields()
            field_descriptions = otype.get_field_descriptions()
            field_defaults = otype.get_field_defaults()
        else:
            type_hints = get_type_hints(otype)
            optional_fields = otype.__optional_keys__  # type: ignore
    except Exception:
        type_hints = get_type_hints(otype)
        optional_fields = otype.__optional_keys__  # type: ignore

    try:
        _, line = inspect.getsourcelines(otype)
    except Exception:
        line = 0
    tname = otype.__module__ + "." + otype.__name__
    if tname not in types:
        tinfo = TypeInfo(type="object", name=tname, line=line)
        types[tname] = tinfo
        tinfo.object_fields = [
            TypeInfoField(
                name=k,
                type=type_info(t, types),
                optional=k in optional_fields,
                desc=field_descriptions.get(k, None),
                default=field_defaults.get(k, Undefined),
            )
            for k, t in type_hints.items()
        ]

    return TypeInfo(type="tlink", name=tname)
