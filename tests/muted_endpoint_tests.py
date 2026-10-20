# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
"""Host evidence rejection and native argument guards; no guest or audio-device claim."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from muted_endpoint import validate_report

HELPER = sys.argv.pop() if len(sys.argv) > 1 else "unsupported"


class EndpointTests(unittest.TestCase):
    def test_incomplete_changed_or_unmuted_observation_cannot_pass(self):
        good = [dict(elapsed_ms=0, muted=True, volume=0.75, same_endpoint=True),
                dict(elapsed_ms=25, muted=True, volume=0.75, same_endpoint=True),
                dict(status="passed", samples=2)]
        cases = [good[:-1], good[1:], [*good[:-1], dict(status="passed", samples=3)]]
        for field, value in (("muted", False), ("volume", 0.5), ("same_endpoint", False), ("elapsed_ms", -1)):
            bad = copy.deepcopy(good)
            bad[1][field] = value
            cases.append(bad)
        with tempfile.TemporaryDirectory() as temporary:
            report = Path(temporary) / "endpoint.jsonl"
            report.write_text("".join(json.dumps(x)+"\n" for x in good), encoding="utf-8")
            self.assertEqual(validate_report(report)["max_sample_gap_ms"], 25)
            for case in cases:
                report.write_text("".join(json.dumps(x)+"\n" for x in case), encoding="utf-8")
                with self.assertRaises((RuntimeError, KeyError)):
                    validate_report(report)

    @unittest.skipIf(HELPER == "unsupported", "Windows native argument guards only")
    def test_native_arguments_rejected_before_device_access_or_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            report, stop, ready = [Path(temporary) / name for name in ("report", "stop", "ready")]
            for timeout in ("0", "99", "600001", "nan", "-1", "1e3"):
                child = subprocess.run([HELPER, "--watch", str(report), str(stop), str(ready), timeout],
                                       capture_output=True, timeout=5)
                self.assertEqual(child.returncode, 1)
                self.assertIn(b"timeout", child.stderr.lower())
                self.assertFalse(report.exists())
                self.assertFalse(ready.exists())
            report.write_bytes(b"preserve")
            child = subprocess.run([HELPER, "--watch", str(report), str(stop), str(ready), "100"],
                                   capture_output=True, timeout=5)
            self.assertEqual(child.returncode, 1)
            self.assertEqual(report.read_bytes(), b"preserve")


if __name__ == "__main__":
    unittest.main()
