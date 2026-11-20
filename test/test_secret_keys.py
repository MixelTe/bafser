"""Secret bootstrap publishes one complete file and never replaces existing keys."""

import importlib
import multiprocessing
import os
import stat
import tempfile
import traceback
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

from bafser.utils.get_secret_key import get_secret_key, get_secret_key_rnd


def _create_key_in_process(path):
    return get_secret_key_rnd(path)


class SecretKeyTests(unittest.TestCase):
    def test_runtime_missing_key_does_not_create_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing" / "key.txt"
            with self.assertRaises(FileNotFoundError):
                get_secret_key(str(path))
            self.assertFalse(path.parent.exists())

    def test_existing_key_is_preserved_verbatim_and_not_rewritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "key.txt"
            path.write_bytes(b"existing-key\r\n")
            modified = path.stat().st_mtime_ns
            self.assertEqual(get_secret_key(str(path)), "existing-key\r\n")
            self.assertEqual(get_secret_key_rnd(str(path)), "existing-key\r\n")
            self.assertEqual(path.stat().st_mtime_ns, modified)
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_empty_existing_key_is_rejected_without_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "key.txt"
            for value in ("", " \n\t\r"):
                with self.subTest(value=value):
                    path.write_text(value, encoding="utf8")
                    before = path.read_bytes()
                    for reader in (get_secret_key, get_secret_key_rnd):
                        with self.assertRaisesRegex(ValueError, "must not be empty"):
                            reader(str(path))
                    self.assertEqual(path.read_bytes(), before)

    def test_invalid_utf8_error_does_not_disclose_key_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "key.txt"
            path.write_bytes(b"\xffPRIVATE_KEY_BYTES")
            try:
                get_secret_key(str(path))
            except ValueError as error:
                self.assertNotIn("PRIVATE_KEY_BYTES", "".join(traceback.format_exception(error)))
            else:
                self.fail("Invalid UTF-8 was accepted")

    def test_new_key_is_complete_private_and_has_no_temporary_files(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "key.txt"
            key = get_secret_key_rnd(str(path))
            self.assertEqual(len(bytes.fromhex(key)), 32)
            self.assertEqual(get_secret_key(str(path)), key)
            self.assertEqual(list(path.parent.iterdir()), [path])
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(path.stat().st_mode) & 0o077, 0)

    def test_simultaneous_threads_receive_the_same_complete_key(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "key.txt"
            barrier = Barrier(8)

            def create(_):
                barrier.wait(timeout=10)
                return get_secret_key_rnd(str(path))

            with ThreadPoolExecutor(max_workers=8) as executor:
                keys = list(executor.map(create, range(8)))
            self.assertEqual(len(set(keys)), 1)
            self.assertEqual(len(keys[0]), 64)
            self.assertEqual(get_secret_key(str(path)), keys[0])
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_simultaneous_processes_receive_the_same_key(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "key.txt"
            with multiprocessing.get_context("spawn").Pool(4) as processes:
                keys = processes.map(_create_key_in_process, [str(path)] * 12)
            self.assertEqual(len(set(keys)), 1)
            self.assertEqual(get_secret_key(str(path)), keys[0])
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_loser_reads_winner_and_cleans_its_unpublished_file(self):
        module = importlib.import_module("bafser.utils.get_secret_key")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "key.txt"

            def publish_winner(source, destination):
                Path(destination).write_text("winner-key", encoding="utf8")
                raise FileExistsError()

            with patch.object(module.os, "link", side_effect=publish_winner):
                self.assertEqual(get_secret_key_rnd(str(path)), "winner-key")
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_unsupported_publication_fails_without_leaving_a_key_or_temp_file(self):
        module = importlib.import_module("bafser.utils.get_secret_key")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "key.txt"
            with patch.object(module.os, "link", side_effect=OSError("unsupported filesystem")):
                with self.assertRaisesRegex(OSError, "must support hard links"):
                    get_secret_key_rnd(str(path))
            self.assertEqual(list(path.parent.iterdir()), [])

    def test_failed_write_sync_does_not_publish_incomplete_key(self):
        module = importlib.import_module("bafser.utils.get_secret_key")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "key.txt"
            with patch.object(module.os, "fsync", side_effect=OSError("write failed")):
                with self.assertRaisesRegex(OSError, "write failed"):
                    get_secret_key_rnd(str(path))
            self.assertEqual(list(path.parent.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
