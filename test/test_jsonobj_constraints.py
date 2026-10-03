import re
import unittest
from typing import Any

from bafser import JsonObj, JsonOpt, JsonParseError, Undefined


def must_contain_at(value: str) -> str | None:
    return None if "@" in value else "must contain @"


class Profile(JsonObj):
    name: str = JsonObj.field(min_length=1, max_length=4)
    age: int = JsonObj.field(min_value=18, max_value=120)
    email: JsonOpt[str] = JsonObj.field(default=Undefined, validators=(must_contain_at,))


class ProfileWithDefault(Profile):
    nickname: str = JsonObj.field(default="toolong", max_length=4)


class RelaxedProfile(Profile):
    name: str = "long default"


class Envelope(JsonObj):
    profile: Profile


class DateRange(JsonObj):
    start: int
    end: int

    def _validate_object(self) -> str | None:
        return "end must be after start" if self.end <= self.start else None


class Item(JsonObj):
    code: str = JsonObj.field(pattern=r"[A-Z]{2}\d{2}")
    state: str = JsonObj.field(choices=("draft", "published"))
    tags: list[str] = JsonObj.field(min_length=1, max_length=2)


class Measurement(JsonObj):
    value: float = JsonObj.field(finite=True, min_value=0, max_value=10)


class LargeCount(JsonObj):
    value: int = JsonObj.field(finite=True)


class JsonObjConstraintTests(unittest.TestCase):
    def test_bounds_are_inclusive(self):
        self.assertIsNone(Profile(name="abcd", age=18).validate())
        self.assertIsNone(Profile(name="a", age=120, email="a@b").validate())

    def test_length_and_numeric_errors(self):
        self.assertEqual(Profile(name="", age=18).validate(), "name must have at least 1 character")
        self.assertEqual(Profile(name="abcde", age=18).validate(), "name must have at most 4 characters")
        self.assertEqual(Profile(name="a", age=17).validate(), "age must be at least 18")
        self.assertEqual(Profile(name="a", age=121).validate(), "age must be at most 120")

    def test_type_is_checked_before_constraints_and_validators(self):
        self.assertEqual(Profile(name=123, age=18).validate(), "name is not str")  # type: ignore[arg-type]
        self.assertEqual(Profile(name="a", age=True).validate(), "age is not int")  # type: ignore[arg-type]
        self.assertEqual(Profile(name="a", age=18, email="invalid").validate(), "email must contain @")

    def test_optional_field_and_nested_error(self):
        self.assertIs(Profile(name="a", age=18).email, Undefined)
        self.assertEqual(Envelope(profile=Profile(name="abcde", age=18)).validate(), "profile.name must have at most 4 characters")

    def test_inherited_rules_and_defaults(self):
        self.assertEqual(ProfileWithDefault(name="a", age=18).validate(), "nickname must have at most 4 characters")
        self.assertEqual(ProfileWithDefault(name="abcde", age=18, nickname="ok").validate(), "name must have at most 4 characters")
        self.assertIsNone(RelaxedProfile(age=18).validate())

    def test_object_rule_and_valid(self):
        invalid = DateRange(start=4, end=3)
        self.assertEqual(invalid.validate(), "end must be after start")
        with self.assertRaisesRegex(JsonParseError, "end must be after start"):
            invalid.valid()
        self.assertIsNone(DateRange(start=3, end=4).validate())

    def test_invalid_bounds_are_rejected(self):
        with self.assertRaises(ValueError):
            JsonObj.field(min_value=2, max_value=1)
        with self.assertRaises(ValueError):
            JsonObj.field(min_length=2, max_length=1)

    def test_pattern_requires_full_match(self):
        self.assertIsNone(Item(code="AB12", state="draft", tags=["one"]).validate())
        self.assertEqual(
            Item(code="AB12-extra", state="draft", tags=["one"]).validate(),
            "code must match pattern [A-Z]{2}\\d{2}",
        )
        self.assertEqual(Item(code="ab12", state="draft", tags=["one"]).validate(), "code must match pattern [A-Z]{2}\\d{2}")
        self.assertEqual(Item(code=12, state="draft", tags=["one"]).validate(), "code is not str")  # type: ignore[arg-type]

    def test_choices_and_list_length(self):
        self.assertEqual(Item(code="AB12", state="other", tags=["one"]).validate(), "state must be one of ('draft', 'published')")
        self.assertEqual(Item(code="AB12", state="draft", tags=[]).validate(), "tags must have at least 1 item")
        self.assertEqual(Item(code="AB12", state="draft", tags=["a", "b", "c"]).validate(), "tags must have at most 2 items")

    def test_compiled_pattern_and_invalid_configuration(self):
        class CaseInsensitive(JsonObj):
            code: str = JsonObj.field(pattern=re.compile(r"[a-z]+", re.IGNORECASE))

        self.assertIsNone(CaseInsensitive(code="ABC").validate())
        with self.assertRaises(ValueError):
            JsonObj.field(choices=())

    def test_finite_rejects_nan_and_infinity_before_bounds(self):
        self.assertIsNone(Measurement(value=0.0).validate())
        self.assertIsNone(Measurement(value=10.0).validate())
        for value in (float("nan"), float("inf"), float("-inf")):
            self.assertEqual(Measurement(value=value).validate(), "value must be finite")
        self.assertEqual(Measurement(value=-1.0).validate(), "value must be at least 0")
        self.assertIsNone(LargeCount(value=10**1000).validate())

    def test_incompatible_rules_fail_when_class_is_defined(self):
        with self.assertRaisesRegex(TypeError, "BadNumber.name: min_value/max_value requires a numeric field"):

            class BadNumber(JsonObj):  # pyright: ignore[reportUnusedClass]
                name: str = JsonObj.field(min_value=1)

        with self.assertRaisesRegex(TypeError, "BadPattern.items: pattern requires a string field"):

            class BadPattern(JsonObj):  # pyright: ignore[reportUnusedClass]
                items: list[str] = JsonObj.field(pattern="x")  # pyright: ignore[reportIncompatibleMethodOverride]

        with self.assertRaisesRegex(TypeError, "BadFinite.value: finite requires a numeric field"):

            class BadFinite(JsonObj):  # pyright: ignore[reportUnusedClass]
                value: Any = JsonObj.field(finite=True)

        with self.assertRaisesRegex(TypeError, "BadOverride.name: min_length/max_length requires a string or list field"):

            class BadOverride(Profile):  # pyright: ignore[reportUnusedClass]
                name: int  # pyright: ignore[reportIncompatibleVariableOverride, reportIncompatibleMethodOverride]

    def test_string_annotations_and_optional_union(self):
        class OptionalName(JsonObj):
            name: "JsonOpt[str | None]" = JsonObj.field(default=Undefined, min_length=1)

        self.assertIsNone(OptionalName().validate())
        self.assertIsNone(OptionalName(name=None).validate())
        self.assertEqual(OptionalName(name="").validate(), "name must have at least 1 character")


if __name__ == "__main__":
    unittest.main()
