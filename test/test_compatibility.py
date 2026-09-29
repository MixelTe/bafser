"""Core behavior that must work on every supported Python version."""

import unittest

from bafser import JsonObj, JsonOpt, TJson, TJsonListOf, Undefined
from bafser.doc_api import type_info, type_to_json


class ExamplePayload(JsonObj):
    name: str
    note: JsonOpt[str] = Undefined


class CompatibilityTests(unittest.TestCase):
    def test_json_optional_field(self):
        payload = ExamplePayload.new({"name": "example"})
        self.assertIsNone(payload.validate())
        self.assertEqual(payload.json(), {"name": "example"})
        self.assertEqual(ExamplePayload.get_optional_fields(), ["note"])

    def test_documentation_aliases(self):
        from test.data.img import ImageJson

        self.assertEqual(type_to_json(TJson["item", int], {}), {"item": "number"})
        self.assertEqual(type_to_json(TJsonListOf["item", int], {}), [{"item": "number"}])
        fields = TJson["img", ImageJson, "type", int]
        expected = {"img": {"data": "string", "name": "string", "desc": "string"}, "type": "number"} # type: ignore
        self.assertEqual(type_to_json(fields, {}), expected)
        info_fields = type_info(fields, {}).object_fields
        assert isinstance(info_fields, list)
        self.assertEqual([field.name for field in info_fields], ["img", "type"])
        self.assertEqual(type_to_json(TJsonListOf["img", ImageJson, "type", int], {}), [expected])

    def test_sqlalchemy_serializer_with_project_model(self):
        from test.data.apple import Apple  # noqa: F401
        from test.data.img import Img  # noqa: F401
        from test.data.user import User

        user = User(login="example", name="Example", balance=0)
        self.assertEqual(user.to_dict(only=("login", "name", "balance")), {"login": "example", "name": "Example", "balance": 0})


if __name__ == "__main__":
    unittest.main()
