"""API defaults and explicit file caching must not expose authenticated responses."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from flask import abort, jsonify, make_response, send_file

import bafser_config

from bafser import AppConfig, create_app, create_file_response, protected_route


class CacheControlTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.file = self.directory / "example.bin"
        self.file.write_bytes(b"private file")
        (self.directory / "index.html").write_bytes(b"<!doctype html><title>Frontend</title>")
        self.app = self.create_app()
        self.client = self.app.test_client()

        @self.app.route("/api/value", methods=["GET", "POST"])
        def value():
            return jsonify(value="account data")

        @self.app.get("/api/error/<int:status>")
        def error(status: int):
            abort(status)

        @self.app.get("/api/protected")
        @protected_route()
        def protected():
            self.fail("Missing JWT must prevent entering the handler")

        @self.app.get("/api/file")
        def file():
            return create_file_response(str(self.file), "application/octet-stream", "download.bin", True)

        @self.app.get("/api/native-file")
        def native_file():
            return send_file(self.file)

    def create_app(self):
        with (
            patch("bafser.app.setLogging"),
            patch("bafser.app.get_logger_requests", return_value=Mock()),
            patch("bafser.app.get_logger_dashboard", return_value=Mock()),
            patch("bafser.app.register_blueprints"),
            patch("bafser.app.init_api_docs"),
            patch.object(bafser_config, "jwt_key_file_path", str(self.directory / "jwt.key")),
            patch.object(bafser_config, "images_folder", str(self.directory / "images")),
            patch.object(bafser_config, "allow_unsupported_for_update_clause", None, create=True),
        ):
            app, _ = create_app(__name__, AppConfig(FRONTEND_FOLDER=str(self.directory)))
        app.testing = True
        return app

    def assert_private_no_store(self, response):
        self.addCleanup(response.close)
        self.assertTrue(response.cache_control.private)
        self.assertTrue(response.cache_control.no_store)
        self.assertFalse(response.cache_control.public)

    def test_default_applies_to_get_head_post_and_options(self):
        for method in ("GET", "HEAD", "POST", "OPTIONS"):
            with self.subTest(method=method):
                response = self.client.open("/api/value", method=method)
                self.assertEqual(response.status_code, 200)
                self.assert_private_no_store(response)

    def test_errors_authentication_and_api_root_are_not_cacheable(self):
        for path, method, status in (
            ("/api/protected", "GET", 401),
            ("/api/error/403", "GET", 403),
            ("/api/missing", "GET", 404),
            ("/api", "GET", 404),
            ("/api/", "GET", 404),
            ("/api/value", "DELETE", 405),
            ("/api/error/500", "GET", 500),
        ):
            with self.subTest(path=path, method=method):
                response = self.client.open(path, method=method)
                self.assertEqual(response.status_code, status)
                self.assert_private_no_store(response)

    def test_route_policies_keep_their_directives_and_public_requires_opt_in(self):
        policies = ("private, max-age=120", "public, max-age=600, immutable", "no-cache", "max-age=30", "no-store", "")
        for index, policy in enumerate(policies):
            def handler(policy=policy):
                response = make_response("value")
                response.headers["Cache-Control"] = policy
                response.headers["Vary"] = "Accept-Language"
                return response

            self.app.add_url_rule(f"/api/policy/{index}", f"policy_{index}", handler)
        for index, policy in enumerate(policies):
            with self.subTest(policy=policy):
                response = self.client.get(f"/api/policy/{index}")
                self.addCleanup(response.close)
                self.assertEqual(response.headers["Vary"], "Accept-Language")
                if policy.startswith("public"):
                    self.assertEqual(response.headers["Cache-Control"], policy)
                else:
                    self.assertTrue(response.cache_control.private)
                    self.assertFalse(response.cache_control.public)
                if "max-age=" in policy:
                    self.assertIn(policy.split(", ")[-1] if "immutable" not in policy else "immutable", response.headers["Cache-Control"])
                    self.assertIsNotNone(response.cache_control.max_age)
                if policy == "no-cache":
                    self.assertTrue(response.cache_control.no_cache)
                if policy in ("no-store", ""):
                    self.assertTrue(response.cache_control.no_store)

    def test_file_helper_keeps_streaming_and_uses_private_no_store(self):
        response = self.client.get("/api/file")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.is_streamed)
        self.assertEqual(response.data, b"private file")
        self.assertIn("attachment; filename=download.bin", response.headers["Content-Disposition"])
        self.assert_private_no_store(response)

    def test_native_flask_file_cannot_be_shared_by_default(self):
        response = self.client.get("/api/native-file")
        self.addCleanup(response.close)
        self.assertTrue(response.cache_control.private)
        self.assertTrue(response.cache_control.no_cache)
        self.assertFalse(response.cache_control.public)

    def test_private_file_conditional_response_keeps_its_cache_policy(self):
        first = self.client.get("/api/file")
        self.addCleanup(first.close)
        response = self.client.get("/api/file", headers={"If-None-Match": first.headers["ETag"]})
        self.assertEqual(response.status_code, 304)
        self.assert_private_no_store(response)

    def test_file_helper_supports_explicit_private_and_public_caching(self):
        for index, policy in enumerate(("private, max-age=3600", "public, max-age=31536000, immutable")):
            def handler(policy=policy):
                return create_file_response(str(self.file), "application/octet-stream", "example.bin", cache_control=policy)

            self.app.add_url_rule(f"/api/cached/{index}", f"cached_{index}", handler)
        for index, policy in enumerate(("private, max-age=3600", "public, max-age=31536000, immutable")):
            with self.subTest(policy=policy):
                response = self.client.get(f"/api/cached/{index}")
                self.addCleanup(response.close)
                self.assertEqual(response.headers["Cache-Control"], policy)
                self.assertEqual(response.data, b"private file")

    def test_missing_file_and_non_api_file_default(self):
        @self.app.get("/api/missing-file")
        def missing_file():
            return create_file_response(str(self.directory / "missing.bin"), "application/octet-stream", "missing.bin")

        @self.app.get("/download")
        def download():
            return create_file_response(str(self.file), "application/octet-stream", "example.bin")

        self.assertEqual(self.client.get("/api/missing-file").status_code, 404)
        self.assert_private_no_store(self.client.get("/api/missing-file"))
        self.assert_private_no_store(self.client.get("/download"))

    def test_custom_api_prefix_and_similarly_named_frontend_path(self):
        with patch.object(bafser_config, "api_url", "/service/v2/"):
            app = self.create_app()
        client = app.test_client()
        for path in ("/service/v2", "/service/v2/missing"):
            with self.subTest(path=path):
                response = client.get(path)
                self.assertEqual(response.status_code, 404)
                self.assert_private_no_store(response)
        for path in ("/apiary", "/service/v20"):
            with self.subTest(path=path):
                response = client.get(path)
                self.addCleanup(response.close)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.cache_control.public)
