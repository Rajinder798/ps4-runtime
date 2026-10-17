# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Audit semantics and real Windows process-tree tests, not PS4 execution tests."""
import ctypes
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import run_homebrew_startup as runner

DRIVER, SUPERVISOR = map(Path, sys.argv[1:3])
sys.argv = sys.argv[:1]


def event(kind, elapsed=0, **fields):
    return dict(schema_version=1, event=kind, elapsed_us=elapsed, **fields)


def valid_events():
    return [event("configured", strict_imports=True),
            event("imports_checked", phase="entry", unresolved_count=0),
            event("guest_entry"),
            event("guest_output", 10, text=runner.MARKERS[0]),
            event("guest_output", 2_000_010, text=runner.MARKERS[1])]


class AuditTests(unittest.TestCase):
    def test_header_roundtrip_and_missing_import_prevents_entry(self):
        with tempfile.TemporaryDirectory(dir=DRIVER.resolve().parent) as directory:
            for mode in ("missing", "entry"):
                trace = Path(directory) / (mode + ".jsonl")
                result = subprocess.run([str(DRIVER), str(trace), mode], capture_output=True, timeout=5)
                self.assertEqual(result.returncode, 0, result.stderr)
                events = runner.read_events(trace, final=True)
                if mode == "missing":
                    self.assertFalse(any(e["event"] == "guest_entry" for e in events))
                    unresolved = next(e for e in events if e["event"] == "unresolved")
                    self.assertEqual(unresolved["symbol"], 'nid#lib#mod\n"\\')
                    with self.assertRaisesRegex(ValueError, "Unresolved"):
                        runner.evaluate(events)
                else:
                    self.assertTrue(runner.evaluate(events)["guest_entry_observed"])
                    self.assertFalse(runner.evaluate(events)["markers_observed"])
                    self.assertEqual(events[-1]["text"], 'driver output \n " \\ \t')

    def test_order_timing_missing_and_forged_events(self):
        self.assertTrue(runner.evaluate(valid_events())["markers_observed"])
        variants = []
        missing = valid_events(); missing.insert(3, event("unresolved", symbol="missing")); variants.append(missing)
        order = valid_events(); order[-1]["text"], order[-2]["text"] = order[-2]["text"], order[-1]["text"]; variants.append(order)
        too_fast = valid_events(); too_fast[-1]["elapsed_us"] = 100; variants.append(too_fast)
        unchecked = valid_events(); del unchecked[1]; variants.append(unchecked)
        pre_entry = valid_events(); pre_entry[2], pre_entry[3] = pre_entry[3], pre_entry[2]; variants.append(pre_entry)
        wrong_clock = valid_events(); wrong_clock[-1]["elapsed_us"] = -1; variants.append(wrong_clock)
        duplicate = valid_events(); duplicate.append(event("guest_entry", 3_000_000)); variants.append(duplicate)
        forged = valid_events(); forged[0]["strict_imports"] = False; variants.append(forged)
        for events in variants:
            with self.subTest(events=events), self.assertRaises(ValueError):
                runner.evaluate(events)
        self.assertFalse(runner.evaluate([])["markers_observed"])

    def test_partial_trace_is_not_a_pass(self):
        with tempfile.TemporaryDirectory(dir=DRIVER.resolve().parent) as directory:
            trace = Path(directory) / "partial.jsonl"
            trace.write_bytes(b'{"schema_version":1,"event":"configured","elapsed_us":0,"strict_imports":true}\n{"event":')
            self.assertFalse(runner.evaluate(runner.read_events(trace))["markers_observed"])
            with self.assertRaisesRegex(ValueError, "Truncated"):
                runner.read_events(trace, final=True)

    def test_unpatched_engine_evidence_is_rejected(self):
        with tempfile.TemporaryDirectory(dir=DRIVER.resolve().parent) as directory:
            work = Path(directory)
            binary, report, fixture = work / "engine", work / "report.json", work / "sample"
            binary.write_bytes(b"test transport, not an engine")
            fixture.write_bytes(b"not the pinned homebrew")
            report.write_text(json.dumps(dict(status="built_and_help_smoke_passed", executable_sha256=runner.digest(binary))))
            with self.assertRaisesRegex(ValueError, "strict build evidence"):
                runner.verify_inputs(binary, report, fixture)

    def test_missing_prerequisite_records_failure_without_guest_execution(self):
        with tempfile.TemporaryDirectory(dir=DRIVER.resolve().parent) as directory:
            work = Path(directory)
            output = work / "attempt"
            result = subprocess.run([sys.executable, ROOT / "tools/run_homebrew_startup.py",
                                     "--engine", work / "missing.exe", "--engine-report", work / "missing.json",
                                     "--fixture", work / "missing.oelf", "--supervisor", SUPERVISOR,
                                     "--output", output], capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 1)
            report = json.loads((output / "startup-result.json").read_text())
            self.assertEqual(report["status"], "failed")
            self.assertFalse(report["g2_passed"])
            self.assertFalse(report["guest_execution_tested"])
            self.assertFalse(report["engine_launch_attempted"])


@unittest.skipUnless(sys.platform == "win32", "Windows Job Object transport")
class WindowsProcessTests(unittest.TestCase):
    def launch(self, mode, poll=lambda work: False, timeout=1.5, extra=()):
        directory = tempfile.TemporaryDirectory(prefix="startup transport \u03bb ", dir=DRIVER.resolve().parent)
        self.addCleanup(directory.cleanup)
        work = Path(directory.name).resolve()
        command = [Path(sys.executable).resolve(), ROOT / "tests/startup_child.py", mode, work, *extra]
        result = runner.supervise(SUPERVISOR, command, work, timeout, lambda: poll(work))
        self.assertTrue(result["tree_cleanup"])
        return work, result

    def assert_dead(self, pid):
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        kernel.WaitForSingleObject.restype = ctypes.c_uint32
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.OpenProcess(0x100000, False, pid)
        if handle:
            try:
                self.assertEqual(kernel.WaitForSingleObject(handle, 0), 0, "descendant is still alive")
            finally:
                kernel.CloseHandle(handle)
        else:
            self.assertEqual(ctypes.get_last_error(), 87)

    def test_timeout_kills_descendant(self):
        work, result = self.launch("tree")
        self.assertEqual(result["reason"], "timeout")
        self.assertTrue((work / "heartbeat.txt").exists())
        self.assert_dead(int((work / "child-pid.txt").read_text()))
        size = (work / "heartbeat.txt").stat().st_size
        time.sleep(0.1)
        self.assertEqual((work / "heartbeat.txt").stat().st_size, size)

    def test_root_exit_also_kills_descendant(self):
        work, result = self.launch("orphan", timeout=3)
        self.assertEqual(result["reason"], "exited")
        self.assertEqual(result["exit_code"], 0)
        self.assert_dead(int((work / "child-pid.txt").read_text()))

    def test_requested_stop_unicode_and_argument_quoting(self):
        arguments = ('', 'space argument', 'quote"argument', 'trailing\\', '\\"', '\u03bb')
        work, result = self.launch("arguments", lambda w: (w / "arguments.json").exists(), timeout=3, extra=arguments)
        self.assertEqual(result["reason"], "requested")
        self.assertEqual(json.loads((work / "arguments.json").read_text()), list(arguments))
        self.assertIn("ordinary stdout", (work / "stdout.txt").read_text())
        self.assertIn("ordinary stderr", (work / "stderr.txt").read_text())

    def test_crash_is_not_success(self):
        _, result = self.launch("crash")
        self.assertEqual(result["reason"], "exited")
        self.assertEqual(result["exit_code"], 17)

    def test_monitor_failure_still_cleans_tree(self):
        with tempfile.TemporaryDirectory(dir=DRIVER.resolve().parent) as directory:
            work = Path(directory).resolve()
            def reject():
                if (work / "heartbeat.txt").exists():
                    raise ValueError("negative monitor case")
                return False
            command = [Path(sys.executable).resolve(), ROOT / "tests/startup_child.py", "tree", work]
            with self.assertRaisesRegex(ValueError, "negative monitor"):
                runner.supervise(SUPERVISOR, command, work, 3, reject)
            self.assertTrue(json.loads((work / "supervisor.json").read_text())["tree_cleanup"])
            self.assert_dead(int((work / "child-pid.txt").read_text()))


if __name__ == "__main__":
    unittest.main()
