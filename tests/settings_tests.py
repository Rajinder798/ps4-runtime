# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Preference persistence/validation and launch propagation, not guest evidence."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import ps4_launch as launcher
import runtime_settings as settings


class SettingsTests(unittest.TestCase):
    def test_cross_key_schema_scope_snapshot_and_reset_preserve_other_settings(self):
        self.update(changes={"log_level":"warning", "volume_percent":50})
        path = self.home / settings.FILE_NAME
        old = path.read_bytes()
        self.assertEqual(self.inspect(launcher.LIVE_PROFILE)["effective_settings"]["cross_key"], "n")
        self.assertEqual(path.read_bytes(), old)
        self.update(changes={"cross_key":"g"})
        self.assertEqual(self.inspect()["settings"]["schema_version"], 4)
        self.assertNotIn("cross_key", self.inspect(launcher.AV_PROFILE)["effective_settings"])
        self.assertNotIn("cross_key", self.inspect("hello-world")["effective_settings"])
        self.update(title=launcher.LIVE_PROFILE, changes={"cross_key":"n"})
        self.assertEqual(self.inspect(launcher.LIVE_PROFILE)["settings_sources"]["cross_key"], "title")
        self.update(title=launcher.LIVE_PROFILE, changes={"volume_percent":0})
        self.assertEqual(self.inspect()["settings"]["schema_version"], 4)
        self.update(title=launcher.LIVE_PROFILE, reset=True, reset_key="cross_key")
        result = self.inspect(launcher.LIVE_PROFILE)
        self.assertEqual(result["effective_settings"], {"log_level":"warning", "volume_percent":0, "cross_key":"g"})
        self.assertEqual(result["settings_sources"]["cross_key"], "global")
        self.update(reset=True, reset_key="cross_key")
        self.assertEqual(self.inspect(launcher.LIVE_PROFILE)["effective_settings"]["cross_key"], "n")
        self.assertEqual(self.inspect()["settings"]["schema_version"], 4)

    def test_cross_key_invalid_types_old_schemas_and_failed_upgrade_preserve_bytes(self):
        self.update(level="info")
        path = self.home / settings.FILE_NAME
        before = path.read_bytes()
        for title, value in ((None,"space"),(None,"G"),(None,True),(None,0),(None,["g"]),
                             (launcher.AV_PROFILE,"g"),("hello-world","n")):
            with self.subTest(title=title,value=value), self.assertRaises(settings.SettingsError):
                self.update(title=title, changes={"cross_key":value})
            self.assertEqual(path.read_bytes(), before)
        with patch.object(settings.os, "replace", side_effect=OSError("failed upgrade")):
            with self.assertRaises(settings.SettingsError): self.update(changes={"cross_key":"g"})
        self.assertEqual(path.read_bytes(), before)
        for version in (1,2,3):
            document = dict(schema_version=version, **{"global":{"cross_key":"g"},"titles":{}})
            path.write_text(json.dumps(document), encoding="utf-8")
            before = path.read_bytes()
            with self.assertRaises(settings.SettingsError): self.update(reset_all=True)
            self.assertEqual(path.read_bytes(), before)

    def test_cross_key_cli_validation_upgrade_and_reset(self):
        def run(*arguments):
            return subprocess.run([sys.executable,str(ROOT/"tools/ps4_launch.py"),"--state-dir",str(self.home),
                "settings",*arguments,"--json"],capture_output=True,text=True,timeout=10)
        for arguments in (("set","cross_key","space"),("set","cross_key","g","--title","interactive-av"),
                          ("reset","--key","cross_key","--title","hello-world")):
            self.assertEqual(run(*arguments).returncode,2)
            self.assertFalse(self.home.exists())
        result = run("set","cross_key","g")
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout)["settings"]["schema_version"],4)
        self.assertEqual(run("reset","--key","cross_key").returncode,0)
        self.assertEqual(self.inspect(launcher.LIVE_PROFILE)["effective_settings"]["cross_key"],"n")

    def test_live_cross_key_is_snapshotted_before_guest_and_invalid_key_blocks_launch(self):
        self.update(changes={"cross_key":"g"})
        seen=[]
        def attempt(**kwargs):
            seen.append(kwargs["cross_key"])
            self.update(changes={"cross_key":"n"})
            return 1,dict(engine_launch_attempted=True,guest_entry_observed=True,guest_execution_tested=True,
                          transport=dict(tree_cleanup=True))
        with patch.object(launcher,"read_config",return_value={}), patch.object(launcher,"check_inputs",return_value={}), \
                patch.object(launcher,"supported_host",return_value=True), patch.object(launcher.live,"run_session",side_effect=attempt):
            code, result = launcher.launch(self.home,launcher.LIVE_PROFILE)
        self.assertEqual(seen,["g"])
        self.assertEqual(result["effective_settings"]["cross_key"],"g")
        self.assertEqual(self.inspect(launcher.LIVE_PROFILE)["effective_settings"]["cross_key"],"n")
        document=self.inspect()["settings"];document["global"]["cross_key"]="space"
        path=self.home/settings.FILE_NAME;path.write_text(json.dumps(document),encoding="utf-8")
        before=set((self.home/"sessions").iterdir())
        with patch.object(launcher,"read_config",return_value={}), patch.object(launcher,"check_inputs",return_value={}), \
                patch.object(launcher.live,"run_session") as execute:
            code, result = launcher.launch(self.home,launcher.LIVE_PROFILE)
        execute.assert_not_called()
        self.assertEqual(code,3)
        self.assertEqual(set((self.home/"sessions").iterdir()),before)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name).resolve() / "preferences \u03bb"

    def inspect(self, title=None):
        return settings.inspect(self.home, launcher.PROFILES, title)

    def update(self, **kwargs):
        return settings.update(self.home, launcher.PROFILES, **kwargs)

    def test_absent_file_has_defaults_without_creating_state(self):
        result = self.inspect("hello-world")
        self.assertEqual(result["effective_settings"], {"log_level": "info"})
        self.assertEqual(result["settings_sources"], {"log_level": "default"})
        self.assertFalse(self.home.exists())
        result["defaults"]["log_level"] = "invalid"
        self.assertEqual(self.inspect()["defaults"]["log_level"], "info")

    def test_global_title_inheritance_persistence_and_reset(self):
        self.update(level="warning")
        self.update(title="hello-world", level="debug")
        self.assertEqual(self.inspect("hello-world")["effective_settings"]["log_level"], "debug")
        self.assertEqual(self.inspect("hello-world")["settings_sources"]["log_level"], "title")
        self.assertEqual(self.inspect("service-roundtrip")["effective_settings"]["log_level"], "warning")
        self.update(reset=True)
        self.assertEqual(self.inspect("hello-world")["effective_settings"]["log_level"], "debug")
        self.assertEqual(self.inspect("service-roundtrip")["effective_settings"]["log_level"], "info")
        self.update(level="warning")
        self.update(title="hello-world", reset=True)
        self.assertEqual(self.inspect("hello-world")["settings_sources"]["log_level"], "global")
        self.update(title="service-roundtrip", level="debug")
        self.update(reset=True, reset_all=True)
        self.assertEqual(self.inspect()["settings"], {"schema_version": 1, "global": {}, "titles": {}})
        self.assertEqual(self.inspect("service-roundtrip")["settings_sources"]["log_level"], "default")

    def test_malformed_unknown_and_future_schemas_are_not_overwritten(self):
        self.home.mkdir()
        valid = dict(schema_version=1, **{"global": {}, "titles": {}})
        invalid = [None, [], {}, {**valid, "schema_version": 5}, {**valid, "schema_version": True},
                   {**valid, "extra": {}}, {**valid, "global": {"fullscreen": True}},
                   {**valid, "global": {"log_level": True}}, {**valid, "global": {"log_level": "off"}},
                   {**valid, "titles": {"unsupported": {"log_level": "info"}}},
                   {**valid, "titles": {"hello-world": []}}]
        strings = [json.dumps(value) for value in invalid] + ['{', '{"schema_version":1,"schema_version":1}', 'x' * (settings.MAX_BYTES + 1)]
        path = self.home / settings.FILE_NAME
        for value in strings:
            path.write_text(value)
            before = path.read_bytes()
            with self.subTest(value=value[:80]), self.assertRaises(settings.SettingsError):
                self.inspect()
            with self.assertRaises(settings.SettingsError):
                self.update(reset=True, reset_all=True)
            self.assertEqual(path.read_bytes(), before)

    def test_invalid_scope_value_and_failed_save_preserve_state(self):
        self.update(level="warning")
        path = self.home / settings.FILE_NAME
        before = path.read_bytes()
        for values in (dict(level="invalid"), dict(level=True), dict(title="unknown", level="debug"),
                       dict(title="hello-world", reset_all=True), dict(level="debug", reset=True)):
            with self.assertRaises(settings.SettingsError):
                self.update(**values)
            self.assertEqual(path.read_bytes(), before)
        with patch.object(settings.os, "replace", side_effect=OSError("disk failure")):
            with self.assertRaises(settings.SettingsError) as error:
                self.update(level="debug")
        self.assertEqual(error.exception.code, "settings_write_failed")
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual({p.name for p in self.home.iterdir()}, {settings.FILE_NAME, ".settings.lock"})

    def test_writer_contention_fails_without_lost_update_and_releases(self):
        self.update(level="warning")
        before = (self.home / settings.FILE_NAME).read_bytes()
        with settings.writer(self.home):
            with self.assertRaises(settings.SettingsError) as error:
                self.update(title="hello-world", level="debug")
            self.assertEqual(error.exception.code, "settings_busy")
            self.assertEqual((self.home / settings.FILE_NAME).read_bytes(), before)
        self.update(title="hello-world", level="debug")
        self.assertEqual(self.inspect("service-roundtrip")["effective_settings"]["log_level"], "warning")
        self.assertEqual(self.inspect("hello-world")["effective_settings"]["log_level"], "debug")

    def test_launch_snapshots_settings_and_rejects_invalid_preferences_before_execution(self):
        self.update(level="warning")
        self.update(title="hello-world", level="debug")
        def attempt(**kwargs):
            self.assertEqual(kwargs["log_level"], "debug")
            self.update(title="hello-world", level="warning")
            return 0, dict(engine_launch_attempted=True, guest_entry_observed=True,
                           guest_execution_tested=True, transport=dict(tree_cleanup=True))
        with patch.object(launcher, "read_config", return_value={}), patch.object(launcher, "check_inputs", return_value={}), patch.object(launcher, "supported_host", return_value=True):
            with patch.object(launcher.research, "run_attempt", side_effect=attempt):
                code, result = launcher.launch(self.home, "hello-world")
            self.assertEqual(code, 0)
            self.assertEqual(result["effective_settings"], {"log_level": "debug"})
            self.assertEqual(self.inspect("hello-world")["effective_settings"], {"log_level": "warning"})
            (self.home / settings.FILE_NAME).write_text('{"schema_version":2}')
            with patch.object(launcher.research, "run_attempt") as execute:
                code, result = launcher.launch(self.home, "hello-world")
                execute.assert_not_called()
            self.assertEqual((code, result["error"]["code"]), (3, "invalid_settings"))
            self.assertFalse(result["engine_launch_attempted"])
            self.assertIsNone(result["session_id"])

    def test_external_writer_lock_releases_when_process_exits(self):
        self.update(level="warning")
        marker = self.home / "writer-ready"
        code = ("import sys,time\nfrom pathlib import Path\nsys.path.insert(0,sys.argv[1])\n"
                "import runtime_settings as settings\nwith settings.writer(Path(sys.argv[2])):\n"
                " Path(sys.argv[3]).write_text('ready')\n time.sleep(20)\n")
        child = subprocess.Popen([sys.executable, "-c", code, str(ROOT / "tools"), str(self.home), str(marker)],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            deadline = time.monotonic() + 3
            while not marker.exists() and time.monotonic() < deadline:
                self.assertIsNone(child.poll(), "Lock fixture exited early")
                time.sleep(0.02)
            self.assertTrue(marker.exists())
            with self.assertRaises(settings.SettingsError) as error:
                self.update(title="hello-world", level="debug")
            self.assertEqual(error.exception.code, "settings_busy")
        finally:
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=5)
        self.update(title="hello-world", level="debug")
        self.assertEqual(self.inspect("service-roundtrip")["effective_settings"]["log_level"], "warning")

    def test_real_cli_persistence_reset_json_and_usage(self):
        def run(*arguments):
            return subprocess.run([sys.executable, str(ROOT / "tools/ps4_launch.py"), "--state-dir", str(self.home),
                "settings", *arguments], capture_output=True, text=True, timeout=10)
        self.assertEqual(json.loads(run("show", "--json").stdout)["effective_settings"], {"log_level": "info", "volume_percent": 100, "cross_key": "n"})
        self.assertEqual(run("set", "log_level", "warning", "--json").returncode, 0)
        result = run("show", "--title", "hello-world", "--json")
        self.assertFalse(result.stderr)
        self.assertEqual(json.loads(result.stdout)["settings_sources"]["log_level"], "global")
        self.assertEqual(run("set", "log_level", "debug", "--title", "hello-world").returncode, 0)
        self.assertIn("debug (title", run("show", "--title", "hello-world").stdout)
        self.assertEqual(run("reset", "--all", "--json").returncode, 0)
        self.assertEqual(json.loads(run("show", "--json").stdout)["settings_sources"]["log_level"], "default")
        self.assertEqual(run("set", "fullscreen", "true").returncode, 2)
        self.assertEqual(run("set", "log_level", "off").returncode, 2)
        self.assertEqual(run("reset", "--all", "--title", "hello-world").returncode, 2)
        (self.home / settings.FILE_NAME).write_text("broken JSON")
        self.assertEqual(run("show", "--json").returncode, 3)
        self.assertEqual(json.loads(run("show", "--json").stdout)["error"]["code"], "invalid_settings")

    def test_volume_upgrade_is_explicit_and_preserves_diagnostics_and_legacy_scopes(self):
        self.update(level="warning")
        self.update(title="hello-world",level="debug")
        path = self.home/settings.FILE_NAME
        old = path.read_bytes()
        self.assertEqual(self.inspect(launcher.AV_PROFILE)["effective_settings"]["volume_percent"],100)
        self.assertEqual(path.read_bytes(),old)  # Reads never migrate published files.
        self.update(changes={"volume_percent":50})
        self.assertEqual(self.inspect()["settings"]["schema_version"],2)
        self.assertEqual(self.inspect(launcher.AV_PROFILE)["effective_settings"],{"log_level":"warning","volume_percent":50})
        self.assertEqual(self.inspect("hello-world")["effective_settings"],{"log_level":"debug"})
        self.assertEqual(self.inspect("service-roundtrip")["effective_settings"],{"log_level":"warning"})
        self.update(level="debug")
        self.assertEqual(self.inspect()["effective_settings"]["volume_percent"],50)

    def test_independent_keys_title_override_inheritance_and_reset_without_downgrade(self):
        self.update(changes={"log_level":"warning","volume_percent":50})
        self.update(title=launcher.AV_PROFILE,changes={"log_level":"debug","volume_percent":0})
        self.update(title=launcher.AV_PROFILE,changes={"log_level":None})
        result = self.inspect(launcher.AV_PROFILE)
        self.assertEqual(result["effective_settings"],{"log_level":"warning","volume_percent":0})
        self.assertEqual(result["settings_sources"],{"log_level":"global","volume_percent":"title"})
        self.update(title=launcher.AV_PROFILE,reset=True,reset_key="volume_percent")
        self.assertEqual(self.inspect(launcher.AV_PROFILE)["effective_settings"]["volume_percent"],50)
        self.update(reset_all=True)
        self.assertEqual(self.inspect()["settings"],{"schema_version":2,"global":{},"titles":{}})
        self.assertEqual(self.inspect(launcher.AV_PROFILE)["effective_settings"]["volume_percent"],100)

    def test_volume_types_scopes_schema_and_failed_migration_are_not_published(self):
        self.update(level="warning")
        path = self.home/settings.FILE_NAME
        before = path.read_bytes()
        for value in (True,False,50.0,"50",-1,25,101):
            with self.subTest(value=value),self.assertRaises(settings.SettingsError):
                self.update(changes={"volume_percent":value})
            self.assertEqual(path.read_bytes(),before)
        with self.assertRaises(settings.SettingsError):
            self.update(title="hello-world",changes={"volume_percent":50})
        with patch.object(settings.os,"replace",side_effect=OSError("migration write failed")):
            with self.assertRaises(settings.SettingsError):
                self.update(changes={"volume_percent":50})
        self.assertEqual(path.read_bytes(),before)
        invalid = [dict(schema_version=1,**{"global":{"volume_percent":50},"titles":{}}),
                   dict(schema_version=2,**{"global":{},"titles":{"hello-world":{"volume_percent":50}}}),
                   dict(schema_version=2,**{"global":{"volume_percent":True},"titles":{}})]
        for document in invalid:
            path.write_text(json.dumps(document)); original=path.read_bytes()
            with self.assertRaises(settings.SettingsError):
                self.update(reset_all=True)
            self.assertEqual(path.read_bytes(),original)

    def test_volume_cli_values_capabilities_and_single_key_reset(self):
        def run(*arguments):
            return subprocess.run([sys.executable,str(ROOT/"tools/ps4_launch.py"),"--state-dir",str(self.home),
                "settings",*arguments],capture_output=True,text=True,timeout=10)
        for arguments in (("set","volume_percent","25"),("set","volume_percent","50.0"),
                          ("set","volume_percent","50","--title","hello-world"),
                          ("reset","--key","volume_percent","--title","hello-world"),
                          ("reset","--key","volume_percent","--all")):
            self.assertEqual(run(*arguments).returncode,2)
        self.assertFalse(self.home.exists())
        self.assertEqual(run("set","log_level","warning").returncode,0)
        self.assertEqual(run("set","volume_percent","50").returncode,0)
        self.assertEqual(run("set","volume_percent","0","--title",launcher.AV_PROFILE).returncode,0)
        self.assertEqual(run("reset","--key","volume_percent","--title",launcher.AV_PROFILE).returncode,0)
        self.assertEqual(self.inspect(launcher.AV_PROFILE)["effective_settings"],{"log_level":"warning","volume_percent":50})

    def test_av_volume_is_snapshotted_and_corrupt_volume_rejects_before_session(self):
        self.update(changes={"volume_percent":50})
        fields = ("graphics_verified","input_verified","windows_render_verified","window_close_verified","combined_verified","volume_verified")
        def attempt(**kwargs):
            self.assertEqual(kwargs["volume_percent"],50)
            self.update(changes={"volume_percent":0})
            return 0,dict(engine_launch_attempted=True,guest_entry_observed=True,guest_execution_tested=True,
                          transport=dict(tree_cleanup=True),**dict.fromkeys(fields,True))
        with patch.object(launcher,"read_config",return_value={}),patch.object(launcher,"check_inputs",return_value={}),patch.object(launcher,"supported_host",return_value=True):
            with patch.object(launcher.video,"run_attempt",side_effect=attempt):
                code,report=launcher.launch(self.home,launcher.AV_PROFILE)
            self.assertEqual(code,0)
            self.assertEqual(report["effective_settings"]["volume_percent"],50)
            self.assertFalse(report["audio_muted"])
            self.assertEqual(self.inspect(launcher.AV_PROFILE)["effective_settings"]["volume_percent"],0)
            document=self.inspect()["settings"]; document["global"]["volume_percent"]=True
            (self.home/settings.FILE_NAME).write_text(json.dumps(document))
            before=set((self.home/"sessions").iterdir())
            with patch.object(launcher.video,"run_attempt") as execute:
                code,report=launcher.launch(self.home,launcher.AV_PROFILE)
            execute.assert_not_called()
            self.assertEqual((code,report["error"]["code"]),(3,"invalid_settings"))
            self.assertEqual(set((self.home/"sessions").iterdir()),before)


    def test_live_scope_upgrade_is_explicit_and_never_downgrades_existing_preferences(self):
        self.update(title="hello-world",level="warning")
        path = self.home / settings.FILE_NAME
        old = path.read_bytes()
        self.assertEqual(self.inspect(launcher.LIVE_PROFILE)["effective_settings"],{"log_level":"info","volume_percent":100,"cross_key":"n"})
        self.assertEqual(path.read_bytes(),old)
        self.update(changes={"volume_percent":50})
        self.update(title=launcher.LIVE_PROFILE,changes={"log_level":"debug","volume_percent":0})
        document = self.inspect()["settings"]
        self.assertEqual(document["schema_version"],3)
        self.assertEqual(document["titles"]["hello-world"],{"log_level":"warning"})
        with self.assertRaises(settings.SettingsError):
            settings.load(self.home, (*launcher.LEGACY_PROFILES,launcher.AV_PROFILE))
        self.update(title=launcher.AV_PROFILE,changes={"volume_percent":100})
        self.assertEqual(self.inspect()["settings"]["schema_version"],3)
        self.update(title=launcher.LIVE_PROFILE,reset=True,reset_key="volume_percent")
        self.assertEqual(self.inspect(launcher.LIVE_PROFILE)["effective_settings"],{"log_level":"debug","volume_percent":50,"cross_key":"n"})
        self.update(title=launcher.LIVE_PROFILE,reset=True)
        self.assertNotIn(launcher.LIVE_PROFILE,self.inspect()["settings"]["titles"])
        self.assertEqual(self.inspect()["settings"]["schema_version"],3)
        # Older schema meanings do not silently widen to admit the new title.
        document["schema_version"]=2
        path.write_text(json.dumps(document))
        before=path.read_bytes()
        with self.assertRaises(settings.SettingsError):
            self.update(reset_all=True)
        self.assertEqual(path.read_bytes(),before)


if __name__ == "__main__":
    unittest.main()
