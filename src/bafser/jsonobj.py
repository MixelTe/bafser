from datetime import datetime
import json
from types import NoneType, UnionType
from typing import Any, Callable, TypeVar, get_args, get_origin, get_type_hints

from flask import jsonify


class JsonObj:
    """
    Working with json via obj::

        class SomeObj(JsonObj):
            value: int  # required field
            isCool: JsonOpt[bool]  # optional field
            name: str = "anonym"  # optional field with default
            some: JsonOpt[SomeObj]  # nested JsonObjs are supported
            some = 1  # ignored if no type alias
            __some: int = 1  # ignored if starts with __

    Usage::

        from bafser import JsonObj, JsonOpt, Undefined, JsonParseError

        json = {"a": 1, ...}
        obj = SomeObj(json)  # no validation, only parsing
        # or
        obj = SomeObj.parse('json string')

        # validation
        error = obj.validate()
        # or
        is_valid = obj.is_valid()
        # or
        obj.valid()  # raises JsonParseError if not valid
        obj = SomeObj(json).valid()  # can be chained

        # get values
        name = obj.name
        obj.items()  # list[tuple[key, value]]
        obj.dict()  # dict[key, value] (dont call nested JsonObj.dict())

        # convert to json
        obj.json()  # dict[key, value] (call nested JsonObj.json())
        obj.dumps()  # str
        obj.jsonify()  # Response

    Override `__repr_fields__` to change __repr__::

        __repr_fields__ = ["name"]
        # str(obj) -> SomeObj(name='anonym')

    Override `__datetime_parser__` and `__datetime_serializer__`. Called if `_parse` and `_serialize` dont convert value::

        __datetime_parser__ = datetime.fromisoformat
        __datetime_serializer__ = datetime.isoformat

    Override `_parse` to map keys and add custom parser::

        @override
        def _parse(self, key: str, v: Any, json: dict[str, Any]):
            if key == "from":
                return "frm", v
            if key == "rect":
                return key, MyRect(v)
            return None

    Override `_serialize` to map keys and add custom serializer::

        @override
        def _serialize(self, key: str, v: Any):
            if key == "rect" and isinstance(v, MyRect):
                return key, v.get_dict()

    Access types for complex logic::

        __type_hints: dict[str, Any]
        __field_types: dict[str, Any]  # JsonOpt[T] replaced with T
        __optional_fields: list[str]  # list of JsonOpt[T] fields
    """
    __repr_fields__: list[str] | None = None
    __datetime_parser__: Callable[[Any], datetime] = datetime.fromisoformat
    __datetime_serializer__: Callable[[datetime], Any] = datetime.isoformat

    def __init__(self, json: object):
        self.__exceptions: list[tuple[str, Exception]] = []
        for k in self.__type_hints:
            if not hasattr(self, k):
                setattr(self, k, undefined)

        if not isinstance(json, dict):
            return

        for k, v in json.items():  # pyright: ignore[reportUnknownVariableType]
            if not isinstance(k, str) or not isinstance(v, object):
                continue
            try:
                r = self._parse(k, v, json)  # pyright: ignore[reportUnknownArgumentType]
                if r is not None:
                    k, v = r
            except Exception as x:
                self.__exceptions.append((k, x))

            if k not in self.__type_hints:
                continue

            t = self.__type_hints[k]
            if isinstance(t, type) and issubclass(t, JsonObj):
                v = t(v)
            elif t == datetime and not isinstance(v, datetime):
                try:
                    v = self.__datetime_parser__(v)
                except Exception:
                    pass

            setattr(self, k, v)

    def _parse(self, key: str, v: Any, json: dict[str, Any]) -> tuple[str, Any] | None:
        return None

    def __init_subclass__(cls):
        type_hints = get_type_hints(cls)
        for k in list(type_hints.keys()):
            if k.startswith("__"):
                del type_hints[k]
        cls.__type_hints = type_hints
        cls.__field_types: dict[str, Any] = {}
        cls.__optional_fields: list[str] = []
        for k, t in type_hints.items():
            torigin = get_origin(t)
            targs = get_args(t)
            if torigin is JsonOpt and len(targs) == 1:
                cls.__optional_fields.append(k)
                t = targs[0]
            cls.__field_types[k] = t

    @classmethod
    def parse(cls, data: str):
        try:
            obj = json.loads(data)
        except Exception:
            obj: Any = {}
        return cls(obj)

    def __repr__(self) -> str:
        params = ", ".join(
            f"{k}={repr(v)}" for (k, v) in self.items()
            if self.__repr_fields__ is None or k in self.__repr_fields__
        )
        return type(self).__name__ + f"({params})"

    def validate(self):
        """Validate data and return error if any"""
        if len(self.__exceptions) != 0:
            k, x = self.__exceptions[0]
            if k in self.__type_hints:
                t = self.__type_hints[k]
                return f"{k} is not {type_names.get(t, t)}: {x}"
            return f"{k}: {x}"
        for k, t in self.__type_hints.items():
            v = getattr(self, k)
            _, err = validate_type(v, t)
            if err:
                return k + err
        return None

    def is_valid(self):
        return self.validate() is None

    def valid(self):
        """
        Validate data and raise error if any

        :raises JsonParseError: if there is any error
        """
        if len(self.__exceptions) != 0:
            _, x = self.__exceptions[0]
            raise JsonParseError(repr(x)).with_traceback(x.__traceback__)
        err = self.validate()
        if err is not None:
            raise JsonParseError(err)
        return self

    def items(self):
        return [(key, getattr(self, key)) for key in self.__type_hints]

    def dict(self):
        return {k: v for (k, v) in self.items()}

    def json(self):
        r: dict[str, Any] = {}
        for k, v in self.items():
            k, v = self.__serialize_item__(k, v)
            if v is undefined:
                continue
            r[k] = v
        return r

    def __serialize_item__(self, k: str, v: Any):
        if v is undefined:
            return k, undefined
        s = self._serialize(k, v)
        if s is not None:
            k, v = s
        if isinstance(v, JsonObj):
            v = v.json()
        elif isinstance(v, datetime):
            v = type(self).__datetime_serializer__(v)
        elif isinstance(v, list):
            r: list[Any] = []
            for el in v:  # pyright: ignore[reportUnknownVariableType]
                _, el = self.__serialize_item__(k, el)
                if el is not undefined:
                    r.append(el)
            v = r
        return k, v

    def _serialize(self, key: str, v: Any) -> tuple[str, Any] | None:
        return None

    def dumps(self):
        return json.dumps(self.json())

    def jsonify(self):
        return jsonify(self.json())


class JsonParseError(Exception):
    pass


class Undefined:
    def __repr__(self) -> str:
        return "Undefined"

    def __str__(self) -> str:
        return self.__repr__()


undefined = Undefined()
type JsonOpt[T] = T | Undefined


class SomeDict2(JsonObj):
    value: int
    date: datetime
    isCool: JsonOpt[bool]
    name: str = "anonym"
    name_opt: JsonOpt[str] = "anonym"

    some_var = 5

    def some_fn(self) -> bool:
        return True


class SomeDict(JsonObj):
    name: str
    keys: list[int | str]
    v: list[SomeDict2]


type ValidateType = dict[str, ValidateType] | int | float | bool | str | object | None | list[Any]
TC = TypeVar("TC", bound=ValidateType)

type_names: dict[Any, str] = {
    int: "int",
    float: "float",
    bool: "bool",
    str: "str",
    object: "object",
    list: "list",
    dict: "dict",
    NoneType: "None",
    datetime: "datetime"
}


def validate_type(obj: Any, otype: type[TC]) -> tuple[TC, None] | tuple[None, str]:
    """Supports int, float, bool, str, object, None, list, dict, list['type'], dict['type', 'type'], Union[...], TypedDict"""
    # simple type
    if isinstance(otype, type):  # type: ignore
        if type(obj) is bool:  # handle isinstance(True, int) is True
            if otype is bool:
                return obj, None  # type: ignore
        elif isinstance(obj, otype):
            return obj, None  # type: ignore
        if obj is undefined:
            return None, " is undefined"
        return None, f" is not {type_names.get(otype, otype)}"

    # generic list
    torigin = get_origin(otype)
    targs = get_args(otype)
    if torigin is list and len(targs) == 1:
        t = targs[0]
        if not isinstance(obj, list):
            return None, f" is not {otype}"
        for i, el in enumerate(obj):  # type: ignore
            _, err = validate_type(el, t)
            if err is not None:
                return None, f"[{i}]{err}"
        return obj, None  # type: ignore

    # generic dict
    if torigin is dict and len(targs) == 2:
        tk = targs[0]
        tv = targs[1]
        if not isinstance(obj, dict):
            return None, f" is not {otype}"
        for k, v in obj.items():  # type: ignore
            if tk != Any:
                _, err = validate_type(k, tk)
                if err is not None:
                    return None, f" key '{k}'{err}"
            if tv != Any:
                _, err = validate_type(v, tv)
                if err is not None:
                    return None, f".{k}{err}"
        return obj, None  # type: ignore

    # Union
    if torigin is UnionType:
        for t in targs:
            _, err = validate_type(obj, t)
            if err is None:
                return obj, None
        return None, f" is not {otype}"

    # JsonOpt
    if torigin is JsonOpt and len(targs) == 1:
        t = targs[0]
        if obj is undefined:
            return obj, None
        _, err = validate_type(obj, t)
        if err is None:
            return obj, None
        return None, f" is not {type_names.get(t, t)}"

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
