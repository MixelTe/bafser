import json
import unittest
from datetime import date, datetime, timezone
from typing import TypedDict

from bafser import JsonObj, JsonOpt, JsonParseError, Undefined


class Day(JsonObj):
    value: date


class CalendarItem(TypedDict):
    day: date


class JsonObjDateTests(unittest.TestCase):
    def test_date_parses_and_serializes_iso_calendar_dates(self):
        for value in ("0001-01-01", "2028-02-29", "9999-12-31"):
            with self.subTest(value=value):
                payload = Day.parse(json.dumps({"value": value})).valid()
                self.assertIs(type(payload.value), date)
                self.assertEqual(payload.value, date.fromisoformat(value))
                self.assertEqual(payload.json(), {"value": value})
                self.assertEqual(json.loads(json.dumps(payload.json())), {"value": value})

    def test_ready_date_is_preserved(self):
        value = date(2026, 11, 4)
        self.assertIs(Day(value=value).valid().value, value)

    def test_invalid_date_input_fails_validation(self):
        for value in ("invalid", "2026-02-29", "2026-11-04T12:00:00", "", 123, True, None, [], {}):
            with self.subTest(value=value):
                payload = Day.new({"value": value})
                with self.assertRaisesRegex(JsonParseError, "value.*date"):
                    payload.valid()

    def test_optional_nullable_and_union_date_fields(self):
        class Options(JsonObj):
            optional: JsonOpt[date]
            nullable: date | None
            fallback: date | int
            text: date | str

        payload = Options.new({"nullable": "2026-11-04", "fallback": "2028-02-29", "text": "2026-11-04"}).valid()
        self.assertIs(payload.optional, Undefined)
        self.assertEqual(payload.nullable, date(2026, 11, 4))
        self.assertEqual(payload.fallback, date(2028, 2, 29))
        self.assertEqual(payload.text, date(2026, 11, 4))
        self.assertEqual(payload.json(), {"nullable": "2026-11-04", "fallback": "2028-02-29", "text": "2026-11-04"})
        payload = Options.new({"optional": "2026-11-04", "nullable": None, "fallback": 0, "text": "free text"}).valid()
        self.assertEqual(payload.optional, date(2026, 11, 4))
        self.assertIsNone(payload.nullable)
        self.assertEqual(payload.fallback, 0)
        with self.assertRaises(JsonParseError):
            Options.new({"optional": "invalid", "nullable": None, "fallback": 0, "text": "text"}).valid()

    def test_dates_in_collections_nested_objects_and_typed_dicts(self):
        class Calendar(JsonObj):
            days: list[date | None]
            pair: tuple[date, date]
            labels: dict[str, date]
            child: Day
            item: CalendarItem

        data = {
            "days": ["2026-11-04", None],
            "pair": ["2026-11-04", "2028-02-29"],
            "labels": {"arbitrary": "2026-11-04"},
            "child": {"value": "2026-11-04"},
            "item": {"day": "2028-02-29"},
        }
        payload = Calendar.new(data).valid()
        self.assertEqual(payload.days, [date(2026, 11, 4), None])
        self.assertEqual(payload.pair, (date(2026, 11, 4), date(2028, 2, 29)))
        self.assertEqual(payload.labels, {"arbitrary": date(2026, 11, 4)})
        self.assertEqual(payload.child.value, date(2026, 11, 4))
        self.assertEqual(payload.item["day"], date(2028, 2, 29))
        self.assertEqual(json.loads(json.dumps(payload.json())), {
            "days": ["2026-11-04", None],
            "pair": ["2026-11-04", "2028-02-29"],
            "labels": {"arbitrary": "2026-11-04"},
            "child": {"value": "2026-11-04"},
            "item": {"day": "2028-02-29"},
        })

    def test_custom_date_parser_and_serializer_are_inherited(self):
        class CustomDay(Day):
            __date_parser__ = staticmethod(lambda value: datetime.strptime(value, "%d.%m.%Y").date())
            __date_serializer__ = staticmethod(lambda value: value.strftime("%d.%m.%Y"))

        class Child(CustomDay):
            pass

        payload = Child.new({"value": "04.11.2026"}).valid()
        self.assertEqual(payload.value, date(2026, 11, 4))
        self.assertEqual(payload.json(), {"value": "04.11.2026"})

    def test_field_hooks_can_override_date_conversion(self):
        class CustomDay(Day):
            def _parse(self, key, value, data):
                return key, date(2026, 11, 4)

            def _serialize(self, key, value):
                return key, "custom day"

        self.assertEqual(CustomDay.new({"value": "today"}).valid().json(), {"value": "custom day"})

    def test_datetime_parser_and_serializer_keep_time_and_offset(self):
        class Mixed(JsonObj):
            day: date
            instant: datetime

        payload = Mixed.new({"day": "2026-11-04", "instant": "2026-11-04T23:15:00+00:00"}).valid()
        self.assertIs(type(payload.day), date)
        self.assertEqual(payload.instant, datetime(2026, 11, 4, 23, 15, tzinfo=timezone.utc))
        self.assertEqual(payload.json(), {"day": "2026-11-04", "instant": "2026-11-04T23:15:00+00:00"})


if __name__ == "__main__":
    unittest.main()
