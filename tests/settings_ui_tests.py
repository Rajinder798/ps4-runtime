# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Real Tk controls and persisted backend integration, never guest evidence."""
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
import ps4_settings as ui
import runtime_settings as settings


class EntryTests(unittest.TestCase):
    def test_help_without_tk_or_window(self):
        result = subprocess.run([sys.executable, str(ROOT / "tools/ps4_settings.py"), "--help"],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--state-dir", result.stdout)
        self.assertIn("--title", result.stdout)


@unittest.skipUnless(sys.platform == "win32", "Windows Settings UI")
class WindowTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name) / "preferences \u03bb"
        # Missing Tk/display is a test failure on supported Windows CI.
        self.root = tk.Tk()
        self.addCleanup(self.root.destroy)
        self.window = ui.SettingsWindow(self.root, self.home)
        self.root.update()

    def scope(self, index):
        self.window.scope.current(index)
        self.window.scope.event_generate("<<ComboboxSelected>>")
        self.root.update()

    def test_live_cross_letter_global_title_inheritance_and_unrelated_saves(self):
        self.window.cross_key.current(2)
        self.window.cross_key.event_generate("<<ComboboxSelected>>"); self.root.update()
        self.window.save_button.invoke()
        self.assertEqual(self.saved()["effective_settings"]["cross_key"],"g")
        self.scope(4)
        self.assertIn("Cross G (from global)",self.window.effective.get())
        self.window.cross_key.current(1)
        self.window.cross_key.event_generate("<<ComboboxSelected>>"); self.root.update()
        self.window.save_button.invoke()
        self.choose("Warning"); self.window.save_button.invoke()
        self.assertEqual(self.saved(launcher.LIVE_PROFILE)["effective_settings"]["cross_key"],"n")
        self.window.cross_key.current(0)
        self.window.cross_key.event_generate("<<ComboboxSelected>>"); self.root.update()
        self.window.save_button.invoke()
        self.assertEqual(self.saved(launcher.LIVE_PROFILE)["effective_settings"]["cross_key"],"g")
        self.scope(3)
        self.assertTrue(self.window.cross_key.instate(["disabled"]))
        self.assertNotIn("cross_key",self.saved(launcher.AV_PROFILE)["defaults"])

    def choose(self, label):
        self.window.level.current(ui.LEVELS.index(label) + 1)
        self.window.level.event_generate("<<ComboboxSelected>>")
        self.root.update()

    def saved(self, title=None):
        return settings.inspect(self.home, launcher.PROFILES, title)

    def test_av_self_test_scope_saves_and_reopens_diagnostic_override(self):
        self.scope(3)
        self.assertEqual(self.window.title, launcher.AV_PROFILE)
        self.choose("Warning")
        self.window.save_button.invoke()
        self.assertEqual(self.saved(launcher.AV_PROFILE)["settings_sources"]["log_level"],"title")
        self.root.withdraw()
        import tkinter as tk
        reopened_root = tk.Tk()
        self.addCleanup(reopened_root.destroy)
        reopened = ui.SettingsWindow(reopened_root,self.home,launcher.AV_PROFILE)
        reopened_root.update()
        self.assertIn("Warning (from title override)",reopened.effective.get())

    def test_live_scope_controls_save_reopen_and_reset_supported_audio(self):
        self.assertEqual(len(ui.SCOPES),len(ui.TITLES))
        self.scope(4)
        self.assertEqual(self.window.title,launcher.LIVE_PROFILE)
        self.assertTrue(self.window.audio_available)
        self.choose("Debug")
        self.window.volume.current(2)
        self.window.volume.event_generate("<<ComboboxSelected>>");self.root.update()
        self.window.save_button.invoke()
        saved=self.saved(launcher.LIVE_PROFILE)
        self.assertEqual(saved["settings"]["schema_version"],3)
        self.assertEqual(saved["effective_settings"],{"log_level":"debug","volume_percent":50,"cross_key":"n"})
        self.window.refresh_button.invoke()
        self.assertEqual(self.window.volume.get(),"Half (50%)")
        self.window.reset_button.invoke()
        self.assertEqual(self.saved(launcher.LIVE_PROFILE)["effective_settings"],{"log_level":"info","volume_percent":100,"cross_key":"n"})

    def test_save_reopen_inherit_and_scope_reset(self):
        self.assertFalse(self.home.exists())
        self.assertEqual(self.window.location_entry.get(), str(self.home.resolve()))
        self.assertIn("Info (from default)", self.window.effective.get())
        self.choose("Warning")
        self.assertFalse(self.home.exists())
        self.assertIn("not saved", self.window.status.get())
        self.window.save_button.invoke()
        self.assertEqual(self.saved()["effective_settings"]["log_level"], "warning")
        self.scope(1)
        self.assertIn("Warning (from global preference)", self.window.effective.get())
        self.choose("Debug")
        self.window.save_button.invoke()
        self.scope(2)
        self.assertIn("Warning (from global preference)", self.window.effective.get())
        # A second window re-reads persistent state, not a shared UI model.
        import tkinter as tk
        reopened = tk.Toplevel(self.root)
        second = ui.SettingsWindow(reopened, self.home, "hello-world")
        self.root.update()
        self.assertEqual(second.level.get(), "Debug")
        self.assertIn("Debug (from title override)", second.effective.get())
        second.reset_button.invoke()
        self.assertIn("Warning (from global preference)", second.effective.get())
        reopened.destroy()
        self.scope(0)
        self.window.reset_button.invoke()
        self.assertIn("Info (from default)", self.window.effective.get())

    def test_inherit_save_reset_all_and_refresh_discard(self):
        self.choose("Warning")
        self.window.save_button.invoke()
        self.scope(1)
        self.choose("Debug")
        self.window.save_button.invoke()
        self.window.level.current(0)
        self.window.level.event_generate("<<ComboboxSelected>>")
        self.window.save_button.invoke()
        self.assertNotIn("hello-world", self.saved()["settings"]["titles"])
        self.choose("Debug")
        self.window.refresh_button.invoke()
        self.assertEqual(self.window.level.current(), 0)
        self.assertTrue(self.window.save_button.instate(["disabled"]))
        self.choose("Debug")
        self.window.save_button.invoke()
        self.window.reset_all_button.invoke()
        self.assertEqual(self.saved()["settings"], {"schema_version": 1, "global": {}, "titles": {}})
        self.assertIn("Info (from default)", self.window.effective.get())

    def test_invalid_startup_and_external_change_preserved(self):
        self.choose("Warning")
        self.window.save_button.invoke()
        invalid = b'{"schema_version":5,"global":{},"titles":{}}'
        path = self.home / settings.FILE_NAME
        path.write_bytes(invalid)
        self.choose("Debug")
        self.window.save_button.invoke()
        self.assertIn("invalid_settings", self.window.status.get())
        self.assertEqual(path.read_bytes(), invalid)
        self.window.refresh_button.invoke()
        for button in (self.window.save_button, self.window.reset_button, self.window.reset_all_button):
            self.assertTrue(button.instate(["disabled"]))
        self.assertIn("unavailable", self.window.effective.get())
        self.assertEqual(path.read_bytes(), invalid)
        # Repair is an explicit external action; Refresh restores usable controls.
        path.write_text(json.dumps({"schema_version": 1, "global": {}, "titles": {}}))
        self.window.refresh_button.invoke()
        self.assertTrue(self.window.reset_button.instate(["!disabled"]))

    def test_busy_and_write_failure_visible_without_losing_saved_values(self):
        self.choose("Warning")
        self.window.save_button.invoke()
        original = (self.home / settings.FILE_NAME).read_bytes()
        self.choose("Debug")
        with settings.writer(self.home):
            self.window.save_button.invoke()
        self.assertIn("settings_busy", self.window.status.get())
        self.assertEqual((self.home / settings.FILE_NAME).read_bytes(), original)
        with patch.object(settings.os, "replace", side_effect=OSError("test write failure")):
            self.window.save_button.invoke()
        self.assertIn("settings_write_failed", self.window.status.get())
        self.assertEqual((self.home / settings.FILE_NAME).read_bytes(), original)
        self.assertEqual(self.window.level.get(), "Debug")
        self.window.save_button.invoke()
        self.assertIn("Saved.", self.window.status.get())
        self.assertEqual(self.saved()["effective_settings"]["log_level"], "debug")

    def test_tk_initialization_failure_is_visible_and_does_not_change_state(self):
        import tkinter as tk
        with patch.object(sys, "argv", ["ps4_settings.py", "--state-dir", str(self.home)]), \
                patch.object(tk, "Tk", side_effect=tk.TclError("test unavailable display")), \
                patch.object(ui, "unavailable") as notice:
            self.assertEqual(ui.main(), 4)
            notice.assert_called_once_with()
        self.assertFalse(self.home.exists())

    def test_volume_persistence_inheritance_and_diagnostic_edits_are_independent(self):
        self.assertLessEqual(self.window.location_entry.winfo_rooty()+self.window.location_entry.winfo_height(),
                             self.root.winfo_rooty()+self.root.winfo_height())
        self.assertTrue(self.window.save_button.winfo_viewable())
        self.window.volume.current(2)  # Half
        self.window.volume.event_generate("<<ComboboxSelected>>"); self.root.update()
        self.window.save_button.invoke()
        self.assertEqual(self.saved()["effective_settings"]["volume_percent"],50)
        self.scope(3)
        self.assertIn("Volume 50% (from global)",self.window.effective.get())
        self.window.volume.current(1)  # Mute
        self.window.volume.event_generate("<<ComboboxSelected>>"); self.root.update()
        self.choose("Warning")
        self.window.save_button.invoke()
        self.assertEqual(self.saved(launcher.AV_PROFILE)["effective_settings"],{"log_level":"warning","volume_percent":0})
        self.choose("Debug")
        self.window.save_button.invoke()
        self.assertEqual(self.saved(launcher.AV_PROFILE)["effective_settings"]["volume_percent"],0)
        self.window.volume.current(0)  # Inherit only volume, retain Debug.
        self.window.volume.event_generate("<<ComboboxSelected>>"); self.root.update()
        self.window.save_button.invoke()
        self.assertEqual(self.saved(launcher.AV_PROFILE)["effective_settings"],{"log_level":"debug","volume_percent":50})
        self.scope(1)
        self.assertTrue(self.window.volume.instate(["disabled"]))
        self.choose("Warning")
        self.window.save_button.invoke()
        self.assertNotIn("volume_percent",self.saved("hello-world")["effective_settings"])


if __name__ == "__main__":
    unittest.main()
