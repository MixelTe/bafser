import unittest

from flask import Flask, g
from werkzeug.exceptions import HTTPException

from bafser import JsonObj, JsonParseError


class Payload(JsonObj):
    name: str


class ExternalPayload(Payload):
    __allow_unknown_fields__ = True


class JsonObjUnknownFieldsTests(unittest.TestCase):
    def test_unknown_fields_are_rejected_on_validation(self):
        payload = Payload.new({"name": "example", "extra": 1})
        self.assertEqual(payload.validate(), "extra: Unexpected field: extra")
        self.assertFalse(payload.is_valid())
        with self.assertRaisesRegex(JsonParseError, "Unexpected field: extra"):
            payload.valid()
        self.assertEqual(Payload.parse('{"name":"example","extra":1}').validate(), payload.validate())

    def test_allow_unknown_fields_ignores_without_assigning_or_serializing(self):
        payload = ExternalPayload.new({"name": "example", "extra": 1, "validate": "broken"}).valid()
        self.assertEqual(payload.json(), {"name": "example"})
        self.assertNotIn("extra", vars(payload))
        self.assertTrue(callable(payload.validate))
        self.assertEqual(ExternalPayload.get_field_types(), {"name": str})

    def test_option_is_inherited_and_can_be_reenabled(self):
        class Child(ExternalPayload):
            pass

        class StrictChild(ExternalPayload):
            __allow_unknown_fields__ = False

        self.assertIsNone(Child.new({"name": "example", "extra": 1}).validate())
        self.assertIsNotNone(StrictChild.new({"name": "example", "extra": 1}).validate())

    def test_input_cannot_override_option_or_private_attributes(self):
        for key in ("__allow_unknown_fields__", "__exceptions__", "_private"):
            with self.subTest(key=key):
                payload = Payload.new({"name": "example", key: True, "extra": 1})
                self.assertIn(f"Unexpected field: {key}", payload.validate())
                self.assertFalse(payload.__allow_unknown_fields__)

    def test_parser_can_map_unknown_input_to_a_declared_field(self):
        class Aliased(Payload):
            def _parse(self, key, value, data):
                if key == "title":
                    return "name"
                if key == "uppercase":
                    return "name", value.upper()

        self.assertEqual(Aliased.new({"title": "example"}).valid().name, "example")
        self.assertEqual(Aliased.new({"uppercase": "example"}).valid().name, "EXAMPLE")
        self.assertIsNotNone(Aliased.new({"name": "example", "extra": 1}).validate())

    def test_parser_cannot_bypass_check_with_an_unknown_output_key(self):
        class Remapped(Payload):
            def _parse(self, key, value, data):
                if key == "extra":
                    return "other", value

        self.assertEqual(Remapped.new({"name": "example", "extra": 1}).validate(), "other: Unexpected field: other")

    def test_nested_schemas_choose_their_own_policy(self):
        class Envelope(JsonObj):
            __allow_unknown_fields__ = True
            strict: Payload
            external: ExternalPayload

        valid = {"strict": {"name": "a"}, "external": {"name": "b", "extra": 1}}
        self.assertIsNone(Envelope.new(valid).validate())
        invalid = {**valid, "strict": {"name": "a", "extra": 1}}
        self.assertIn("Unexpected field: extra", Envelope.new(invalid).validate())

    def test_collection_paths_and_dictionary_keys_are_not_unknown_fields(self):
        class Collections(JsonObj):
            names: list[str]
            pair: tuple[int, str]
            labels: dict[str, str]
            children: list[Payload]

        data = {"names": ["a"], "pair": [1, "a"], "labels": {"arbitrary": "value"}, "children": [{"name": "a"}]}
        self.assertIsNone(Collections.new(data).validate())
        data["children"] = [{"name": "a", "extra": 1}]
        self.assertIn("Unexpected field: extra", Collections.new(data).validate())

    def test_request_returns_400_for_unknown_fields(self):
        app = Flask(__name__)
        with app.test_request_context(json={"name": "example", "extra": 1}):
            g.json = ({"name": "example", "extra": 1}, True)
            with self.assertRaises(HTTPException) as raised:
                Payload.get_from_req()
            self.assertEqual(raised.exception.response.status_code, 400)
            self.assertIn("Unexpected field: extra", raised.exception.response.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
