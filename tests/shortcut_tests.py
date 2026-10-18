# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Shortcut policy, desktop error handling and real Windows COM metadata tests."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import ps4_launch as launcher
import ps4_desktop as desktop
import homebrew_shortcut as shortcut

HELPER = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path("unsupported")
sys.argv = sys.argv[:1]


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()

    def test_desktop_success_has_no_dialog_and_retains_response(self):
        response = dict(schema_version=1, operation="launch", status="completed", session_id="test-policy")
        with patch.object(launcher, "launch", return_value=(0, response)), patch.object(desktop, "show_error") as dialog:
            self.assertEqual(desktop.run(self.root, "hello-world"), 0)
            dialog.assert_not_called()
        files = list((self.root / "desktop-results").glob("*.json"))
        self.assertEqual(len(files), 1)
        self.assertEqual(json.loads(files[0].read_text()), response)

    def test_desktop_failure_has_a_visible_message_and_local_result(self):
        response = dict(schema_version=1, status="failed", error=dict(code="guest_failed", message="Guest failed."),
                        logs_directory=str(self.root / "session"))
        with patch.object(launcher, "launch", return_value=(5, response)), patch.object(desktop, "show_error") as dialog:
            self.assertEqual(desktop.run(self.root, "hello-world"), 5)
            self.assertIn(str(self.root / "session"), dialog.call_args.args[0])
        result = json.loads(next((self.root / "desktop-results").glob("*.json")).read_text())
        self.assertEqual(result["error"]["code"], "guest_failed")

    def test_desktop_storage_failure_is_not_silent(self):
        response = dict(schema_version=1, status="completed")
        with patch.object(launcher, "launch", return_value=(0, response)), patch.object(Path, "mkdir", side_effect=OSError("disk full")), patch.object(desktop, "show_error") as dialog:
            self.assertEqual(desktop.run(self.root, "hello-world"), 6)
            dialog.assert_called_once()

    def test_unexpected_desktop_failure_is_reported(self):
        with patch.object(launcher, "launch", side_effect=RuntimeError("unexpected failure")), patch.object(desktop, "show_error") as dialog:
            self.assertEqual(desktop.run(self.root, "hello-world"), 6)
            dialog.assert_called_once()
        result = json.loads(next((self.root / "desktop-results").glob("*.json")).read_text())
        self.assertEqual(result["error"]["code"], "session_failed")
        self.assertIsNone(result["guest_entry_observed"])

    def test_creation_is_atomic_and_refuses_existing_files(self):
        expected = dict(schema_version=1, target="pythonw.exe", arguments="fixed test command",
                        working_directory=str(self.root), description="policy test, not guest execution")
        directory = self.root / "shortcuts"
        def adapter(helper, action, staged, *arguments, runtime):
            if action == "create":
                staged.write_bytes(b"original test shortcut")
            return expected
        with patch.object(launcher, "supported_host", return_value=True), patch.object(launcher, "read_config"), patch.object(launcher, "check_inputs"), patch.object(shortcut, "properties", return_value=expected), patch.object(shortcut, "adapter", side_effect=adapter):
            result = shortcut.create(self.root, "hello-world", directory, Path(sys.executable), runtime=launcher)
            path = Path(result["shortcut"])
            self.assertFalse(result["engine_launch_attempted"])
            self.assertEqual(path.read_bytes(), b"original test shortcut")
            with self.assertRaises(launcher.LaunchError) as error:
                shortcut.create(self.root, "hello-world", directory, Path(sys.executable), runtime=launcher)
            self.assertEqual(error.exception.code, "shortcut_exists")
            self.assertEqual(path.read_bytes(), b"original test shortcut")
            path.unlink()
            with patch.object(shortcut.os, "link", side_effect=FileExistsError("concurrent creator")):
                with self.assertRaises(launcher.LaunchError) as error:
                    shortcut.create(self.root, "hello-world", directory, Path(sys.executable), runtime=launcher)
                self.assertEqual(error.exception.code, "shortcut_exists")
            self.assertEqual(list(directory.iterdir()), [])
            with patch.object(shortcut, "adapter", return_value={"target": "wrong command"}):
                with self.assertRaises(launcher.LaunchError):
                    shortcut.create(self.root, "hello-world", directory, Path(sys.executable), runtime=launcher)
            self.assertEqual(list(directory.iterdir()), [])

    def test_cli_errors_are_structured_and_do_not_create_shortcuts(self):
        process = subprocess.run([sys.executable, str(ROOT / "tools/ps4_launch.py"), "--state-dir", str(self.root),
            "shortcut", "hello-world", "--directory", str(self.root / "links"), "--helper", str(HELPER), "--json"],
            capture_output=True, text=True, timeout=10)
        self.assertIn(process.returncode, (3, 4))
        self.assertFalse(process.stderr)
        self.assertEqual(json.loads(process.stdout)["status"], "failed")
        self.assertFalse((self.root / "links").exists())


@unittest.skipUnless(sys.platform == "win32", "Windows Shell Link COM adapter")
class NativeTests(unittest.TestCase):
    def test_native_unicode_and_quoted_argument_metadata_roundtrip(self):
        with tempfile.TemporaryDirectory(prefix="shortcut \u03bb ") as directory:
            root = Path(directory).resolve()
            link = root / "test \u03bb.lnk"
            expected = dict(schema_version=1, target=str(Path(sys.executable).resolve()),
                arguments=subprocess.list2cmdline(["space argument", 'quote"argument', "trailing\\", "\u03bb", "line\nfeed"]),
                working_directory=str(root), description='Unicode \u03bb, quotes " and newline\n')
            created = shortcut.adapter(HELPER, "create", link, expected["target"], expected["arguments"],
                                       expected["working_directory"], expected["description"], runtime=launcher)
            self.assertEqual(created, expected)
            self.assertEqual(shortcut.adapter(HELPER, "inspect", link, runtime=launcher), expected)
            original = link.read_bytes()
            with self.assertRaises(launcher.LaunchError):
                shortcut.adapter(HELPER, "create", link, expected["target"], "overwrite", root, "overwrite", runtime=launcher)
            self.assertEqual(link.read_bytes(), original)

    def test_helper_rejects_usage_and_relative_paths(self):
        self.assertEqual(subprocess.run([str(HELPER)], capture_output=True, timeout=10).returncode, 2)
        result = subprocess.run([str(HELPER), "inspect", "relative.lnk"], capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 1)
        self.assertFalse(result.stdout)


if __name__ == "__main__":
    unittest.main()
