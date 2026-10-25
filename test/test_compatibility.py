"""Core behavior that must work on every supported Python version."""

import unittest
from datetime import datetime
from unittest.mock import patch

from flask import Flask
from flask_jwt_extended import JWTManager
from werkzeug.exceptions import HTTPException

from bafser import JsonObj, JsonOpt, TJson, TJsonListOf, Undefined, UserBase
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
        expected = {"img": {"data": "string", "name": "string", "desc": "string"}, "type": "number"}  # type: ignore
        self.assertEqual(type_to_json(fields, {}), expected)
        info_fields = type_info(fields, {}).object_fields
        assert isinstance(info_fields, list)
        self.assertEqual([field.name for field in info_fields], ["img", "type"])
        self.assertEqual(type_to_json(TJsonListOf["img", ImageJson, "type", int], {}), [expected])

    def test_documentation_optional_alias_fields_and_datetime(self):
        for list_of, schema in (
            (False, TJson["active", JsonOpt[bool], "date", datetime, "until", JsonOpt[datetime | None]]),
            (True, TJsonListOf["active", JsonOpt[bool], "date", datetime, "until", JsonOpt[datetime | None]]),
        ):
            with self.subTest(list_of=list_of):
                expected = {"active?": "boolean", "date": "datetime", "until?": "datetime | null"}
                self.assertEqual(type_to_json(schema, {}), [expected] if list_of else expected)
                info = type_info(schema, {})
                if list_of:
                    info = info.list_type
                fields = info.object_fields
                self.assertEqual([field.name for field in fields], ["active", "date", "until"])
                self.assertEqual([field.optional for field in fields], [True, False, True])
                self.assertEqual(fields[0].type.type, "bool")
                self.assertEqual(fields[1].type.type, "datetime")
                self.assertEqual([item.type for item in fields[2].type.union_type], ["datetime", "null"])

    def test_sqlalchemy_serializer_with_project_model(self):
        from test.data.apple import Apple  # type: ignore
        from test.data.img import Img  # type: ignore
        from test.data.user import User

        user = User(login="example", name="Example", balance=0)
        self.assertEqual(user.to_dict(only=("login", "name", "balance")), {"login": "example", "name": "Example", "balance": 0})


class CurrentUserCompatibilityTests(unittest.TestCase):
    def test_current_resolves_user_from_base_subclass_and_instance(self):
        from test.data.apple import Apple  # type: ignore
        from test.data.img import Img  # type: ignore
        from test.data.user import User

        user = User(login="example", name="Example", balance=0)
        with patch("bafser.data.user._current_user_getter", return_value=user) as getter:
            self.assertIs(UserBase.current, user)
            self.assertIs(User.current, user)
            self.assertIs(user.current, user)
        self.assertEqual(getter.call_count, 3)
        getter.assert_called_with(UserBase._get_current, False, False)

    def test_current_does_not_cache_user_across_contexts(self):
        first = UserBase.get_fake_system()
        second = UserBase.get_fake_system()
        with patch("bafser.data.user._current_user_getter", side_effect=[first, second]):
            self.assertIs(UserBase.current, first)
            self.assertIs(UserBase.current, second)

    def test_missing_current_user_outside_request_raises(self):
        with patch("bafser.data.user._current_user_getter", return_value=None):
            with self.assertRaisesRegex(Exception, "No current user"):
                _ = UserBase.current

    def test_missing_current_user_in_request_clears_jwt_and_returns_401(self):
        app = Flask(__name__)
        JWTManager(app)
        with app.test_request_context(), patch("bafser.data.user._current_user_getter", return_value=None):
            with self.assertRaises(HTTPException) as caught:
                _ = UserBase.current
            response = caught.exception.get_response()
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.get_json(), {"msg": "The JWT has expired"})
            self.assertTrue(any("access_token_cookie=;" in cookie for cookie in response.headers.getlist("Set-Cookie")))


if __name__ == "__main__":
    unittest.main()
