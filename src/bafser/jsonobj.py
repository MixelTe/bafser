import inspect
import json
from collections.abc import Callable as CallableClass
from dataclasses import dataclass
from datetime import datetime
from types import NoneType, UnionType
from typing import Any, Callable, Literal, TypeVar, Union, dataclass_transform, get_args, get_origin, get_type_hints, overload

from flask import abort, jsonify

from .utils import get_json_list, response_msg
from .utils.get_json_values_from_req import get_json_from_req


class UndefinedMeta(type):
    def __repr__(cls):
        return "Undefined"


class Undefined(metaclass=UndefinedMeta):
    def __init__(self):
        raise Exception("bafser: Undefined cant be instantiated")


type JsonOpt[T] = T | type[Undefined]


class JsonParseError(Exception):
    pass


@dataclass
class JsonField:
    default: Any
    default_factory: Callable[[], Any] | None
    desc: str | None
    repr: bool


@overload
def _field(*, default_factory: Callable[[], Any], desc: str | None = None, init: bool = True, repr: bool = True) -> Any:
    ...


@overload
def _field(*, default: Any = Undefined, desc: str | None = None, init: bool = True, repr: bool = True) -> Any:
    ...


def _field(*,
           default: Any = Undefined,
           default_factory: Callable[[], Any] | None = None,
           desc: str | None = None,
           init: bool = True,
           repr: bool = True,
           ) -> Any:
    """Configure object field"""
    return JsonField(default=default, default_factory=default_factory, desc=desc, repr=repr)


def _noinit_value[T](value: T, *, init: bool = False) -> T:
    return value


def _constructor_to_init[T](cls: type[T]) -> type[T]:
    cls.__init__ = cls.__constructor__  # type: ignore
    return cls


@dataclass_transform(kw_only_default=True, eq_default=False, field_specifiers=(JsonField, _field, _noinit_value))
@_constructor_to_init
class JsonObj:
    """
    Working with json via obj::

        class SomeObj(JsonObj):
            value: int  # required field
            isCool: JsonOpt[bool]  # optional field
            isCool: JsonOpt[bool] = Undefined  # optional field in __init__ also
            name: str = "anonym"  # optional field with default value
            name: str = JsonObj.field(default="anonym", desc="The name of obj")  # same as prev but with description
            value: int = JsonObj.field(desc="Required field with description")
            some2: JsonOpt[SomeObj2]  # nested JsonObjs are supported
            some: JsonOpt["SomeObj"]  # recursive JsonObjs are supported
            one = 1  # ignored if no type alias
            _one: int = 1  # ignored if starts with _
            _one: int = JsonObj.noinit_value(1)  # same but removed from __init__ type check

    Usage::

        from bafser import JsonObj, JsonOpt, Undefined, JsonParseError

        # no validation, only parsing
        obj = SomeObj(a=1, ...})
        obj = SomeObj.new({"a": 1, ...})
        obj = SomeObj.parse('json string')

        # with validation
        obj = SomeObj.get_from_req()
        obj = SomeObj.get_from_req("some_obj")
        objs = SomeObj.get_list_from_req()

        # validation
        error = obj.validate()
        # or
        is_valid = obj.is_valid()
        # or
        obj.valid()  # raises JsonParseError if not valid
        obj = SomeObj.new(json).valid()  # can be chained

        # get values
        name = obj.name
        obj.items()  # -> list[tuple[key, value]]
        obj.dict()  # -> dict[key, value] (doesnt call nested JsonObj.dict())

        # convert to json
        obj.json()  # -> dict[key, value] (calls nested JsonObj.json())
        obj.dumps()  # -> str
        obj.jsonify()  # -> Response

    Override `__repr_fields__` to change __repr__::

        __repr_fields__ = ["name"]
        # str(obj) -> SomeObj(name='anonym')
        # or use repr param in JsonObj.field:
        value: int = JsonObj.field(repr=False)

    Override `__datetime_parser__` and `__datetime_serializer__`. Called if `_parse` and `_serialize` dont convert value::

        __datetime_parser__ = datetime.fromisoformat
        __datetime_serializer__ = datetime.isoformat

    Override `_parse` to map keys and add custom parser::

        @override
        def _parse(self, key: str, v: Any, json: dict[str, Any]):
            if key == "from":
                return "frm", v
            if key == "char":
                if not isinstance(v, str) or len(v) != 1:
                    raise JsonParseError("must be a single character string")
                return key, v.lower()
            return None

    Override `_serialize` to map keys and add custom serializer::

        @override
        def _serialize(self, key: str, v: Any):
            if key == "rect" and isinstance(v, MyRect):
                return key, v.get_dict()

    Access types for complex logic::

        get_type_hints() -> dict[str, Any]
        get_field_types() -> dict[str, Any]  # JsonOpt[T] replaced with T
        get_optional_fields() -> list[str]  # list of JsonOpt[T] fields
        get_field_descriptions() -> dict[str, str]
        get_field_defaults() -> dict[str, Any]

    Unions are supported::

        class ObjD(JsonObj):
            name: Literal["d"]
            d: int
        class ObjV(JsonObj):
            name = Literal["v"]
            v: str

        class SomeObj(JsonObj):
            objs: list[ObjD | ObjV]
    """
    __repr_fields__: list[str] | None = _noinit_value(None)
    __datetime_parser__: Callable[[Any], datetime] = _noinit_value(datetime.fromisoformat)
    __datetime_serializer__: Callable[[datetime], Any] = _noinit_value(datetime.isoformat)

    field = _field
    noinit_value = _noinit_value

    def __init_subclass__(cls):
        type_hints = inspect.get_annotations(cls)
        repr_fields: list[str] = []
        cls.__fields__ = {}
        for k in type_hints:
            add_to_repr = not k.startswith("_")
            if hasattr(cls, k):
                v = getattr(cls, k)
                if isinstance(v, JsonField):
                    cls.__fields__[k] = v
                    setattr(cls, k, v.default)
                    if not v.repr:
                        add_to_repr = False
            else:
                setattr(cls, k, Undefined)
            if add_to_repr:
                repr_fields.append(k)
        if cls.__repr_fields__ is None:
            cls.__repr_fields__ = repr_fields

    def __constructor__(self, **data: Any):
        # self._exceptions: list[tuple[str, Exception]] = []
        self.__exceptions__: list[tuple[str, JsonParseError]] = []

        type_hints = self.get_type_hints()
        for k, v in self.__fields__.items():
            if v.default_factory:
                setattr(self, k, v.default_factory())

        for k, v in data.items():
            if not isinstance(v, object):
                continue
            t = type_hints.get(k, None)
            k, v = self.__parse_item__(k, v, t, data)
            if k is not None:
                setattr(self, k, v)

    @classmethod
    def new(cls, json: object):
        """Create obj from `json: dict[str, Any]` (without validation)"""

        if isinstance(json, dict):
            return cls(**json)
        return cls()

    def __parse_item__(self, k: str, v: object, t: Any, json: dict[str, Any]) -> tuple[str | None, Any]:
        type_hints = self.get_type_hints()
        try:
            r = self._parse(k, v, json)
            if r is not None:
                k, v = r
                t = type_hints.get(k, None)
        # except Exception as x:
        except JsonParseError as x:
            self.__exceptions__.append((k, x))

        if k not in type_hints:
            return None, v

        torigin = get_origin(t)
        targs = get_args(t)
        if isinstance(t, type) and issubclass(t, JsonObj):
            if not isinstance(v, JsonObj):
                v = t.new(v)
        elif torigin is list and len(targs) == 1 and isinstance(v, list):
            t = targs[0]
            l: list[Any] = []
            for el in v:  # pyright: ignore[reportUnknownVariableType]
                if not isinstance(el, object):
                    continue
                k2, el = self.__parse_item__(k, el, t, json)
                if el is not Undefined and k2 is not None:
                    l.append(el)
            v = l
        elif t == datetime and not isinstance(v, datetime):
            try:
                v = self.__datetime_parser__(v)
            except Exception:
                pass
        return k, v

    def _parse(self, key: str, v: Any, json: dict[str, Any]) -> tuple[str, Any] | None:
        return None

    @classmethod
    def get_type_hints(cls):
        if cls.__type_hints__ is None:
            return cls.__get_type_hints__()
        return cls.__type_hints__

    @classmethod
    def get_field_types(cls):
        if cls.__type_hints__ is None:
            cls.__get_type_hints__()
        return cls.__field_types__

    @classmethod
    def get_optional_fields(cls):
        if cls.__type_hints__ is None:
            cls.__get_type_hints__()
        return cls.__optional_fields__

    @classmethod
    def get_field_descriptions(cls):
        if cls.__type_hints__ is None:
            cls.__get_type_hints__()
        return {k: v.desc for k, v in cls.__fields__.items() if v.desc is not None}

    @classmethod
    def get_field_defaults(cls):
        type_hints = cls.get_type_hints()
        return {k: getattr(cls, k) for k in type_hints if hasattr(cls, k)}

    __type_hints__: dict[str, Any] | None = _noinit_value(None)
    __fields__: dict[str, JsonField] = _noinit_value({})
    __field_types__: dict[str, Any] = _noinit_value({})
    __optional_fields__: list[str] = _noinit_value([])

    @classmethod
    def __get_type_hints__(cls):
        type_hints = get_type_hints(cls)
        for k in list(type_hints.keys()):
            if k.startswith("_"):
                del type_hints[k]
        cls.__type_hints__ = type_hints
        cls.__field_types__ = {}
        cls.__optional_fields__ = []
        for k, t in type_hints.items():
            torigin = get_origin(t)
            targs = get_args(t)
            if torigin is JsonOpt and len(targs) == 1:
                cls.__optional_fields__.append(k)
                t = targs[0]
            cls.__field_types__[k] = t

        return type_hints

    @classmethod
    def parse(cls, data: str | bytes | bytearray):
        """Deserialize data to obj (without validation)"""
        try:
            obj = json.loads(data)
        except Exception:
            obj: Any = {}
        return cls.new(obj)

    @classmethod
    def get_from_req(cls, key: str | None = None):
        """
        Create obj from request body. Calls `flask.abort` on validation fail.

        :param key: if `key` is specified, the obj data will be obtained from the json field `key` in the request body
        """
        data = get_json_from_req(dict)  # type: ignore
        if key is not None:
            if key not in data:
                abort(response_msg(f"{key} is undefined", 400))
            data = data[key]  # type: ignore
        obj = cls.new(data)  # type: ignore
        err = obj.validate()
        if err is not None:
            abort(response_msg(err, 400))
        return obj

    @classmethod
    def get_list_from_req(cls):
        """Create list of objs from request body. Calls `flask.abort` on validation fail."""
        data = get_json_from_req(list)  # type: ignore
        data, err = get_json_list(data, cls)  # type: ignore
        if err is not None:
            abort(response_msg(err, 400))
        return data

    def __repr__(self) -> str:
        params = ", ".join(
            f"{k}={repr(v)}" for (k, v) in self.items()
            if self.__repr_fields__ is None or k in self.__repr_fields__
        )
        return type(self).__name__ + f"({params})"

    def validate(self):
        """Validate data and return error if any"""
        type_hints = self.get_type_hints()
        r: str | None = None
        for k, t in type_hints.items():
            v = getattr(self, k)
            try:
                _, err = validate_type(v, t, True)
                if err:
                    r = k + err
                    break
            # except Exception as x:
            except JsonParseError as x:
                self.__exceptions__.append((k, x))
        if len(self.__exceptions__) != 0:
            k, x = self.__exceptions__[0]
            if k in type_hints:
                t = type_hints[k]
                return f"{k} is not {type_name(t)}: {x}"
            return f"{k}: {x}"
        return r

    def is_valid(self):
        """Validate data"""
        return self.validate() is None

    def valid(self):
        """
        Validate data and raise error if any

        :raises JsonParseError: if there is any error
        """
        err = self.validate()
        if len(self.__exceptions__) != 0:
            _, x = self.__exceptions__[0]
            raise x
            # if isinstance(x, JsonParseError):
            #     raise x
            # raise JsonParseError(repr(x)).with_traceback(x.__traceback__)
        if err is not None:
            raise JsonParseError(err)
        return self

    def items(self):
        """Get all values as pairs (key, value)"""
        return [(key, getattr(self, key)) for key in self.get_type_hints()]

    def dict(self):
        """Get all values as dict"""
        return {k: v for (k, v) in self.items()}

    def json(self):
        """Get data as serializable dict"""
        r: dict[str, Any] = {}
        for k, v in self.items():
            k, v = self.__serialize_item__(k, v)
            if v is Undefined:
                continue
            r[k] = v
        return r

    def __serialize_item__(self, k: str, v: Any):
        if v is Undefined:
            return k, Undefined
        s = self._serialize(k, v)
        if s is not None:
            k, v = s
        if isinstance(v, JsonObj):
            v = v.json()
        elif isinstance(v, datetime):
            v = type(self).__datetime_serializer__(v)
        elif isinstance(v, (list, tuple)):
            r: list[Any] = []
            for i, el in enumerate(v):  # type: ignore
                _, el = self.__serialize_item__(k, el)  # type: ignore
                if el is not Undefined:
                    r.append(el)
            v = r
        elif isinstance(v, dict):
            d: dict[Any, Any] = {}
            for dk, dv in v.items():  # pyright: ignore[reportUnknownVariableType]
                _, dv = self.__serialize_item__(k, dv)  # type: ignore
                if dv is not Undefined:
                    d[dk] = dv
            v = d
        return k, v

    def _serialize(self, key: str, v: Any) -> tuple[str, Any] | None:
        return None

    def dumps(self, indent: int | str | None = None):
        """Serialize obj to a JSON formatted str"""
        return json.dumps(self.json(), indent=indent)

    def jsonify(self):
        """
        Serialize the given arguments as JSON, and return a
        :class:`~flask.Response` object with the ``application/json``
        mimetype.
        """
        return jsonify(self.json())


type ValidateType = dict[str, ValidateType] | int | float | bool | str | object | None | list[Any]
TC = TypeVar("TC", bound=ValidateType)


def validate_type(obj: Any, otype: type[TC], r: bool = False) -> tuple[TC, None] | tuple[None, str]:
    """Supports int, float, bool, str, object, None, list, dict, list['type'],
    dict['type', 'type'], Union[...], TypedDict, JsonObj, JsonOpt, Literal"""
    if otype is Any:  # type: ignore
        return obj, None  # type: ignore
    # simple type
    try:
        isinstance(obj, otype)
        good_type = True
    except Exception:
        good_type = False
    if good_type and isinstance(otype, type):  # type: ignore
        if type(obj) is bool:  # handle isinstance(True, int) is True
            if otype is bool:
                return obj, None  # type: ignore
        if issubclass(otype, JsonObj):
            if not isinstance(obj, JsonObj):
                obj = otype.new(obj)
            err = obj.validate()
            if r and len(obj.__exceptions__) != 0:  # pyright: ignore[reportPrivateUsage]
                k, x = obj.__exceptions__[0]  # pyright: ignore[reportPrivateUsage]
                if isinstance(x, JsonParseError):
                    raise x
                raise JsonParseError(repr(x)).with_traceback(x.__traceback__)
            if err is None:
                return obj, None  # type: ignore
            return None, "." + err
        if isinstance(obj, otype):
            return obj, None  # type: ignore
        if obj is Undefined:
            return None, " is undefined"
        return None, f" is not {type_name(otype)}"

    torigin = get_origin(otype)
    targs = get_args(otype)

    # JsonOpt
    if torigin is JsonOpt and len(targs) == 1:
        t = targs[0]
        if obj is Undefined:
            return obj, None  # type: ignore
        obj, err = validate_type(obj, t, r)
        if err is None:
            return obj, None
        return None, f" is not {type_name(t)}"

    if obj is Undefined:
        return None, " is undefined"

    if torigin is Literal:
        for t in targs:
            if obj == t:
                return obj, None
        return None, f" is not {type_name(otype)}"

    # generic list
    if torigin is list and len(targs) == 1:
        t = targs[0]
        if not isinstance(obj, (list, tuple)):
            return None, f" is not {type_name(otype)}"
        l: list[Any] = []
        for i, el in enumerate(obj):  # type: ignore
            o, err = validate_type(el, t, r)
            if err is not None:
                return None, f"[{i}]{err}"
            l.append(o)
        return l, None  # type: ignore

    # tuple
    if torigin is tuple:
        if not isinstance(obj, (list, tuple)) or len(obj) != len(targs):  # type: ignore
            return None, f" is not {type_name(otype)}"
        t = targs[0]
        l: list[Any] = []
        for i, el in enumerate(obj):  # type: ignore
            o, err = validate_type(el, t, r)
            if err is not None:
                return None, f"[{i}]{err}"
            l.append(o)
        return tuple(l), None  # type: ignore

    # generic dict
    if torigin is dict and len(targs) == 2:
        tk = targs[0]
        tv = targs[1]
        if not isinstance(obj, dict):
            return None, f" is not {type_name(otype)}"
        d: dict[Any, Any] = {}
        for k, v in obj.items():  # type: ignore
            d[k] = v
            if tk != Any:
                _, err = validate_type(k, tk, r)
                if err is not None:
                    return None, f" key '{k}'{err}"
            if tv != Any:
                d[k], err = validate_type(v, tv, r)
                if err is not None:
                    return None, f".{k}{err}"
        return d, None  # type: ignore

    # Union
    if torigin in (UnionType, Union):
        for t in targs:
            o, err = validate_type(obj, t, r)
            if err is None:
                return o, None  # type: ignore
        return None, f" is not {type_name(otype)}"

    # TypedDict
    try:
        type_hints = get_type_hints(otype)
        opt_keys: frozenset[str] = otype.__optional_keys__  # type: ignore
    except (TypeError, AttributeError):
        raise Exception("[bafser] validate_type: unsupported type")

    if not isinstance(obj, dict):
        return None, f" is not {otype}"
    d: dict[Any, Any] = {}
    for k, t in type_hints.items():
        d[k] = obj[k]
        if k not in obj:
            if k in opt_keys:
                continue
            return None, f" field is missing '{k}': {type_name(t)}"
        d[k], err = validate_type(obj[k], t, r)
        if err is not None:
            return None, f" field '{k}' {err}"

    return d, None  # type: ignore


def type_name(t: Any, json: bool = False) -> str:
    if t in (NoneType, None):
        return "null" if json else "None"
    torigin = get_origin(t)
    targs = get_args(t)
    if torigin is list and len(targs) == 1:
        if json:
            to = get_origin(targs[0])
            if to in (UnionType, Union, CallableClass):
                return f"({type_name(targs[0], json)})[]"
            return f"{type_name(targs[0], json)}[]"
        return f"list[{type_name(targs[0], json)}]"
    if torigin is tuple:
        return f"tuple[{", ".join(type_name(v, json) for v in targs)}]"
    if torigin is dict and len(targs) == 2:
        if json:
            return f"{{[key: {type_name(targs[0], json)}]: {type_name(targs[1], json)}}}"
        return f"dict[{type_name(targs[0], json)}, {type_name(targs[1], json)}]"
    if torigin in (UnionType, Union):
        return " | ".join(type_name(v, json) for v in targs)
    if torigin is Literal:
        return " | ".join(repr(v) for v in targs)
    if torigin is CallableClass and len(targs) == 2:
        if json:
            return f"({", ".join(type_name(v, json) for v in targs[0])}) => {type_name(targs[1], json)}"
        return f"({", ".join(type_name(v, json) for v in targs[0])}) -> {type_name(targs[1], json)}"
    if json:
        if t in (int, float):
            return "number"
        if t == bool:
            return "boolean"
        if t == str:
            return "string"
    try:
        return t.__name__
    except Exception:
        return str(t)
