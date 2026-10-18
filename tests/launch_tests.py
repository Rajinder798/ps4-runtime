# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Launch policy and CLI tests. Test transport evidence is not PS4 execution."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import ps4_launch as launcher


class LaunchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.home = self.root / "state with spaces \u03bb"
        self.paths = {}
        for name in ("engine", "engine_report", "supervisor", "hello-world", "service-roundtrip"):
            path = self.root / name
            path.write_bytes(name.encode())
            self.paths[name] = path
        # Only policy tests replace engine attestation; real guest acceptance is
        # separate and uses the normal exact-input verifier without replacement.
        self.verify = patch.object(launcher.research, "verify_inputs", return_value={})
        self.verify.start()
        self.addCleanup(self.verify.stop)

    def register(self, replace=False):
        return launcher.register(self.home, self.paths["engine"], self.paths["engine_report"],
            self.paths["supervisor"], {k: self.paths[k] for k in launcher.LEGACY_PROFILES}, replace)

    def test_registration_persists_exact_paths_and_no_guest_is_started(self):
        with patch.object(launcher.research, "run_attempt") as execute:
            config = self.register()
            self.assertEqual(launcher.read_config(self.home), config)
            execute.assert_not_called()
        self.assertEqual(set(config["fixtures"]), set(launcher.LEGACY_PROFILES))
        self.assertTrue(all(Path(config[k]["path"]).is_absolute() for k in ("engine", "engine_report", "supervisor")))
        self.assertFalse((self.home / "sessions").exists())
        self.assertEqual([p.name for p in self.home.iterdir()], [launcher.CONFIG_NAME])

    def test_failed_registration_and_replace_preserve_previous_state(self):
        original = self.register()
        before = (self.home / launcher.CONFIG_NAME).read_bytes()
        self.paths["engine"].write_bytes(b"updated engine")
        with self.assertRaisesRegex(launcher.LaunchError, "already exists"):
            self.register()
        self.assertEqual((self.home / launcher.CONFIG_NAME).read_bytes(), before)
        with patch.object(launcher.research, "verify_inputs", side_effect=ValueError("wrong engine")):
            with self.assertRaises(launcher.LaunchError):
                self.register(replace=True)
        self.assertEqual((self.home / launcher.CONFIG_NAME).read_bytes(), before)
        with patch.object(launcher.os, "replace", side_effect=OSError("disk failure")):
            with self.assertRaises(launcher.LaunchError):
                self.register(replace=True)
        self.assertEqual((self.home / launcher.CONFIG_NAME).read_bytes(), before)
        updated = self.register(replace=True)
        self.assertNotEqual(original["engine"]["sha256"], updated["engine"]["sha256"])
        self.assertEqual(launcher.read_config(self.home), updated)

    def test_invalid_config_shapes_versions_paths_and_duplicates_are_rejected(self):
        original = self.register()
        cases = [None, [], {**original, "schema_version": 2}, {**original, "schema_version": True},
                 {**original, "extra": "ignored?"}, {**original, "fixtures": {}},
                 {**original, "fixtures": {"arbitrary": original["fixtures"]["hello-world"]}},
                 {**original, "engine": dict(path="relative.exe", sha256="a" * 64)},
                 {**original, "supervisor": dict(path=str(self.root), sha256="wrong")}]
        for value in cases:
            (self.home / launcher.CONFIG_NAME).write_text(json.dumps(value))
            with self.subTest(value=value), self.assertRaises(launcher.LaunchError):
                launcher.read_config(self.home)
        for data in ('{"schema_version":1,"schema_version":1}', '{', 'x' * (launcher.MAX_CONFIG_BYTES + 1)):
            (self.home / launcher.CONFIG_NAME).write_text(data)
            with self.assertRaises(launcher.LaunchError):
                launcher.read_config(self.home)

    def test_unknown_missing_and_changed_inputs_never_start_a_process(self):
        self.assertEqual(launcher.launch(self.home, "hello-world")[1]["error"]["code"], "not_registered")
        self.register()
        with patch.object(launcher.research, "run_attempt") as execute:
            code, report = launcher.launch(self.home, "../../arbitrary.elf")
            self.assertEqual((code, report["error"]["code"]), (3, "unsupported_title"))
            for name in self.paths:
                original = self.paths[name].read_bytes()
                self.paths[name].write_bytes(b"changed")
                title = name if name in launcher.PROFILES else "hello-world"
                code, report = launcher.launch(self.home, title)
                self.assertEqual((code, report["error"]["code"]), (4, "input_verification_failed"))
                self.assertFalse(report["engine_launch_attempted"])
                self.assertIsNone(report["session_id"])
                self.paths[name].write_bytes(original)
            service_bytes = self.paths["service-roundtrip"].read_bytes()
            self.paths["service-roundtrip"].unlink()
            self.assertEqual(launcher.check_inputs(launcher.read_config(self.home), "hello-world")["fixture"], self.paths["hello-world"])
            self.paths["service-roundtrip"].write_bytes(service_bytes)
            self.paths["supervisor"].unlink()
            self.assertEqual(launcher.launch(self.home, "hello-world")[0], 4)
            execute.assert_not_called()
        self.assertFalse((self.home / "sessions").exists())

    def test_exact_contract_verification_is_repeated_after_registration(self):
        self.register()
        with patch.object(launcher.research, "verify_inputs", side_effect=ValueError("stale patch")):
            self.assertEqual(launcher.launch(self.home, "hello-world")[1]["error"]["code"], "input_verification_failed")

    def test_repeat_launches_keep_unique_evidence_and_do_not_rewrite_config(self):
        self.register()
        before = (self.home / launcher.CONFIG_NAME).read_bytes()
        def attempt(**kwargs):
            self.assertEqual(list(kwargs["output"].iterdir()), [])
            (kwargs["output"] / "startup-result.json").write_text("test evidence only")
            return 0, dict(engine_launch_attempted=True, guest_entry_observed=True,
                           guest_execution_tested=True, transport=dict(tree_cleanup=True))
        with patch.object(launcher, "supported_host", return_value=True), patch.object(launcher.research, "run_attempt", side_effect=attempt):
            reports = [launcher.launch(self.home, title)[1] for title in ("hello-world", "service-roundtrip", "hello-world")]
        self.assertEqual(len({r["session_id"] for r in reports}), 3)
        for report in reports:
            self.assertEqual(report["status"], "completed")
            session = Path(report["logs_directory"])
            self.assertEqual(json.loads((session / "launch-result.json").read_text()), report)
            self.assertEqual((session / "startup-result.json").read_text(), "test evidence only")
        self.assertEqual((self.home / launcher.CONFIG_NAME).read_bytes(), before)

    def test_prerequisite_guest_and_storage_failures_have_distinct_codes(self):
        self.register()
        for attempted, code, expected in ((False, 4, "prerequisite_failed"), (True, 5, "guest_failed")):
            evidence = dict(engine_launch_attempted=attempted, guest_entry_observed=False,
                            guest_execution_tested=False, transport=dict(tree_cleanup=True))
            with patch.object(launcher, "supported_host", return_value=True), patch.object(launcher.research, "run_attempt", return_value=(1, evidence)):
                exit_code, report = launcher.launch(self.home, "hello-world")
            self.assertEqual((exit_code, report["error"]["code"]), (code, expected))
            self.assertTrue(report["tree_cleanup"])
        with patch.object(launcher, "supported_host", return_value=False):
            self.assertEqual(launcher.launch(self.home, "hello-world")[1]["error"]["code"], "unsupported_host")
        with patch.object(launcher, "supported_host", return_value=True), patch.object(Path, "mkdir", side_effect=OSError("disk failure")):
            self.assertEqual(launcher.launch(self.home, "hello-world")[0], 6)

    def test_session_collision_never_overwrites_existing_evidence(self):
        self.register()
        identifier = uuid.UUID("12345678-1234-5678-1234-567812345678")
        existing = self.home / "sessions" / identifier.hex
        existing.mkdir(parents=True)
        sentinel = existing / "launch-result.json"
        sentinel.write_text("previous evidence")
        with patch.object(launcher, "supported_host", return_value=True), patch.object(launcher.uuid, "uuid4", return_value=identifier):
            code, report = launcher.launch(self.home, "hello-world")
        self.assertEqual(code, 6)
        self.assertIsNone(report["session_id"])
        self.assertEqual(sentinel.read_text(), "previous evidence")

    def test_real_cli_json_text_and_usage_contract(self):
        def run(*arguments):
            return subprocess.run([sys.executable, str(ROOT / "tools/ps4_launch.py"), "--state-dir", str(self.home), *arguments],
                                  capture_output=True, text=True, timeout=10)
        result = run("launch", "hello-world", "--json")
        self.assertEqual(result.returncode, 3)
        self.assertFalse(result.stderr)
        self.assertEqual(json.loads(result.stdout)["error"]["code"], "not_registered")
        self.assertIn("error[not_registered]", run("launch", "hello-world").stderr)
        self.assertEqual(run("--help").returncode, 0)
        self.assertEqual(run("launch").returncode, 2)
        self.assertEqual(run("register", "--engine", "e", "--engine-report", "r", "--supervisor", "s").returncode, 2)
        self.register()
        result = run("launch", "--json", "arbitrary")
        self.assertEqual(json.loads(result.stdout)["error"]["code"], "unsupported_title")


class AVLaunchTests(unittest.TestCase):
    setUp = LaunchTests.setUp

    def register_av(self, replace=False):
        fixture, helper = self.root / "av.oelf", self.root / "capture.exe"
        fixture.write_bytes(b"AV fixture test input")
        helper.write_bytes(b"capture helper test input")
        return launcher.register(self.home, self.paths["engine"], self.paths["engine_report"],
            self.paths["supervisor"], {**{k:self.paths[k] for k in launcher.LEGACY_PROFILES}, launcher.AV_PROFILE:fixture},
            replace, capture_helper=helper)

    def test_schema_two_is_explicit_and_legacy_registration_is_preserved_on_failed_upgrade(self):
        legacy = LaunchTests.register(self)
        self.assertEqual(legacy["schema_version"], 1)
        before = (self.home / launcher.CONFIG_NAME).read_bytes()
        with self.assertRaises(launcher.LaunchError):
            self.register_av()
        self.assertEqual((self.home / launcher.CONFIG_NAME).read_bytes(), before)
        updated = self.register_av(replace=True)
        self.assertEqual(updated["schema_version"], 2)
        self.assertEqual(set(updated["fixtures"]), set(launcher.PROFILES))
        self.assertEqual(launcher.read_config(self.home), updated)
        cases = [{**updated, "schema_version": 3}, {**updated, "schema_version": 1},
                 {k:v for k,v in updated.items() if k != "capture_helper"},
                 {**updated,"capture_helper":dict(path="relative",sha256="a"*64)},
                 {**updated,"fixtures":legacy["fixtures"]}]
        for config in cases:
            with self.assertRaises(ValueError):
                launcher.validate_config(config)
        with self.assertRaises(ValueError):
            launcher.validate_config({**legacy,"fixtures":updated["fixtures"]})

    def test_capture_input_is_rechecked_only_for_selected_av_title(self):
        config = self.register_av()
        helper = Path(config["capture_helper"]["path"])
        paths = launcher.check_inputs(config, launcher.AV_PROFILE)
        self.assertEqual(paths["capture_helper"], helper)
        helper.write_bytes(b"changed helper")
        with patch.object(launcher.video,"run_attempt") as execute:
            code, report = launcher.launch(self.home,launcher.AV_PROFILE)
            self.assertEqual((code,report["error"]["code"]),(4,"input_verification_failed"))
            execute.assert_not_called()
        self.assertEqual(launcher.check_inputs(config,"hello-world")["fixture"],self.paths["hello-world"])
        self.assertFalse((self.home / "sessions").exists())

    def test_av_dispatch_requires_every_surface_and_snapshots_effective_log_level(self):
        self.register_av()
        launcher.runtime_settings.update(self.home,launcher.PROFILES,title=launcher.AV_PROFILE,level="warning")
        fields = ("graphics_verified","input_verified","windows_render_verified","window_close_verified","combined_verified","volume_verified")
        evidence = dict(engine_launch_attempted=True,guest_entry_observed=True,guest_execution_tested=True,
                        transport=dict(tree_cleanup=True),**dict.fromkeys(fields,True))
        with patch.object(launcher,"supported_host",return_value=True), patch.object(launcher.research,"run_attempt") as legacy:
            with patch.object(launcher.video,"run_attempt",return_value=(0,evidence)) as run:
                code, report = launcher.launch(self.home,launcher.AV_PROFILE)
            self.assertEqual(code,0)
            self.assertEqual(report["completion"],"fixture_observed_and_window_closed")
            self.assertEqual(run.call_args.kwargs["log_level"],"warning")
            self.assertEqual(run.call_args.kwargs["audio_backend"],"wasapi")
            self.assertEqual(run.call_args.kwargs["shutdown"],"window-close")
            self.assertEqual(run.call_args.kwargs["volume_percent"],100)
            legacy.assert_not_called()
            for field in fields:
                with patch.object(launcher.video,"run_attempt",return_value=(0,dict(evidence,**{field:False}))):
                    code, report = launcher.launch(self.home,launcher.AV_PROFILE)
                    self.assertEqual((code,report["error"]["code"]),(5,"guest_failed"))

    def test_registration_cli_requires_av_and_capture_helper_pair_before_state_creation(self):
        command = [sys.executable,str(ROOT / "tools/ps4_launch.py"),"--state-dir",str(self.home),"register",
            "--engine","absent","--engine-report","absent","--supervisor","absent"]
        for options in (("--interactive-av","absent"),("--hello-world","absent","--capture-helper","absent")):
            result = subprocess.run([*command,*options],capture_output=True,timeout=10)
            self.assertEqual(result.returncode,2)
            self.assertFalse(self.home.exists())


if __name__ == "__main__":
    unittest.main()
