from functools import partial

from sqlalchemy import String
from sqlalchemy.orm import Mapped, declared_attr, mapped_column
from typing_extensions import assert_type

from bafser import (
    IdMixin,
    NormalizationError,
    NormalizedValueTooLongError,
    SqlAlchemyBase,
    normalize_search,
    normalized_column,
    normalized_update_values,
)


class SearchModel(SqlAlchemyBase, IdMixin):
    __tablename__ = "typing_search_model"
    title: Mapped[str] = mapped_column(String(64))
    title_search: Mapped[str] = normalized_column(title, length=128)
    title_full: Mapped[str] = normalized_column(title)
    title_short: Mapped[str] = normalized_column(title, length=8, overflow="truncate")
    alias: Mapped[str | None] = mapped_column(String(64), default=None)
    alias_search: Mapped[str | None] = normalized_column(alias, length=128)


class SearchSource(SqlAlchemyBase, IdMixin):
    __abstract__ = True
    title: Mapped[str] = mapped_column(String(64))


class InheritedSearch(SearchSource):
    __tablename__ = "typing_inherited_search"

    @declared_attr
    @classmethod
    def title_search(cls) -> Mapped[str]:
        return normalized_column(cls.title, length=128)


model = SearchModel(title="Name")
assert_type(model.title_search, str)
assert_type(model.title_full, str)
assert_type(model.title_short, str)
assert_type(model.alias_search, str | None)
assert_type(InheritedSearch(title="Name").title_search, str)
assert_type(normalize_search("Name"), str)
assert_type(normalize_search("Яна", cyrillic_to_latin=True), str)
assert_type(NormalizationError(), NormalizationError)
assert_type(NormalizedValueTooLongError(), NormalizedValueTooLongError)
normalizer = partial(normalize_search, cyrillic_to_latin=True)
assert_type(normalizer("Ёлка"), str)
values = normalized_update_values(SearchModel, title="Name")
