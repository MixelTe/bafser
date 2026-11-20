"""Early HTTP policy, error headers, and isolated public request behavior."""

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from flask import Request, Response, abort, g, request
from werkzeug.datastructures import WWWAuthenticate
from werkzeug.exceptions import RequestEntityTooLarge, TooManyRequests, Unauthorized
from werkzeug.test import EnvironBuilder

import bafser_config
from bafser import AppConfig, JsonObj, RequestPolicy, create_app, request_policy
from bafser.utils.get_json import get_json as read_json


class Payload(JsonObj):
    value: str


class HttpContractsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def make_app(self, policy=None, *, dev=False, details=True, log_responses=None, health=False):
        self.logger = Mock()
        with (
            patch("bafser.app.setLogging"),
            patch("bafser.app.get_logger_requests", return_value=self.logger),
            patch("bafser.app.get_logger_dashboard", return_value=Mock()),
            patch("bafser.app.register_blueprints"),
            patch("bafser.app.init_api_docs"),
            patch.object(bafser_config, "jwt_key_file_path", str(self.directory / "jwt.key")),
            patch.object(bafser_config, "images_folder", str(self.directory / "images")),
        ):
            app, _ = create_app(__name__, AppConfig(
                REQUEST_POLICY=policy, DEV_MODE=dev, LOG_ERROR_DETAILS=details,
                LOG_JSON_RESPONSES=log_responses, HEALTH_ROUTE=health,
            ))
        app.testing = True
        return app

    def test_size_rejection_precedes_json_parser_and_body_logging(self):
        app = self.make_app(RequestPolicy(max_content_length=24))

        @app.post("/api/data")
        def data():
            self.fail("oversized requests must never enter the view")

        with patch.object(Request, "get_json", side_effect=AssertionError("body was parsed")) as parse:
            response = app.test_client().post("/api/data", data='{"value":"' + "x" * 50 + '"}', content_type="application/json")
        self.assertEqual(response.status_code, 413)
        parse.assert_not_called()
        self.assertNotIn("x" * 50, str(self.logger.info.call_args_list))
        self.assertTrue(response.cache_control.no_store)

    def unknown_length_json(self, app, body):
        class MeasuredInput(io.BytesIO):
            consumed = 0

            def read(self, size=-1):
                data = super().read(size)
                self.consumed += len(data)
                return data

            def readinto(self, buffer):
                count = super().readinto(buffer)
                self.consumed += count
                return count

        stream = MeasuredInput(body)
        builder = EnvironBuilder(path="/api/data", method="POST", input_stream=stream, content_type="application/json")
        environ = builder.get_environ()
        environ.pop("CONTENT_LENGTH", None)
        environ["wsgi.input_terminated"] = True
        # The test client would rebuild this environ and restore Content-Length
        # from the seekable input, hiding the branch this helper must exercise.
        with app.request_context(environ):
            self.assertIsNone(request.content_length)
            response = app.full_dispatch_request()
            self.assertIsNone(request.content_length)
        return response, stream.consumed

    def test_unknown_length_json_accepts_only_the_complete_body_within_limit(self):
        app = self.make_app(RequestPolicy(max_content_length=24))
        entered = Mock()

        @app.post("/api/data")
        def data():
            entered()
            return {"parsed": g.json[0]}

        for body in (b"{}" + b" " * 21, b"{}" + b" " * 22):
            with self.subTest(length=len(body)):
                response, consumed = self.unknown_length_json(app, body)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.get_json(), {"parsed": {}})
                self.assertEqual(consumed, len(body))
        self.assertEqual(entered.call_count, 2)

        for body in (b"{}" + b" " * 23, b"{}" + b" " * 22 + b"INVALID_TAIL", b"{}" + b" " * 10000):
            with self.subTest(length=len(body)), patch.object(Request, "get_json", side_effect=AssertionError("JSON parser was called")):
                response, consumed = self.unknown_length_json(app, body)
                self.assertEqual(response.status_code, 413)
                self.assertLessEqual(consumed, 25)
        self.assertEqual(entered.call_count, 2)

    def test_unknown_length_json_keeps_syntax_errors_distinct_from_size(self):
        app = self.make_app(RequestPolicy(max_content_length=24))

        @app.post("/api/data")
        def data():
            self.fail("malformed JSON must not enter the view")

        response, consumed = self.unknown_length_json(app, b"{")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(consumed, 1)

    def test_unknown_length_json_uses_route_limit_after_early_stream_access(self):
        for initial, effective in ((None, 24), (10, 24), (24, 64), (64, 24)):
            with self.subTest(initial=initial, effective=effective):
                app = self.make_app(RequestPolicy(max_content_length=effective))
                app.config["MAX_CONTENT_LENGTH"] = initial

                @app.url_value_preprocessor
                def cache_stream(endpoint, values):
                    self.assertIsNone(request.content_length)
                    _ = request.stream

                @app.post("/api/data")
                def data():
                    self.assertIsNone(request.content_length)
                    return {"parsed": g.json[0]}

                for length in (effective - 1, effective):
                    response, consumed = self.unknown_length_json(app, b"{}" + b" " * (length - 2))
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.get_json(), {"parsed": {}})
                    self.assertEqual(consumed, length)
                for body in (b"{}" + b" " * (effective - 1), b"{}" + b" " * effective + b"INVALID_TAIL" * 1000):
                    response, consumed = self.unknown_length_json(app, body)
                    self.assertEqual(response.status_code, 413)
                    self.assertEqual(consumed, effective + 1)

    def test_unknown_length_size_failure_remains_rejected_on_a_second_parse_attempt(self):
        app = self.make_app()
        body = b"{}" + b" " * 22 + b"X"
        builder = EnvironBuilder(method="POST", data=body, content_type="application/json")
        environ = builder.get_environ()
        environ.pop("CONTENT_LENGTH", None)
        environ["wsgi.input_terminated"] = True
        with app.request_context(environ):
            request.max_content_length = 24
            # Accessing the limited stream first must not disable lookahead.
            _ = request.stream
            for _ in range(2):
                with self.assertRaises(RequestEntityTooLarge):
                    read_json(request)
            self.assertEqual(environ["wsgi.input"].tell(), 25)
            self.assertEqual(request.max_content_length, 24)

    def test_session_close_diagnostics_follow_error_detail_switch_and_preserve_response(self):
        for dev, details in ((False, False), (False, True), (True, False)):
            with self.subTest(dev=dev, details=details):
                app = self.make_app(dev=dev, details=details)
                session = Mock()
                session.close.side_effect = RuntimeError("PRIVATE_CLOSE_VALUE")

                @app.get("/api/data")
                def data(session=session):
                    g.db_session = session
                    return {"ok": True}

                with self.assertLogs(level="ERROR") as captured:
                    response = app.test_client().get("/api/data")
                self.assertEqual(response.status_code, 200)
                self.assertEqual("PRIVATE_CLOSE_VALUE" in "\n".join(captured.output), dev or details)
                self.assertEqual(captured.records[0].exc_info is not None, dev or details)
                session.close.assert_called_once_with()

    def test_internal_error_details_are_server_only_and_reduced_mode_omits_values(self):
        for details in (False, True):
            with self.subTest(details=details):
                app = self.make_app(details=details)

                @app.get("/api/data")
                def data():
                    raise KeyError("ticketId")

                with self.assertLogs(level="ERROR") as captured:
                    response = app.test_client().get("/api/data")
                self.assertEqual(response.status_code, 500)
                self.assertEqual(response.get_json(), {"msg": "Internal Server Error"})
                text = "\n".join(captured.output)
                self.assertIn("KeyError", text)
                self.assertEqual("ticketId" in text, details)
                self.assertEqual("Traceback" in text, details)

    def test_health_failure_details_are_server_only(self):
        for details in (False, True):
            with self.subTest(details=details):
                app = self.make_app(details=details, health=True)
                with (
                    patch("bafser.app.db_session.create_session", side_effect=OSError("DB_FAILURE_VALUE")),
                    self.assertLogs(level="ERROR") as captured,
                ):
                    response = app.test_client().get("/api/health")
                self.assertEqual(response.status_code, 500)
                self.assertEqual(response.get_json(), {"status": "unhealthy"})
                self.assertIn("Database health check failed", "\n".join(captured.output))
                self.assertEqual("DB_FAILURE_VALUE" in "\n".join(captured.output), details)

    def test_diagnostic_failure_details_preserve_successful_http_response(self):
        for details in (False, True):
            with self.subTest(details=details):
                app = self.make_app(details=details)
                self.logger.info.side_effect = RuntimeError("DIAGNOSTIC_FAILURE_VALUE")

                @app.get("/api/data")
                def data():
                    return {"ok": True}

                with self.assertLogs(level="ERROR") as captured:
                    response = app.test_client().get("/api/data")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.get_json(), {"ok": True})
                self.assertTrue(response.cache_control.no_store)
                text = "\n".join(captured.output)
                self.assertIn("Request diagnostics could not be formatted", text)
                self.assertIn("Response diagnostics could not be formatted", text)
                self.assertEqual("DIAGNOSTIC_FAILURE_VALUE" in text, details)
                self.assertEqual("Traceback" in text, details)

    def test_json_media_syntax_and_type_errors_are_distinct(self):
        app = self.make_app()

        @app.post("/api/data")
        def data():
            return Payload.get_from_req().json()

        client = app.test_client()
        self.assertEqual(client.post("/api/data", data="value").status_code, 415)
        self.assertEqual(client.post("/api/data", data="{", content_type="application/json").status_code, 400)
        self.assertEqual(client.post("/api/data", json=[]).status_code, 400)
        self.assertEqual(client.post("/api/data", json={"value": "ok"}).get_json(), {"value": "ok"})

    def test_excessively_nested_json_is_private_bad_request_before_view(self):
        for dev in (False, True):
            with self.subTest(dev=dev):
                app = self.make_app(RequestPolicy(max_content_length=4096, authenticate=False, log_body=False), dev=dev)
                @app.post("/api/deep")
                def data():
                    self.fail("excessive nesting must not enter the view")
                payload = '{"unknown":' + "[" * 1200 + '"BODY_SECRET"' + "]" * 1200 + "}"
                response = app.test_client().post("/api/deep", data=payload, content_type="application/json")
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.get_json(), {"msg": "Bad Request"})
                self.assertNotIn("BODY_SECRET", response.get_data(as_text=True))
                self.assertNotIn("BODY_SECRET", str(self.logger.info.call_args_list))

    def test_json_reader_repeatedly_rejects_excessive_nesting(self):
        from werkzeug.exceptions import BadRequest

        app = self.make_app()
        payload = "[" * 1200 + "0" + "]" * 1200
        with app.test_request_context("/api/deep", method="POST", data=payload, content_type="application/json"):
            for _ in range(2):
                with self.assertRaises(BadRequest):
                    read_json(request)

    def test_http_exceptions_keep_status_and_protocol_headers(self):
        app = self.make_app()

        @app.get("/api/error/<int:status>")
        def error(status):
            abort(status)

        @app.get("/api/limited")
        def limited():
            raise TooManyRequests(retry_after=13)

        client = app.test_client()
        for status in (400, 409, 413, 429, 503):
            with self.subTest(status=status):
                response = client.get(f"/api/error/{status}")
                self.assertEqual(response.status_code, status)
                self.assertIsInstance(response.get_json()["msg"], str)
        response = client.post("/api/limited")
        self.assertEqual(response.status_code, 405)
        self.assertIn("GET", response.headers["Allow"])
        self.assertEqual(client.get("/api/limited").headers["Retry-After"], "13")

    def test_unauthorized_keeps_challenge_and_rolls_back_once(self):
        app = self.make_app()
        session = Mock()

        @app.get("/api/private")
        @app.get("/private")
        def private():
            g.db_session = session
            raise Unauthorized(www_authenticate=WWWAuthenticate("basic", {"realm": "private"}))

        client = app.test_client()
        response = client.get("/api/private")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json(), {"msg": "Unauthorized"})
        self.assertEqual(response.www_authenticate.type, "basic")
        self.assertEqual(response.www_authenticate.parameters["realm"], "private")
        session.rollback.assert_called_once_with()
        session.commit.assert_not_called()

        session.reset_mock()
        response = client.get("/private")
        self.assertEqual(response.status_code, 302)
        self.assertIn("redirect=/private", response.headers["Location"])
        session.rollback.assert_called_once_with()
        session.commit.assert_not_called()

    def test_policy_overrides_inherit_limits_and_public_cookie_behavior(self):
        app = self.make_app(RequestPolicy(max_content_length=30, authenticate=False, sensitive_fields=("private",)))

        @app.post("/api/data")
        @request_policy(RequestPolicy(log_body=True, sensitive_fields=("other",)))
        def data():
            self.assertFalse(g.request_policy.authenticate)
            self.assertEqual(g.request_policy.sensitive_fields, ("private", "other"))
            return {"user": g.userId}

        with patch("bafser.app.verify_jwt_in_request", side_effect=AssertionError("user JWT was inspected")):
            client = app.test_client()
            self.assertEqual(client.post("/api/data", json={"value": "x" * 50}).status_code, 413)
            response = client.post("/api/data", json={})
        self.assertEqual(response.get_json(), {"user": None})
        self.assertEqual(response.headers.getlist("Set-Cookie"), [])

    def test_per_route_json_limit_does_not_break_larger_form_upload(self):
        app = self.make_app()

        @app.post("/api/purchase")
        @request_policy(RequestPolicy(max_content_length=20))
        def purchase():
            return "ok"

        @app.post("/api/upload")
        @request_policy(RequestPolicy(max_content_length=2048))
        def upload():
            return {"value": request.form["value"]}

        client = app.test_client()
        self.assertEqual(client.post("/api/purchase", json={"value": "x" * 40}).status_code, 413)
        self.assertEqual(client.post("/api/upload", data={"value": "x" * 100}).get_json(), {"value": "x" * 100})

    def test_blocked_response_diagnostics_never_materialize_json_body(self):
        app = self.make_app(RequestPolicy(log_body=False), log_responses=True)

        class UnreadResponse(Response):
            def get_data(self, *args, **kwargs):
                raise AssertionError("response was read for diagnostics")

        @app.get("/api/data")
        def data():
            return UnreadResponse('{"secret":"hidden"}', content_type="application/json")

        response = app.test_client().get("/api/data")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("hidden", str(self.logger.info.call_args_list))

    def test_http_failure_rolls_back_current_session(self):
        app = self.make_app()
        session = Mock()

        @app.get("/api/data")
        def data():
            g.db_session = session
            abort(409)

        self.assertEqual(app.test_client().get("/api/data").status_code, 409)
        session.rollback.assert_called_once()
        session.commit.assert_not_called()

    def test_unexpected_json_parser_failure_is_private_500(self):
        app = self.make_app()

        @app.post("/api/data")
        def data():
            return "ok"

        with patch.object(Request, "get_json", side_effect=RuntimeError("PRIVATE parser value")):
            response = app.test_client().post("/api/data", data="{}", content_type="application/json")
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("PRIVATE", response.get_data(as_text=True))

    def test_policy_configuration_rejects_invalid_types(self):
        for values in ({"max_content_length": True}, {"max_log_length": 0}, {"sensitive_fields": None}, {"authenticate": 1}):
            with self.subTest(values=values), self.assertRaises((TypeError, ValueError)):
                RequestPolicy(**values)
