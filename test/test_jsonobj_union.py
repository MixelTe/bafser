import unittest
from datetime import date, datetime

from bafser import JsonObj, JsonParseError, UnionParseError
from bafser import get_json_list, get_json_values
from bafser.jsonobj import validate_type


class JsonObjUnionTests(unittest.TestCase):
    def test_type_validation_never_constructs_models(self):
        calls = []

        class Model(JsonObj):
            value: int

            def _parse(self, key, value, data):
                calls.append(key)

        self.assertIsNotNone(validate_type({"value": 1}, Model)[1])
        self.assertIsNotNone(validate_type([{"value": 1}], list[Model])[1])
        self.assertEqual(calls, [])

    def test_json_helpers_explicitly_parse_model_input(self):
        class Model(JsonObj):
            value: int

            def _parse(self, key, value, data):
                return "value" if key == "wire" else None

        models, error = get_json_list([{"wire": 1}], Model)
        self.assertIsNone(error)
        self.assertEqual(models[0].value, 1)
        model, error = get_json_values({"model": {"wire": 2}}, ("model", Model))
        self.assertIsNone(error)
        self.assertEqual(model.value, 2)

    def test_selected_branch_is_not_reparsed_but_explicit_validation_runs_again(self):
        calls = []

        class Model(JsonObj):
            day: date

            def _parse(self, key, value, data):
                calls.append(("parse", key))
                return "day" if key == "wire" else None

            def _validate_object(self):
                calls.append(("validate", self.day))

        class Envelope(JsonObj):
            __annotations__ = {"value": Model | dict}

            def _parse(self, key, value, data):
                calls.append(("outer", key))

        payload = Envelope.new({"value": {"wire": "2026-11-04"}})
        self.assertEqual(calls, [("outer", "value"), ("parse", "wire"), ("validate", date(2026, 11, 4))])
        payload.valid()
        payload.valid()
        self.assertIsInstance(payload.value, Model)
        self.assertEqual(calls, [("outer", "value"), ("parse", "wire"), *[("validate", date(2026, 11, 4))] * 3])

    def test_failed_branch_does_not_mutate_next_branch_or_input(self):
        class Rejected(JsonObj):
            values: list[int]

            def _parse(self, key, value, data):
                value.append(99)
                raise JsonParseError("reject mutated candidate")

        class Accepted(JsonObj):
            values: list[int]

        class Envelope(JsonObj):
            __annotations__ = {"value": Rejected | Accepted}

        data = {"value": {"values": [1]}}
        payload = Envelope.new(data).valid()
        self.assertIsInstance(payload.value, Accepted)
        self.assertEqual(payload.value.values, [1])
        self.assertEqual(data, {"value": {"values": [1]}})

    def test_union_order_controls_conversion_and_dictionary_fallback(self):
        class Envelope(JsonObj):
            first: date | str
            second: str | date
            instant: datetime | None

        value = Envelope.new({"first": "2026-11-04", "second": "2026-11-04", "instant": "2026-11-04T12:30:00"}).valid()
        self.assertEqual(value.first, date(2026, 11, 4))
        self.assertEqual(value.second, "2026-11-04")
        self.assertEqual(value.instant, datetime(2026, 11, 4, 12, 30))

    def test_all_branch_errors_keep_path_type_and_original_reason(self):
        class First(JsonObj):
            value: int

            def _parse(self, key, value, data):
                raise JsonParseError("first reason")

        class Second(JsonObj):
            value: int

            def _validate_object(self):
                return "second reason"

        class Envelope(JsonObj):
            __annotations__ = {"items": list[First | Second]}

        with self.assertRaises(UnionParseError) as caught:
            Envelope.new({"items": [{"value": 1}]}).valid()
        self.assertEqual(caught.exception.path, "items.0")
        self.assertEqual([target for target, _ in caught.exception.failures], [First, Second])
        self.assertIn("first reason", str(caught.exception))
        self.assertIn("second reason", str(caught.exception))

    def test_unexpected_parser_and_validator_errors_propagate(self):
        for phase in ("parse", "validate"):
            with self.subTest(phase=phase):
                class Broken(JsonObj):
                    value: int

                    def _parse(self, key, value, data):
                        if phase == "parse":
                            raise ValueError("programming error")

                    def _validate_object(self):
                        raise RuntimeError("programming error")

                class Envelope(JsonObj):
                    __annotations__ = {"value": Broken | dict}

                with self.assertRaisesRegex((ValueError, RuntimeError), "programming error"):
                    Envelope.new({"value": {"value": 1}})

    def test_collection_branches_are_not_reparsed_during_validation(self):
        calls = []

        class Rejected(JsonObj):
            value: int

            def _parse(self, key, value, data):
                calls.append("reject")
                raise JsonParseError("rejected")

        class Envelope(JsonObj):
            __annotations__ = {"value": list[Rejected] | list[dict]}

        value = Envelope.new({"value": [{"value": 1}]}).valid()
        self.assertEqual(value.value, [{"value": 1}])
        self.assertEqual(calls, ["reject"])

    def test_changed_candidate_is_revalidated_before_accepting_parent(self):
        class Model(JsonObj):
            values: list[int]

            def _validate_object(self):
                return "too many" if len(self.values) > 1 else None

        class Envelope(JsonObj):
            __annotations__ = {"value": Model | None}

        value = Envelope.new({"value": {"values": [1]}})
        value.value.values.append(2)
        with self.assertRaisesRegex(JsonParseError, "too many"):
            value.valid()

    def test_ready_model_is_reused_and_wrong_sibling_is_not_accepted(self):
        class First(JsonObj):
            value: int

        class Second(JsonObj):
            value: int

        class Envelope(JsonObj):
            __annotations__ = {"value": First | Second}

        original = Second(value=1)
        value = Envelope(value=original).valid()
        self.assertIsInstance(value.value, Second)
        self.assertIs(value.value, original)
        self.assertEqual(original.value, 1)

    def test_tuple_arity_and_nullable_model_are_preserved(self):
        class Model(JsonObj):
            value: int = 1

        class Envelope(JsonObj):
            __annotations__ = {"value": Model | None, "items": tuple[int, int] | list[int]}

        value = Envelope.new({"value": None, "items": [1, 2, 3]}).valid()
        self.assertIsNone(value.value)
        self.assertEqual(value.items, [1, 2, 3])
