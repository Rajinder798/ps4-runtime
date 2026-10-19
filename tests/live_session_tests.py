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


class LiveSessionTests(unittest.TestCase):
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
