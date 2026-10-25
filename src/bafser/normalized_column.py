# pyright: reportUnnecessaryIsInstance=false
"""Stored search strings derived from explicitly referenced ORM columns."""

import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, TypeVar
from weakref import WeakKeyDictionary

from sqlalchemy import Column, String, Text, and_, event, inspect, or_, select
from sqlalchemy.orm import ColumnProperty, InstrumentedAttribute, Mapped, MappedColumn, Mapper, Session, mapped_column, undefer
from sqlalchemy.orm.base import NO_VALUE
from sqlalchemy.orm.exc import UnmappedColumnError
from sqlalchemy.sql.elements import ClauseElement
from sqlalchemy.types import TypeDecorator

from .truncate_string import TruncateString

TString = TypeVar("TString", bound=str | None)
_SPEC_KEY = "_bafser_normalized_column"
_CYRILLIC_TO_LATIN = str.maketrans(
    {
        "а": "a",
        "б": "b",
        "в": "v",
        "г": "g",
        "д": "d",
        "е": "e",
        "ё": "yo",
        "ж": "zh",
        "з": "z",
        "и": "i",
        "й": "y",
        "к": "k",
        "л": "l",
        "м": "m",
        "н": "n",
        "о": "o",
        "п": "p",
        "р": "r",
        "с": "s",
        "т": "t",
        "у": "u",
        "ф": "f",
        "х": "h",
        "ц": "ts",
        "ч": "ch",
        "ш": "sh",
        "щ": "sch",
        "ъ": "",
        "ы": "y",
        "ь": "",
        "э": "e",
        "ю": "yu",
        "я": "ya",
    }
)


class NormalizationError(ValueError):
    """A source value or normalizer cannot produce a stored search string."""


class NormalizedValueTooLongError(NormalizationError):
    """The normalized string exceeds the declared column length."""


def normalize_search(
    value: str,
    *,
    replace_yo: bool = True,
    strip_diacritics: bool = True,
    strip_punctuation: bool = True,
    cyrillic_to_latin: bool = False,
    transliterate: Callable[[str], str] | None = None,
) -> str:
    """NFKC/casefold, fold ё/diacritics, replace punctuation and collapse spaces.

    Punctuation becomes whitespace, rather than joining adjacent words.
    Removing diacritics also changes Cyrillic й to и. Optional Russian-to-Latin
    transliteration runs after ё/diacritic folding; other letters are preserved.
    A custom transliterator receives NFKC/casefold text before those transforms
    and must return a string.
    """
    if not isinstance(value, str):
        raise TypeError("normalize_search expects a string")
    value = unicodedata.normalize("NFKC", value).casefold()
    if transliterate is not None:
        value = transliterate(value)
        if not isinstance(value, str):
            raise TypeError("transliterate must return a string")
        value = unicodedata.normalize("NFKC", value).casefold()
    if replace_yo:
        value = value.replace("ё", "е")
    if strip_diacritics:
        value = "".join(char for char in unicodedata.normalize("NFD", value) if not unicodedata.category(char).startswith("M"))
    value = unicodedata.normalize("NFKC", value)
    if cyrillic_to_latin:
        value = value.translate(_CYRILLIC_TO_LATIN)
    if strip_punctuation:
        value = "".join(" " if unicodedata.category(char).startswith("P") else char for char in value)
    return " ".join(value.split())


@dataclass(frozen=True)
class _Spec:
    source: Any
    length: int | None
    normalizer: Callable[[str], str]
    nullable: bool | None
    overflow: Literal["raise", "truncate"] | None


@dataclass(frozen=True)
class _Binding:
    source_key: str
    target_key: str
    source_type: Any
    nullable: bool
    length: int | None
    normalizer: Callable[[str], str]
    has_insert_default: bool
    overflow: Literal["raise", "truncate"]

    def normalize(self, value: Any, model: type, *, inserting: bool = False) -> str | None:
        label = f"{model.__name__}.{self.target_key}"
        if value is None and inserting and self.has_insert_default and not self.source_type.should_evaluate_none:
            raise NormalizationError(f"{label}: {self.source_key} has an INSERT default; provide a concrete string")
        if value is None and self.nullable:
            return None
        if not isinstance(value, str):
            raise NormalizationError(f"{label}: {self.source_key} requires a concrete string" + (" or None" if self.nullable else ""))
        if isinstance(self.source_type, TruncateString):
            value = self.source_type.prepare_value(value)
        try:
            result = self.normalizer(value)
        except Exception as exc:
            raise NormalizationError(f"{label}: normalizer failed") from exc
        if not isinstance(result, str):
            raise NormalizationError(f"{label}: normalizer must return a string")
        if self.length is not None and len(result) > self.length:
            if self.overflow == "truncate":
                return result[: self.length]
            raise NormalizedValueTooLongError(f"{label}: normalized length {len(result)} exceeds {self.length}")
        return result


_BINDINGS: WeakKeyDictionary[Mapper[Any], tuple[_Binding, ...]] = WeakKeyDictionary()
_LISTENERS: WeakKeyDictionary[type, set[str]] = WeakKeyDictionary()


def normalized_column(
    source: Mapped[TString] | MappedColumn[TString] | Column[TString],
    *,
    length: int | None = None,
    normalizer: Callable[[str], str] = normalize_search,
    overflow: Literal["raise", "truncate"] | None = None,
    **kwargs: Any,
) -> MappedColumn[TString]:
    """Declare an init=False search column derived from a referenced string field.

    Without length, store the full result in Text. With length, use String(length)
    and truncate overflow for TruncateString sources, otherwise raise. Explicit
    overflow overrides that choice; it has no effect without a length limit.

    Reference a mapped_column declared above, or use declared_attr with cls.field
    for inherited sources. Strings, relationships and SQL expressions are invalid.
    Pass normal mapped_column options such as index, nullable and a database name.
    """
    if not isinstance(source, (MappedColumn, InstrumentedAttribute, Column)):
        raise TypeError("normalized_column source must be a column attribute, not a name or expression")
    if length is not None and (type(length) is not int or length < 1):
        raise ValueError("normalized_column length must be a positive integer")
    if overflow not in (None, "raise", "truncate"):
        raise ValueError("normalized_column overflow must be 'raise', 'truncate' or None")
    if not callable(normalizer):
        raise TypeError("normalized_column normalizer must be callable")
    if kwargs.pop("init", False) is not False:
        raise ValueError("normalized_column is always init=False")
    managed = {"default", "default_factory", "insert_default", "onupdate", "server_default", "server_onupdate", "primary_key"}
    if managed.intersection(kwargs):
        raise ValueError("normalized_column cannot have defaults, onupdate or a primary key")
    info = dict(kwargs.pop("info", {}))
    nullable = kwargs.get("nullable")
    if nullable is not None and type(nullable) is not bool:
        raise TypeError("normalized_column nullable must be a boolean")
    info[_SPEC_KEY] = _Spec(source, length, normalizer, nullable, overflow)
    column_type = Text() if length is None else String(length)
    return mapped_column(column_type, init=False, info=info, **kwargs)


def _source_property(mapper: Mapper[Any], source: Any) -> ColumnProperty[Any]:
    if isinstance(source, InstrumentedAttribute):
        owner = source.class_
        if not isinstance(owner, type) or not issubclass(mapper.class_, owner):
            raise TypeError("normalized_column source must belong to the model or an ancestor and map one column")
        prop = inspect(owner).get_property(source.key)  # type: ignore
        if not isinstance(prop, ColumnProperty) or len(prop.columns) != 1:
            raise TypeError("normalized_column source must map exactly one column")
        column = prop.columns[0]
    else:
        column: Any = source.column if isinstance(source, MappedColumn) else source  # type: ignore
    try:
        prop = mapper.get_property_by_column(column)
    except UnmappedColumnError:
        # Declarative copies mixin columns. Resolve the original declaration in
        # the MRO, never guess a source by its SQL column name.
        prop = None
        for base in mapper.class_.__mro__:
            for key, declaration in vars(base).items():
                if declaration is source and mapper.has_property(key):
                    prop = mapper.get_property(key)
                    break
            if prop is not None:
                break
        if prop is None:
            raise ValueError("normalized_column source is not mapped by this model") from None
    if not isinstance(prop, ColumnProperty) or len(prop.columns) != 1 or not isinstance(prop.columns[0], Column):
        raise TypeError("normalized_column source must map exactly one column")
    return prop


@event.listens_for(Mapper, "after_mapper_constructed")
def _configure_columns(mapper: Mapper[Any], model: type) -> None:
    bindings: list[_Binding] = []
    for prop in mapper.iterate_properties:
        if not isinstance(prop, ColumnProperty):
            continue
        specs = [column.info[_SPEC_KEY] for column in prop.columns if _SPEC_KEY in getattr(column, "info", {})]
        if not specs:
            continue
        if len(prop.columns) != 1:
            raise TypeError(f"{model.__name__}.{prop.key}: normalized field must map one column")
        target_column = prop.columns[0]
        if not isinstance(target_column, Column):
            raise TypeError(f"{model.__name__}.{prop.key}: normalized field must be a stored column")
        spec = specs[0]
        source = _source_property(mapper, spec.source)
        source_column = source.columns[0]
        if _SPEC_KEY in source_column.info:
            raise TypeError(f"{model.__name__}.{prop.key}: chains of normalized columns are not supported")
        source_type = source_column.type
        if type(source_type) is not TruncateString and (
            not isinstance(source_type, String)
            or isinstance(source_type, TypeDecorator)
            or type(source_type).bind_processor is not String.bind_processor
        ):
            raise TypeError(f"{model.__name__}.{prop.key}: source must use String or TruncateString")
        if source_column.computed is not None or source_column.onupdate is not None or source_column.server_onupdate is not None:
            raise ValueError(f"{model.__name__}.{prop.key}: generated/onupdate sources are not supported")
        if spec.nullable is None:
            target_column.nullable = source_column.nullable
        elif source_column.nullable != spec.nullable:
            raise TypeError(f"{model.__name__}.{prop.key}: nullable must match the source")
        bindings.append(
            _Binding(
                source.key,
                prop.key,
                source_type,
                source_column.nullable,
                spec.length,
                spec.normalizer,
                source_column.default is not None or source_column.server_default is not None,
                spec.overflow if spec.overflow is not None else ("truncate" if isinstance(source_type, TruncateString) else "raise"),
            )
        )
    _BINDINGS[mapper] = tuple(bindings)


@event.listens_for(Mapper, "mapper_configured")
def _configure_listeners(mapper: Mapper[Any], model: type) -> None:
    # Install after SQLAlchemy's @validates listeners, so the normalizer sees
    # their returned values. before_flush also covers later custom listeners.
    for source_key in {binding.source_key for binding in _BINDINGS.get(mapper, ())}:
        if not any(source_key in _LISTENERS.get(base, ()) for base in model.__mro__):
            event.listen(getattr(model, source_key), "set", _source_assigned, propagate=True)
            _LISTENERS.setdefault(model, set()).add(source_key)


def _source_assigned(target: Any, value: Any, oldvalue: Any, initiator: Any) -> None:
    state = inspect(target)
    values = [
        (binding.target_key, binding.normalize(value, type(target), inserting=state.transient or state.pending))  # pyright: ignore[reportUnknownArgumentType]
        for binding in _BINDINGS.get(state.mapper, ())
        if binding.source_key == initiator.key
    ]
    for key, normalized in values:
        setattr(target, key, normalized)


def _synchronize(obj: Any, bindings: tuple[_Binding, ...]) -> None:
    inserting = inspect(obj).pending
    values = [
        (binding.target_key, binding.normalize(getattr(obj, binding.source_key, NO_VALUE), type(obj), inserting=inserting))  # pyright: ignore[reportUnknownArgumentType]
        for binding in bindings
    ]
    for key, value in values:
        if getattr(obj, key, NO_VALUE) != value:
            setattr(obj, key, value)


@event.listens_for(Session, "before_flush")
def _before_flush(session: Session, flush_context: Any, instances: Any) -> None:
    for obj in tuple(session.new) + tuple(session.dirty):
        state = inspect(obj)
        if obj in session.deleted:
            continue
        bindings = tuple(
            binding
            for binding in _BINDINGS.get(state.mapper, ())
            if state.pending or state.attrs[binding.source_key].history.has_changes() or state.attrs[binding.target_key].history.has_changes()
        )
        if bindings:
            _synchronize(obj, bindings)


def _model_bindings(model: type) -> tuple[Mapper[Any], tuple[_Binding, ...]]:
    mapper = inspect(model)  # pyright: ignore[reportUnknownVariableType]
    if not isinstance(mapper, Mapper):
        raise TypeError("Expected a mapped model class")
    if not mapper.configured:
        mapper.registry.configure(cascade=True)
    return mapper, _BINDINGS.get(mapper, ())  # type: ignore


def normalized_update_values(model: type, /, **values: Any) -> dict[str, Any]:
    """Prepare concrete ORM UPDATE values and every affected normalized column.

    Keys are Python attribute names. Direct SQL and unwrapped bulk writes do not
    synchronize derived columns. No SQL is executed by this function.
    """
    mapper, bindings = _model_bindings(model)
    targets = {binding.target_key for binding in bindings}
    for key, value in values.items():
        if key not in mapper.column_attrs or key in targets:
            raise TypeError(f"{model.__name__}.{key}: expected a non-derived column")
        if isinstance(value, ClauseElement) or hasattr(value, "__clause_element__"):
            raise NormalizationError(f"{model.__name__}.{key}: SQL expressions are not supported")
    result = dict(values)
    for binding in bindings:
        if binding.source_key in values:
            result[binding.target_key] = binding.normalize(values[binding.source_key], model)
    return result


def rebuild_normalized_columns(model: type, *, db_sess: Session, batch_size: int = 500) -> int:
    """Recompute every row, including soft-deleted rows, without committing.

    Returns the number of processed rows. Flushes the supplied session; use a
    dedicated maintenance session and stop old writers during algorithm changes.
    Uses primary-key pages, not a streaming cursor open during UPDATE statements.
    """
    if type(batch_size) is not int or batch_size < 1:
        raise ValueError("batch_size must be a positive integer")
    mapper, bindings = _model_bindings(model)
    if not bindings:
        return 0
    keys = [mapper.get_property_by_column(column).key for column in mapper.primary_key]
    attributes = [getattr(model, key) for key in keys]
    db_sess.flush()
    last = None
    count = 0
    while True:
        statement: Any = select(model).options(undefer("*")).order_by(*attributes).limit(batch_size).execution_options(populate_existing=True)  # pyright: ignore[reportUnknownVariableType]
        if last is not None:
            statement = statement.where(
                or_(
                    *[
                        and_(*(attributes[previous] == last[previous] for previous in range(index)), attribute > last[index])
                        for index, attribute in enumerate(attributes)
                    ]
                )
            )
        batch = db_sess.execute(statement).unique().scalars().all()
        if not batch:
            return count
        last = tuple(getattr(batch[-1], key) for key in keys)
        for obj in batch:
            _synchronize(obj, bindings)
        db_sess.flush()
        count += len(batch)
