# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later

"""Portable launch guards and evidence limits, never guest execution evidence."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import run_homebrew_startup as startup
from live_av_tests import events
from live_status import open_status, read_status, publish_status
import live_input
from live_launch_guest_tests import verify_transport_timing


class LiveSessionTests(unittest.TestCase):
    def test_transport_timing_rejects_stale_pre_oracle_clock_and_short_key_intervals(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/"trace.jsonl"
            events=[dict(event="image_verified",sequence=i,monotonic=i*3+2) for i in range(5)]
            events += [dict(event="mapped_letter",monotonic=i*3+3.1) for i in range(4)]
            events += [dict(event="displaced_letter",down=True,monotonic=0),
                       dict(event="displaced_letter",down=False,monotonic=0.6),
                       dict(event="displaced_neutral_verified",monotonic=1.2)]
            def save():path.write_text("".join(json.dumps(e)+"\n" for e in events),encoding="utf-8")
            save();self.assertGreater(verify_transport_timing(path,True)["displaced_held_seconds"],0.5)
            events[-2]["monotonic"]=0.328;save()
            with self.assertRaises(RuntimeError):verify_transport_timing(path,True)
            events[-2]["monotonic"]=0.6
            events[5]["monotonic"]=2.3;save()
            with self.assertRaises(RuntimeError):verify_transport_timing(path,True)

    def test_live_cross_adapter_preserves_other_pinned_bindings_and_rejects_tampering(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            self.assertEqual(live_input.stage_input(work,"n"),dict(cross_key="n",source="engine_default"))
            self.assertFalse((work/"user").exists())
            (work/"user").mkdir()
            record = live_input.stage_input(work,"g")
            self.assertEqual(record["cross_key"],"g")
            staged = (work/"user/input_config/default.ini").read_bytes()
            original = live_input.TEMPLATE.read_bytes().replace(b"\r\n",b"\n")
            self.assertEqual(staged.replace(b"\ncross = g\n",b"\ncross = n\n"),original)
            for binding in (b"cross = kp2",b"cross = cross",b"circle = b",b"touchpad_center = space"):
                self.assertIn(binding,staged)
            with self.assertRaises(FileExistsError): live_input.stage_input(work,"g")
            changed = work/"changed.ini"; changed.write_bytes(original+b"cross = g\n")
            with patch.object(live_input,"TEMPLATE",changed), self.assertRaises(ValueError):
                live_input.stage_input(work,"g")
            with self.assertRaises(ValueError): live_input.stage_input(work,"space")

    def test_muted_lifetime_driver_rejects_capture_cases_before_output_or_device_access(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "unused"
            common = [sys.executable, str(ROOT / "tests/live_session_guest_tests.py")]
            for name in ("engine", "engine-report", "fixture", "supervisor", "capture-helper", "muted-endpoint-observer"):
                common.extend(["--" + name, str(output / "missing")])
            for extra in ([], ["--case", "long-session"]):
                child = subprocess.run([*common, "--output", str(output), *extra], capture_output=True, timeout=5)
                self.assertEqual(child.returncode, 2)
                self.assertIn(b"non-capture", child.stderr)
                self.assertFalse(output.exists())

    def test_status_reader_allows_atomic_replacement_and_keeps_snapshot(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "status.json"
            publish_status(path, {"sequence": 0})
            with open_status(path) as stream:
                publish_status(path, {"sequence": 1})
                self.assertEqual(json.load(stream), {"sequence": 0})
            self.assertEqual(read_status(path), {"sequence": 1})
            self.assertFalse(path.with_suffix(".tmp").exists())

    @unittest.skipUnless(sys.platform == "win32", "Windows sharing violation reproduction")
    def test_old_replacement_denial_and_incompatible_reader_failure_are_explicit(self):
        with tempfile.TemporaryDirectory() as temporary:
            path, pending = [Path(temporary) / name for name in ("status.json", "pending.json")]
            path.write_bytes(b"original")
            pending.write_bytes(b"next")
            with path.open("rb"):
                with self.assertRaises(PermissionError):
                    pending.replace(path)
                with self.assertRaises(PermissionError):
                    publish_status(path, {"sequence": 1})
            self.assertEqual(path.read_bytes(), b"original")
            self.assertEqual(pending.read_bytes(), b"next")
            with open_status(path):
                with self.assertRaises(PermissionError):
                    pending.replace(path)

    def test_cli_rejects_bad_startup_budget_and_existing_output_without_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "unused"
            common = [sys.executable, str(ROOT / "tools/run_live_session.py")]
            for name in ("engine", "engine-report", "fixture", "supervisor"):
                common.extend(["--" + name, str(output)])
            for budget in ("2", "31", "nan", "inf"):
                process = subprocess.run([*common, "--output", str(output), "--startup-timeout", budget],
                                         capture_output=True, timeout=5)
                self.assertEqual(process.returncode, 2)
                self.assertFalse(output.exists())
            output.mkdir()
            marker = output / "existing.txt"
            marker.write_bytes(b"preserve")
            process = subprocess.run([*common, "--output", str(output)], capture_output=True, timeout=5)
            self.assertEqual(process.returncode, 2)
            self.assertEqual(list(output.iterdir()), [marker])
            self.assertEqual(marker.read_bytes(), b"preserve")

    def test_missing_inputs_cannot_claim_a_closed_session(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "attempt"
            command = [sys.executable, str(ROOT / "tools/run_live_session.py")]
            for name in ("engine", "engine-report", "fixture", "supervisor"):
                command.extend(["--" + name, str(output / "missing")])
            process = subprocess.run([*command, "--output", str(output)], capture_output=True, timeout=5)
            self.assertEqual(process.returncode, 1)
            result = json.loads((output / "session-result.json").read_text())
            self.assertEqual(result["status"], "failed")
            for field in ("engine_launch_attempted", "guest_entry_observed", "guest_execution_tested",
                          "guest_completed", "independent_av_qualification_performed", "normal_exit_verified"):
                self.assertFalse(result[field])

    def test_live_postmortem_preserves_only_valid_entry_and_records_later_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            (output / "session").mkdir()
            trace = output / "session/startup-audit.jsonl"
            for entry_valid in (True, False):
                case = events() if entry_valid else [dict(schema_version=1, elapsed_us=0, event="guest_entry")]
                case.append(dict(schema_version=1, elapsed_us=99, event="unresolved", symbol="late"))
                trace.write_text("".join(json.dumps(e) + "\n" for e in case))
                result = dict(profile="live-av", guest_completed=False, independent_av_qualification_performed=False)
                startup.collect_failure_evidence(output, result)
                self.assertEqual(result["guest_entry_observed"], entry_valid)
                self.assertEqual(result["guest_execution_tested"], entry_valid)
                self.assertIn("validation_error", result["audit"])
                self.assertFalse(result["guest_completed"])
                self.assertFalse(result["independent_av_qualification_performed"])


if __name__ == "__main__":
    unittest.main()
