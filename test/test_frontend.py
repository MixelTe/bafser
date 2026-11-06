"""Regression tests for SPA routes that share names with asset directories."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import bafser_config

from bafser import AppConfig, create_app


class FrontendTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.frontend = self.directory / "frontend"
        self.frontend.mkdir()
        self.index = b"<!doctype html><title>TicketSystem</title>"
        (self.frontend / "index.html").write_bytes(self.index)

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
            self.app, _ = create_app(
                __name__,
                AppConfig(FRONTEND_FOLDER=str(self.frontend)),
            )
        self.app.testing = True
        self.client = self.app.test_client()

    def assert_page(self, path, expected):
        response = self.client.get(path)
        self.addCleanup(response.close)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, expected)
        self.assertNotIn("immutable", response.headers["Cache-Control"])

    def test_existing_directories_do_not_hide_spa_routes(self):
        (self.frontend / "fonts" / "nested").mkdir(parents=True)
        for path in ("/fonts", "/fonts/", "/fonts/nested", "/fonts/nested/"):
            with self.subTest(path=path):
                self.assert_page(path, self.index)

    def test_html_page_is_preferred_to_a_same_named_directory(self):
        (self.frontend / "help").mkdir()
        content = b"<!doctype html><title>Help</title>"
        (self.frontend / "help.html").write_bytes(content)
        self.assert_page("/help", content)

    def test_directory_with_html_suffix_does_not_hide_spa_fallback(self):
        (self.frontend / "help.html").mkdir()
        self.assert_page("/help", self.index)

    def test_bundled_assets_keep_their_content_and_immutable_cache(self):
        assets = {
            "fonts/fonts.css": b"@font-face {}",
            "fonts/example.woff2": b"font data",
            "static/app.js": b"console.log('app');",
            "static/version": b"release",
        }
        for name, content in assets.items():
            path = self.frontend / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            with self.subTest(path=name):
                response = self.client.get("/" + name)
                self.addCleanup(response.close)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data, content)
                self.assertIn("immutable", response.headers["Cache-Control"])
                self.assertIn("max-age=31536000", response.headers["Cache-Control"])

    def test_html_under_a_static_prefix_uses_page_cache(self):
        (self.frontend / "fonts").mkdir()
        content = b"<!doctype html><title>Font help</title>"
        (self.frontend / "fonts" / "help.html").write_bytes(content)
        for path in ("/fonts/help", "/fonts/help.html"):
            with self.subTest(path=path):
                self.assert_page(path, content)

    def test_missing_files_and_api_paths_do_not_receive_spa_html(self):
        for path in ("/fonts/missing.woff2", "/static/missing.js", "/missing.css", "/api/missing"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.addCleanup(response.close)
                self.assertEqual(response.status_code, 404)
                self.assertNotEqual(response.data, self.index)

    def test_files_outside_frontend_are_not_exposed(self):
        secret = b"PRIVATE test fixture"
        (self.directory / "outside.txt").write_bytes(secret)
        (self.directory / "outside.html").write_bytes(secret)
        for path in ("/../outside.txt", "/%2e%2e/outside.txt", "/../outside"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.addCleanup(response.close)
                self.assertEqual(response.status_code, 404)
                self.assertNotIn(secret, response.data)
