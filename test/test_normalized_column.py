"""Normalized column behavior on SQLite and an optional dedicated MySQL database."""

import os
import unittest
from functools import partial

from sqlalchemy import Index, MetaData, String, Text, create_engine, event, func, inspect, select, update
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateIndex
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, Session, declared_attr, mapped_column, registry, validates
from sqlalchemy.types import TypeDecorator

from bafser import (
    IdMixin, NormalizationError, NormalizedValueTooLongError, ObjMixin, SqlAlchemyBase, TruncateString,
    normalize_search, normalized_column, normalized_update_values, rebuild_normalized_columns,
)


class SearchBase(SqlAlchemyBase):
    __abstract__ = True
    metadata = MetaData()


class SearchItem(SearchBase, ObjMixin):
    __tablename__ = "bafser_search_items"
    name: Mapped[str] = mapped_column("display_name", TruncateString(32))
    name_search: Mapped[str] = normalized_column(name, length=96, index=True, normalizer=partial(normalize_search, cyrillic_to_latin=False))
    name_folded: Mapped[str] = normalized_column(name, length=96, normalizer=partial(normalize_search, replace_yo=True, cyrillic_to_latin=False))
    alias: Mapped[str | None] = mapped_column(String(64), default=None)
    alias_search: Mapped[str | None] = normalized_column(alias, length=128, normalizer=partial(normalize_search, cyrillic_to_latin=False))
    note: Mapped[str] = mapped_column(String(64), default="")


class ShortSearchItem(SearchBase, IdMixin):
    __tablename__ = "bafser_short_search_items"
    name: Mapped[str] = mapped_column(String(64))
    name_search: Mapped[str] = normalized_column(name, length=4)


class MultipleSearchItem(SearchBase, IdMixin):
    __tablename__ = "bafser_multiple_search_items"
    name: Mapped[str] = mapped_column(String(64))
    name_search: Mapped[str] = normalized_column(name, length=128, index=True, normalizer=partial(normalize_search, cyrillic_to_latin=False))
    name_latin: Mapped[str] = normalized_column(name, length=128, index=True, normalizer=partial(normalize_search, cyrillic_to_latin=True))
    city: Mapped[str] = mapped_column(String(64))
    city_search: Mapped[str] = normalized_column(city, normalizer=partial(normalize_search, cyrillic_to_latin=False))


class TruncatingSearchItem(SearchBase, IdMixin):
    __tablename__ = "bafser_truncating_search_items"
    name: Mapped[str] = mapped_column(TruncateString(4))
    name_search: Mapped[str] = normalized_column(name, length=5, normalizer=partial(normalize_search, cyrillic_to_latin=False))
    name_full: Mapped[str] = normalized_column(name, normalizer=partial(normalize_search, cyrillic_to_latin=False))
    alias: Mapped[str | None] = mapped_column(String(32), default=None)
    alias_search: Mapped[str | None] = normalized_column(alias, length=None, normalizer=partial(normalize_search, cyrillic_to_latin=False))


class StrictTruncateSearchItem(SearchBase, IdMixin):
    __tablename__ = "bafser_strict_truncate_search"
    name: Mapped[str] = mapped_column(TruncateString(4))
    name_search: Mapped[str] = normalized_column(name, length=5, overflow="raise", normalizer=partial(normalize_search, cyrillic_to_latin=False))


class ExplicitTruncateSearchItem(SearchBase, IdMixin):
    __tablename__ = "bafser_explicit_truncate_search"
    name: Mapped[str] = mapped_column(String(32))
    name_search: Mapped[str] = normalized_column(name, length=5, overflow="truncate", normalizer=partial(normalize_search, cyrillic_to_latin=False))


class FullTextSearchItem(SearchBase, IdMixin):
    __tablename__ = "bafser_full_text_search"
    name: Mapped[str] = mapped_column(Text())
    name_search: Mapped[str] = normalized_column(name, normalizer=partial(normalize_search, cyrillic_to_latin=False))


full_text_search_index = Index("ix_bafser_full_text_search", FullTextSearchItem.name_search, mysql_length=32)


class LiteralSearchItem(SearchBase, IdMixin):
    __tablename__ = "bafser_literal_search_items"
    name: Mapped[str] = mapped_column(String(64))
    name_search: Mapped[str] = normalized_column(name, length=128, normalizer=partial(normalize_search, strip_punctuation=False, cyrillic_to_latin=False))


class LatinSearchItem(SearchBase, IdMixin):
    __tablename__ = "bafser_latin_search_items"
    name: Mapped[str] = mapped_column(String(64))
    name_search: Mapped[str] = normalized_column(name, length=128, normalizer=partial(normalize_search, cyrillic_to_latin=True))


class InheritedSearchItem(SearchItem):
    pass


class CompositeSearchItem(SearchBase):
    __tablename__ = "bafser_composite_search_items"
    group_id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(32))
    name_search: Mapped[str] = normalized_column(name, length=64, normalizer=partial(normalize_search, cyrillic_to_latin=False))


class SearchMixin(MappedAsDataclass):
    label: Mapped[str] = mapped_column(String(32))
    label_search: Mapped[str] = normalized_column(label, length=64, normalizer=partial(normalize_search, cyrillic_to_latin=False))


class FirstMixinItem(SearchBase, SearchMixin, IdMixin):
    __tablename__ = "bafser_first_mixin_search"


class SecondMixinItem(SearchBase, SearchMixin, IdMixin):
    __tablename__ = "bafser_second_mixin_search"


class AbstractSearchSource(SearchBase, IdMixin):
    __abstract__ = True
    title: Mapped[str] = mapped_column(String(32))


class DeclaredSearchItem(AbstractSearchSource):
    __tablename__ = "bafser_declared_search"

    @declared_attr
    @classmethod
    def title_search(cls) -> Mapped[str]:
        return normalized_column(cls.title, length=64, normalizer=partial(normalize_search, cyrillic_to_latin=False))


class DeferredSearchItem(SearchBase, IdMixin):
    __tablename__ = "bafser_deferred_search"
    title: Mapped[str] = mapped_column(String(32), deferred=True)
    title_search: Mapped[str] = normalized_column(title, length=64, normalizer=partial(normalize_search, cyrillic_to_latin=False))
    note: Mapped[str] = mapped_column(String(32), default="")


class ValidatedSearchItem(SearchBase, IdMixin):
    __tablename__ = "bafser_validated_search"
    title: Mapped[str] = mapped_column(String(32))
    title_search: Mapped[str] = normalized_column(title, length=64, normalizer=partial(normalize_search, cyrillic_to_latin=False))

    @validates("title")
    def validate_title(self, key, value):
        return value.replace("!", "")


class SearchNormalizationTests(unittest.TestCase):
    def test_default_unicode_casefold_and_whitespace(self):
        self.assertEqual(normalize_search("  ИВАН\u00a0\t Иванов \n", cyrillic_to_latin=False), "иван иванов")
        self.assertEqual(normalize_search("ＳＴＲＡＳＳＥ Straße", cyrillic_to_latin=False), "strasse strasse")
        self.assertEqual(normalize_search("E\u0301", cyrillic_to_latin=False), "e")
        self.assertEqual(normalize_search("  \t\n", cyrillic_to_latin=False), "")
        self.assertEqual(normalize_search("Ёлка-Йогурт", cyrillic_to_latin=False), "елка иогурт")

    def test_optional_transforms(self):
        self.assertEqual(normalize_search("Ёлка-Йогурт", replace_yo=False, strip_diacritics=False, strip_punctuation=False, cyrillic_to_latin=False), "ёлка-йогурт")
        self.assertEqual(normalize_search("Ё Й", strip_diacritics=False, cyrillic_to_latin=False), "е й")
        self.assertEqual(normalize_search("Ё Й", replace_yo=False, strip_diacritics=False, cyrillic_to_latin=False), "ё й")
        self.assertEqual(normalize_search("Été Й", strip_diacritics=False, cyrillic_to_latin=False), "été й")
        self.assertEqual(normalize_search("one-two", strip_punctuation=False, cyrillic_to_latin=False), "one-two")
        self.assertEqual(normalize_search("  ЁЛКА! ", transliterate=lambda value: value.replace("ёлка", "YOLKA"), strip_punctuation=True), "yolka")

    def test_cyrillic_to_latin_is_opt_in_and_handles_mixed_text(self):
        self.assertEqual(normalize_search("Яна Юлия", cyrillic_to_latin=False), "яна юлия")
        self.assertEqual(normalize_search("  ЯНА, ЮЛИЯ и ЩУКА ", cyrillic_to_latin=True), "yana yuliya i schuka")
        self.assertEqual(normalize_search("Anna / Анна", cyrillic_to_latin=True), "anna anna")
        self.assertEqual(normalize_search("Съешь хлеб, выпей чаю", cyrillic_to_latin=True), "sesh hleb vypei chayu")

    def test_transliteration_respects_folding_options_and_custom_callback(self):
        self.assertEqual(normalize_search("Ёж Йод", cyrillic_to_latin=True), "ezh iod")
        self.assertEqual(normalize_search("Ёж Йод", cyrillic_to_latin=True, strip_diacritics=False), "ezh yod")
        self.assertEqual(normalize_search("Ёж Йод", cyrillic_to_latin=True, replace_yo=False, strip_diacritics=False), "yozh yod")
        self.assertEqual(normalize_search("Я/Ю", cyrillic_to_latin=True, strip_punctuation=False), "ya/yu")
        self.assertEqual(normalize_search("Я", cyrillic_to_latin=True, transliterate=lambda value: "Бренд"), "brend")

    def test_idempotence(self):
        for value in ("  Straße É Ё Й ", "\u212a\u212b\ufb03", "E\u0301\u2003 TEST", "İ ǰ"):
            self.assertEqual(normalize_search(normalize_search(value)), normalize_search(value))
            normalized = normalize_search(value, cyrillic_to_latin=True)
            self.assertEqual(normalize_search(normalized, cyrillic_to_latin=True), normalized)

    def test_invalid_types(self):
        with self.assertRaises(TypeError):
            normalize_search(None)
        with self.assertRaises(TypeError):
            normalize_search("x", transliterate=lambda value: None)


class NormalizedColumnTests(unittest.TestCase):
    database_url = "sqlite:///:memory:"

    def setUp(self):
        self.engine = create_engine(self.database_url)
        self.addCleanup(self.engine.dispose)
        SearchBase.metadata.create_all(self.engine)
        with self.engine.begin() as connection:
            for table in reversed(SearchBase.metadata.sorted_tables):
                connection.execute(table.delete())
        self.session = Session(self.engine)
        self.addCleanup(self.session.close)

    def test_constructor_and_assignment_update_both_derived_columns(self):
        item = SearchItem(name="  ЁЛКА  ")
        self.assertEqual(item.name, "  ЁЛКА  ")
        self.assertEqual(item.name_search, "елка")
        self.assertEqual(item.name_folded, "елка")
        self.assertIsNone(item.alias_search)
        item.name = "  Straße "
        self.assertEqual(item.name_search, "strasse")
        with self.assertRaises(TypeError):
            SearchItem(name="x", name_search="manual")

    def test_multiple_normalized_fields_use_their_own_sources_and_rules(self):
        item = MultipleSearchItem(name="ЯНА", city="МОСКВА")
        self.assertEqual((item.name_search, item.name_latin, item.city_search), ("яна", "yana", "москва"))
        self.session.add(item)
        self.session.commit()
        item.name = "ЮЛИЯ"
        self.assertEqual((item.name_search, item.name_latin, item.city_search), ("юлия", "yuliya", "москва"))
        item.city = "ТУЛА"
        self.session.commit()
        self.assertEqual((item.name_search, item.name_latin, item.city_search), ("юлия", "yuliya", "тула"))
        indexed_fields = {column.key for index in MultipleSearchItem.__table__.indexes for column in index.columns}
        self.assertEqual(indexed_fields, {"name_search", "name_latin"})

    def test_bulk_updates_keep_multiple_search_fields_independent(self):
        item = MultipleSearchItem(name="ЯНА", city="МОСКВА")
        self.session.add(item)
        self.session.commit()
        values = normalized_update_values(MultipleSearchItem, name="ЮЛИЯ")
        self.assertEqual(values, {"name": "ЮЛИЯ", "name_search": "юлия", "name_latin": "yuliya"})
        self.session.execute(update(MultipleSearchItem).where(MultipleSearchItem.id == item.id).values(**values))
        self.session.commit()
        self.assertEqual((item.name_search, item.name_latin, item.city_search), ("юлия", "yuliya", "москва"))
        values = normalized_update_values(MultipleSearchItem, name="ЯНА", city="ТУЛА")
        self.session.execute(update(MultipleSearchItem).where(MultipleSearchItem.id == item.id).values(**values))
        self.session.commit()
        self.assertEqual((item.name_search, item.name_latin, item.city_search), ("яна", "yana", "тула"))

    def test_rebuild_restores_all_normalizers_from_their_respective_sources(self):
        item = MultipleSearchItem(name="ЯНА", city="МОСКВА")
        self.session.add(item)
        self.session.commit()
        self.session.execute(update(MultipleSearchItem).values(name_search="wrong", name_latin="wrong", city_search="wrong"))
        self.session.commit()
        self.assertEqual(rebuild_normalized_columns(MultipleSearchItem, db_sess=self.session), 1)
        self.assertEqual((item.name_search, item.name_latin, item.city_search), ("яна", "yana", "москва"))

    def test_persistence_autoflush_and_rollback(self):
        item = SearchItem(name=" FIRST ")
        self.session.add(item)
        self.session.commit()
        item.name = " SECOND "
        found = self.session.scalars(select(SearchItem).where(SearchItem.name_search == "second")).one()
        self.assertIs(found, item)
        self.session.rollback()
        self.assertEqual(item.name, " FIRST ")
        self.assertEqual(item.name_search, "first")

    def test_manual_target_changes_are_repaired_on_flush(self):
        item = SearchItem(name="Name")
        self.session.add(item)
        self.session.flush()
        item.name_search = "wrong"
        item.name_folded = "also wrong"
        self.session.flush()
        self.assertEqual((item.name_search, item.name_folded), ("name", "name"))

    def test_nullable_and_empty_values(self):
        item = SearchItem(name="", alias="  ")
        self.session.add(item)
        self.session.flush()
        self.assertEqual(item.name_search, "")
        self.assertEqual(item.alias_search, "")
        item.alias = None
        self.session.flush()
        self.assertIsNone(item.alias_search)
        with self.assertRaises(NormalizationError):
            item.name = None

    def test_truncation_uses_the_stored_source(self):
        value = "A" * 32 + " HIDDEN TAIL"
        item = SearchItem(name=value)
        self.assertEqual(item.name, value)
        self.assertEqual(item.name_search, "a" * 32)
        self.session.add(item)
        self.session.commit()
        self.assertEqual(item.name, "A" * 32)
        self.assertEqual(item.name_search, "a" * 32)

    def test_normalized_length_is_checked_without_silent_truncation(self):
        with self.assertRaisesRegex(NormalizedValueTooLongError, r"ShortSearchItem.name_search.*6.*4"):
            ShortSearchItem(name="ßßß")
        self.assertEqual(ShortSearchItem(name="ßß").name_search, "ssss")

    def test_default_text_and_prefix_index_preserve_full_result(self):
        self.assertIsInstance(FullTextSearchItem.__table__.c.name_search.type, Text)
        value = "ﬃ" * 1000 + " TAIL"
        expected = "ffi" * 1000 + " tail"
        item = FullTextSearchItem(name=value)
        self.session.add(item)
        self.session.commit()
        self.assertEqual(item.name_search, expected)
        self.assertEqual(self.session.scalars(select(FullTextSearchItem).where(FullTextSearchItem.name_search.endswith("tail"))).one().id, item.id)
        self.assertIn("name_search(32)", str(CreateIndex(full_text_search_index).compile(dialect=mysql.dialect())))

    def test_truncate_source_defaults_to_truncating_derived_value(self):
        item = TruncatingSearchItem(name="ßßßßTAIL")
        self.assertEqual(item.name, "ßßßßTAIL")
        self.assertEqual(item.name_search, "sssss")
        self.assertEqual(item.name_full, "ssssssss")
        self.session.add(item)
        self.session.commit()
        self.assertEqual(item.name, "ßßßß")
        self.assertEqual(item.name_search, "sssss")
        self.assertEqual(item.name_full, "ssssssss")

    def test_explicit_overflow_overrides_source_defaults(self):
        with self.assertRaises(NormalizedValueTooLongError):
            StrictTruncateSearchItem(name="ßßßß")
        item = ExplicitTruncateSearchItem(name="ßßßß")
        self.session.add(item)
        self.session.commit()
        self.assertEqual(item.name, "ßßßß")
        self.assertEqual(item.name_search, "sssss")

    def test_overflow_policy_is_shared_by_bulk_updates_and_rebuild(self):
        item = TruncatingSearchItem(name="old")
        self.session.add(item)
        self.session.commit()
        values = normalized_update_values(TruncatingSearchItem, name="ßßßßTAIL")
        self.assertEqual(values["name_search"], "sssss")
        self.assertEqual(values["name_full"], "ssssssss")
        self.session.execute(update(TruncatingSearchItem).where(TruncatingSearchItem.id == item.id).values(**values))
        self.session.commit()
        self.assertEqual(item.name_search, "sssss")
        self.session.execute(update(TruncatingSearchItem).values(name_search="wrong", name_full="wrong"))
        self.session.commit()
        self.assertEqual(rebuild_normalized_columns(TruncatingSearchItem, db_sess=self.session), 1)
        self.assertEqual(item.name_search, "sssss")
        self.assertEqual(item.name_full, "ssssssss")
        self.assertEqual(normalized_update_values(ExplicitTruncateSearchItem, name="ßßßß")["name_search"], "sssss")
        with self.assertRaises(NormalizedValueTooLongError):
            normalized_update_values(StrictTruncateSearchItem, name="ßßßß")

    def test_unbounded_nullable_text(self):
        self.assertIsInstance(TruncatingSearchItem.__table__.c.alias_search.type, Text)
        item = TruncatingSearchItem(name="NAME", alias=None)
        self.session.add(item)
        self.session.flush()
        self.assertIsNone(item.alias_search)
        item.alias = "ﬃ" * 20
        self.session.flush()
        self.assertEqual(item.alias_search, "ffi" * 20)

    def test_copied_mixin_columns_bind_to_each_model(self):
        first = FirstMixinItem(label=" FIRST ")
        second = SecondMixinItem(label=" SECOND ")
        self.session.add_all([first, second])
        self.session.flush()
        self.assertEqual(first.label_search, "first")
        self.assertEqual(second.label_search, "second")
        first.label = "CHANGED"
        self.assertEqual(first.label_search, "changed")
        self.assertEqual(second.label_search, "second")

    def test_declared_attr_can_reference_an_inherited_field(self):
        item = DeclaredSearchItem(title=" INHERITED ")
        self.session.add(item)
        self.session.flush()
        self.assertEqual(item.title_search, "inherited")

    def test_mapped_inheritance_preserves_source_listeners(self):
        item = InheritedSearchItem(name=" ЁЛКА ")
        self.assertEqual(item.name_search, "елка")
        self.assertEqual(item.name_folded, "елка")
        item.name = "NEW"
        self.session.add(item)
        self.session.flush()
        self.assertEqual(item.name_search, "new")

    def test_validators_and_later_set_listeners_are_respected_before_flush(self):
        validated = ValidatedSearchItem(title=" HELLO! ")
        self.assertEqual(validated.title_search, "hello")
        self.session.add(validated)
        self.session.flush()
        self.assertEqual(validated.title_search, "hello")

        def append_suffix(target, value, oldvalue, initiator):
            return value + "-SUFFIX"

        event.listen(ValidatedSearchItem.title, "set", append_suffix, retval=True)
        self.addCleanup(event.remove, ValidatedSearchItem.title, "set", append_suffix)
        validated.title = "NEW"
        self.session.flush()
        self.assertEqual(validated.title_search, "new suffix")

    def test_unrelated_update_does_not_load_deferred_source(self):
        item = DeferredSearchItem(title="NAME")
        self.session.add(item)
        self.session.commit()
        item = self.session.get(DeferredSearchItem, item.id)
        self.assertIn("title", inspect(item).unloaded)
        calls = []
        event.listen(self.engine, "before_cursor_execute", lambda *args: calls.append(args[2]))
        item.note = "changed"
        self.session.flush()
        self.assertIn("title", inspect(item).unloaded)
        self.assertFalse(any(statement.lstrip().upper().startswith("SELECT") for statement in calls))

    def test_literal_wildcards_in_search(self):
        self.session.add_all([LiteralSearchItem(name="100%_REAL"), LiteralSearchItem(name="100abcXREAL")])
        self.session.flush()
        needle = normalize_search("%_", strip_punctuation=False)
        rows = self.session.scalars(select(LiteralSearchItem).where(LiteralSearchItem.name_search.contains(needle, autoescape=True))).all()
        self.assertEqual([row.name for row in rows], ["100%_REAL"])

    def test_latin_column_assignment_bulk_update_and_search_use_same_policy(self):
        item = LatinSearchItem(name="ЯНА Ёлкина")
        self.assertEqual(item.name_search, "yana elkina")
        self.session.add(item)
        self.session.commit()
        needle = normalize_search("YANA", cyrillic_to_latin=True)
        self.assertEqual(self.session.scalars(select(LatinSearchItem).where(LatinSearchItem.name_search.contains(needle))).one().id, item.id)
        self.session.execute(update(LatinSearchItem).where(LatinSearchItem.id == item.id).values(**normalized_update_values(LatinSearchItem, name="ЮЛИЯ")))
        self.session.commit()
        self.assertEqual(item.name_search, "yuliya")

    def test_bulk_helper_uses_attribute_names_and_current_normalizers(self):
        item = SearchItem(name="old")
        self.session.add(item)
        self.session.commit()
        values = normalized_update_values(SearchItem, name=" ЁЛКА ", alias=None, note="note")
        self.assertEqual(values["name_search"], "елка")
        self.assertEqual(values["name_folded"], "елка")
        self.assertIsNone(values["alias_search"])
        self.session.execute(update(SearchItem).where(SearchItem.id == item.id).values(**values))
        self.session.commit()
        self.assertEqual(item.name_search, "елка")
        self.assertEqual(item.note, "note")

    def test_bulk_helper_rejects_expressions_derived_and_unknown_fields(self):
        for values, error in (({"name": func.upper(SearchItem.name)}, NormalizationError), ({"name_search": "manual"}, TypeError), ({"missing": "value"}, TypeError)):
            with self.subTest(values=values), self.assertRaises(error):
                normalized_update_values(SearchItem, **values)
        self.assertEqual(normalized_update_values(SearchItem, note="x"), {"note": "x"})

    def test_sql_expression_assignment_is_rejected(self):
        item = SearchItem(name="name")
        with self.assertRaises(NormalizationError):
            item.name = func.upper(SearchItem.name)
        self.assertEqual(item.name_search, "name")

    def test_direct_bulk_write_is_not_implicitly_normalized(self):
        item = SearchItem(name="OLD")
        self.session.add(item)
        self.session.commit()
        self.session.execute(update(SearchItem).where(SearchItem.id == item.id).values(name="NEW"))
        self.session.commit()
        self.assertEqual(item.name, "NEW")
        self.assertEqual(item.name_search, "old")

    def test_rebuild_pages_include_deleted_rows_without_committing(self):
        items = [SearchItem(name=f" ITEM {index} ") for index in range(5)]
        items[-1].deleted = True
        self.session.add_all(items)
        self.session.commit()
        self.session.execute(update(SearchItem).values(name_search="outdated", name_folded="outdated"))
        self.session.commit()
        self.assertEqual(rebuild_normalized_columns(SearchItem, db_sess=self.session, batch_size=2), 5)
        self.assertEqual([item.name_search for item in items], [f"item {index}" for index in range(5)])
        self.session.rollback()
        self.assertEqual(items[0].name_search, "outdated")

    def test_rebuild_supports_composite_primary_keys_and_repeated_runs(self):
        self.session.add_all([CompositeSearchItem(group_id=group, item_id=index, name=f" NAME {group} {index} ") for group in (1, 2) for index in (1, 2, 3)])
        self.session.commit()
        self.session.execute(update(CompositeSearchItem).values(name_search="outdated"))
        self.session.commit()
        self.assertEqual(rebuild_normalized_columns(CompositeSearchItem, db_sess=self.session, batch_size=2), 6)
        self.assertEqual(rebuild_normalized_columns(CompositeSearchItem, db_sess=self.session, batch_size=3), 6)
        rows = self.session.scalars(select(CompositeSearchItem)).all()
        self.assertTrue(all(row.name_search == normalize_search(row.name) for row in rows))

    def test_rebuild_supports_deferred_sources(self):
        self.session.add(DeferredSearchItem(title="NAME"))
        self.session.commit()
        self.session.execute(update(DeferredSearchItem).values(title_search="outdated"))
        self.session.commit()
        self.assertEqual(rebuild_normalized_columns(DeferredSearchItem, db_sess=self.session), 1)
        self.assertEqual(self.session.scalars(select(DeferredSearchItem.title_search)).one(), "name")

    def test_empty_rebuild_and_invalid_batch_size(self):
        self.assertEqual(rebuild_normalized_columns(SearchItem, db_sess=self.session), 0)
        for size in (0, -1, True):
            with self.assertRaises(ValueError):
                rebuild_normalized_columns(SearchItem, db_sess=self.session, batch_size=size)


class InvalidConfigurationTests(unittest.TestCase):
    def test_bad_helper_arguments(self):
        source = mapped_column(String(32))
        for kwargs in ({"length": 0}, {"length": True}, {"length": 10, "init": True}, {"length": 10, "default": ""}, {"length": 10, "overflow": "ignore"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                normalized_column(source, **kwargs)
        with self.assertRaises(TypeError):
            normalized_column("name", length=32)
        with self.assertRaises(TypeError):
            normalized_column(source, normalizer=None)

    def check_invalid_model(self, factory, message, error=TypeError):
        mapper_registry = registry()
        try:
            class Base(MappedAsDataclass, DeclarativeBase):
                registry = mapper_registry

            with self.assertRaisesRegex(error, message):
                factory(Base)
                mapper_registry.configure()
        finally:
            mapper_registry.dispose()

    def test_non_string_and_foreign_source_are_rejected(self):
        def integer_model(Base):
            class Item(Base):
                __tablename__ = "invalid_integer_source"
                id: Mapped[int] = mapped_column(primary_key=True)
                value: Mapped[str] = normalized_column(id, length=32)

        self.check_invalid_model(integer_model, "source must use String")

        def foreign_model(Base):
            class Item(Base):
                __tablename__ = "invalid_foreign_source"
                id: Mapped[int] = mapped_column(primary_key=True)
                value: Mapped[str] = normalized_column(SearchItem.name, length=32)

        self.check_invalid_model(foreign_model, "belong to the model")

    def test_nullable_mismatch_and_chains_are_rejected(self):
        def mismatch(Base):
            class Item(Base):
                __tablename__ = "invalid_nullable"
                id: Mapped[int] = mapped_column(primary_key=True)
                name: Mapped[str | None] = mapped_column(String(32))
                value: Mapped[str] = normalized_column(name, length=32, nullable=False)

        self.check_invalid_model(mismatch, "nullable must match")

        def chain(Base):
            class Item(Base):
                __tablename__ = "invalid_chain"
                id: Mapped[int] = mapped_column(primary_key=True)
                name: Mapped[str] = mapped_column(String(32))
                value: Mapped[str] = normalized_column(name, length=32)
                other: Mapped[str] = normalized_column(value, length=32)

        self.check_invalid_model(chain, "chains")

    def test_custom_bind_processor_is_rejected(self):
        class CustomString(TypeDecorator):
            impl = String(32)
            cache_ok = True

        def model(Base):
            class Item(Base):
                __tablename__ = "invalid_custom_type"
                id: Mapped[int] = mapped_column(primary_key=True)
                name: Mapped[str] = mapped_column(CustomString())
                value: Mapped[str] = normalized_column(name, length=32)

        self.check_invalid_model(model, "source must use String")

    def test_generated_source_is_rejected(self):
        def model(Base):
            class Item(Base):
                __tablename__ = "invalid_generated_type"
                id: Mapped[int] = mapped_column(primary_key=True)
                name: Mapped[str] = mapped_column(String(32), onupdate="generated")
                value: Mapped[str] = normalized_column(name, length=32)

        self.check_invalid_model(model, "generated/onupdate", ValueError)

    def test_missing_server_default_and_invalid_normalizer_results(self):
        mapper_registry = registry()
        engine = create_engine("sqlite://")
        try:
            class Base(MappedAsDataclass, DeclarativeBase):
                registry = mapper_registry

            class Item(Base):
                __tablename__ = "unknown_server_default"
                id: Mapped[int] = mapped_column(primary_key=True, init=False)
                name: Mapped[str] = mapped_column(String(32), init=False, server_default="unknown")
                value: Mapped[str] = normalized_column(name, length=32)

            class InvalidNormalizer(Base):
                __tablename__ = "invalid_normalizer_result"
                id: Mapped[int] = mapped_column(primary_key=True, init=False)
                name: Mapped[str] = mapped_column(String(32))
                value: Mapped[str] = normalized_column(name, length=32, normalizer=lambda value: None)

            class NullableDefault(Base):
                __tablename__ = "nullable_server_default"
                id: Mapped[int] = mapped_column(primary_key=True, init=False)
                name: Mapped[str | None] = mapped_column(String(32), init=False, server_default="unknown")
                value: Mapped[str | None] = normalized_column(name, length=32)

            Base.metadata.create_all(engine)
            with Session(engine) as session:
                session.add(Item())
                with self.assertRaisesRegex(NormalizationError, "concrete string"):
                    session.flush()
            with Session(engine) as session:
                session.add(NullableDefault())
                with self.assertRaisesRegex(NormalizationError, "concrete string"):
                    session.flush()
            known = NullableDefault()
            known.name = "KNOWN"
            with Session(engine) as session:
                session.add(known)
                session.flush()
                known.name = None
                session.flush()
                self.assertIsNone(known.value)
            with self.assertRaisesRegex(NormalizationError, "must return a string"):
                InvalidNormalizer(name="name")
        finally:
            engine.dispose()
            mapper_registry.dispose()


@unittest.skipUnless(os.environ.get("BAFSER_TEST_MYSQL_URL"), "BAFSER_TEST_MYSQL_URL is not configured")
class MySQLNormalizedColumnTests(NormalizedColumnTests):
    @property
    def database_url(self):
        return os.environ["BAFSER_TEST_MYSQL_URL"]


if __name__ == "__main__":
    unittest.main()
