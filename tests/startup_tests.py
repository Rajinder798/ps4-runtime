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
from unittest.mock import patch

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
    def test_service_profile_requires_its_own_ordered_guest_evidence(self):
        events = valid_events()
        events[-2]["text"], events[-1]["text"] = runner.SERVICE_MARKERS
        events[-1]["elapsed_us"] = 20
        self.assertTrue(runner.evaluate(events, "service-roundtrip")["markers_observed"])
        self.assertFalse(runner.evaluate(valid_events(), "service-roundtrip")["markers_observed"])
        self.assertFalse(runner.evaluate(events)["markers_observed"])
        for kind in ("missing-entry", "reversed", "failure", "duplicate", "unresolved"):
            bad = [dict(e) for e in events]
            if kind == "missing-entry":
                del bad[2]
            elif kind == "reversed":
                bad[-2]["text"], bad[-1]["text"] = bad[-1]["text"], bad[-2]["text"]
            elif kind == "failure":
                bad.insert(4, event("guest_output", 15, text="service-roundtrip: FAIL read"))
            elif kind == "duplicate":
                bad.append(dict(bad[-1]))
            else:
                bad.append(event("unresolved", 21, symbol="missing#B#B"))
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                runner.evaluate(bad, "service-roundtrip")
        with self.assertRaisesRegex(ValueError, "Unknown fixture"):
            runner.evaluate([], "arbitrary")

    def test_service_output_is_independently_checked(self):
        challenge = bytes(range(256))
        expected = runner.service_expected(challenge)
        self.assertEqual(expected[:4], bytes((165, 165, 169, 169)))
        self.assertEqual(runner.service_expected(bytes(256))[128], 37)
        with self.assertRaises(ValueError):
            runner.service_expected(b"short")
        with tempfile.TemporaryDirectory(dir=DRIVER.resolve().parent) as directory:
            work = Path(directory)
            result = work / "user/data/service-result.bin"
            result.parent.mkdir(parents=True)
            with self.assertRaisesRegex(ValueError, "independent host"):
                runner.verify_service(work, challenge)
            for data in (expected[:-1], expected + b"x", bytes(256), bytes([expected[0] ^ 1]) + expected[1:]):
                result.write_bytes(data)
                with self.assertRaisesRegex(ValueError, "independent host"):
                    runner.verify_service(work, challenge)
            result.write_bytes(expected)
            report = runner.verify_service(work, challenge)
            self.assertEqual(report["bytes_verified"], 256)
            self.assertEqual(report["result_sha256"], runner.digest(result))
            with self.assertRaises(ValueError):
                runner.verify_service(work, bytes(reversed(challenge)))

    def test_service_staging_is_fresh_and_does_not_write_the_result(self):
        with tempfile.TemporaryDirectory(dir=DRIVER.resolve().parent) as directory:
            root = Path(directory)
            fixture = root / "fixture.oelf"
            fixture.write_bytes(b"transport fixture, not guest code")
            challenges = []
            for name in ("first", "second"):
                work = root / name
                runner.prepare_session(work)
                staged, challenge = runner.prepare_service(work, fixture)
                self.assertEqual(staged.read_bytes(), fixture.read_bytes())
                self.assertEqual((staged.parent / "challenge.bin").read_bytes(), challenge)
                self.assertFalse((work / "user/data/service-result.bin").exists())
                challenges.append(challenge)
                with self.assertRaises(FileExistsError):
                    runner.prepare_service(work, fixture)
            self.assertNotEqual(*challenges)

    def test_service_header_is_bound_to_engine_report_and_input(self):
        with tempfile.TemporaryDirectory(dir=DRIVER.resolve().parent) as directory:
            root = Path(directory)
            (root / "config").mkdir()
            revision = "a" * 40
            paths = {}
            for name in ("engine", "fixture", "patch", "audit_header", "services_header", "aac_header"):
                paths[name] = root / name
                paths[name].write_bytes(name.encode())
            contract = {}
            for name in ("patch", "audit_header", "services_header", "aac_header"):
                contract[name + "_path"] = name
                contract[name + "_sha256"] = runner.digest(paths[name])
            contract["expected_patched_tree"] = "b" * 40
            (root / "config/startup-research.json").write_text(json.dumps(contract))
            (root / "config/g2-integration-audit.json").write_text(json.dumps({
                "upstream": {"revision": revision},
                "fixture": {"oelf_sha256": runner.digest(paths["fixture"])}}))
            report = dict(status="strict_engine_built", upstream_revision=revision,
                          patched_tree=contract["expected_patched_tree"], aac_backend="ffmpeg-aac-lc",
                          fdk_linkage_verified_absent=True, aac_tests={"status": "passed"},
                          executable_sha256=runner.digest(paths["engine"]),
                          **{k: v for k, v in contract.items() if k.endswith("_sha256")})
            report_path = root / "build-report.json"
            with patch.object(runner, "ROOT", root):
                for value in (None, "wrong", contract["services_header_sha256"]):
                    candidate = dict(report)
                    if value is None:
                        del candidate["services_header_sha256"]
                    else:
                        candidate["services_header_sha256"] = value
                    report_path.write_text(json.dumps(candidate))
                    if value != contract["services_header_sha256"]:
                        with self.assertRaisesRegex(ValueError, "strict build evidence"):
                            runner.verify_inputs(paths["engine"], report_path, paths["fixture"])
                    else:
                        self.assertEqual(runner.verify_inputs(paths["engine"], report_path,
                                                              paths["fixture"]), report)
                source = root / "research/homebrew/service_roundtrip/main.cpp"
                source.parent.mkdir(parents=True)
                source.write_bytes(b"original service fixture")
                service_fixture = root / "second.oelf"
                service_fixture.write_bytes(b"second fixture")
                service_contract = root / "config/service-roundtrip.json"
                service_contract.write_text(json.dumps(dict(schema_version=1,
                    source_sha256=runner.digest(source), oelf_sha256=runner.digest(service_fixture))))
                self.assertEqual(runner.verify_inputs(paths["engine"], report_path,
                    service_fixture, "service-roundtrip"), report)
                for candidate, profile in ((paths["fixture"], "service-roundtrip"),
                                           (service_fixture, "hello-world"), (service_fixture, "arbitrary")):
                    with self.assertRaises(ValueError):
                        runner.verify_inputs(paths["engine"], report_path, candidate, profile)
                source.write_bytes(b"tampered fixture")
                with self.assertRaisesRegex(ValueError, "source checksum"):
                    runner.verify_inputs(paths["engine"], report_path, service_fixture, "service-roundtrip")
                paths["services_header"].write_bytes(b"changed implementation")
                with self.assertRaisesRegex(ValueError, "Kernel services header checksum"):
                    runner.verify_inputs(paths["engine"], report_path, paths["fixture"])
                paths["services_header"].write_bytes(b"services_header")
                paths["aac_header"].write_bytes(b"changed decoder implementation")
                with self.assertRaisesRegex(ValueError, "AAC decoder header checksum"):
                    runner.verify_inputs(paths["engine"], report_path, paths["fixture"])
                paths["aac_header"].write_bytes(b"aac_header")
                for field, value in (("aac_header_sha256", "wrong"), ("patched_tree", "wrong"),
                                     ("aac_backend", "fdk"), ("fdk_linkage_verified_absent", False),
                                     ("aac_tests", {"status": "failed"})):
                    candidate = dict(report); candidate[field] = value
                    report_path.write_text(json.dumps(candidate))
                    with self.subTest(field=field), self.assertRaisesRegex(ValueError, "strict build evidence"):
                        runner.verify_inputs(paths["engine"], report_path, paths["fixture"])

    def test_session_is_empty_and_existing_profiles_are_refused(self):
        with tempfile.TemporaryDirectory(dir=DRIVER.resolve().parent) as directory:
            root = Path(directory)
            personal = root / "personal-save.dat"
            personal.write_bytes(b"unrelated user data")
            work = root / "session"
            runner.prepare_session(work)
            homes = work / "user" / "home"
            self.assertEqual({p.name for p in homes.iterdir()}, {"1000", "1001", "1002", "1003"})
            for home in homes.iterdir():
                self.assertEqual({p.name for p in home.iterdir()}, {"savedata", "trophy", "inputs"})
            self.assertFalse(any(p.is_file() for p in work.rglob("*")))
            self.assertEqual(personal.read_bytes(), b"unrelated user data")
            sentinel = work / "user" / "users.json"
            sentinel.write_text("existing profile", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                runner.prepare_session(work)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "existing profile")

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

    def test_failed_attempt_keeps_all_imports_and_cleanup(self):
        with tempfile.TemporaryDirectory(dir=DRIVER.resolve().parent) as directory:
            output = Path(directory)
            work = output / "session"
            work.mkdir()
            events = [event("configured", strict_imports=True),
                      event("unresolved", symbol="first#B#B", library="libkernel", module="libkernel"),
                      event("unresolved", symbol="second#B#B", library="libkernel", module="libkernel"),
                      event("imports_checked", phase="initial", unresolved_count=2)]
            trace = work / "startup-audit.jsonl"
            trace.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
            transport = dict(schema_version=1, reason="exited", exit_code=86, tree_cleanup=True)
            (work / "supervisor.json").write_text(json.dumps(transport), encoding="utf-8")
            result = dict(g2_passed=False, guest_execution_tested=False)
            runner.collect_failure_evidence(output, result)
            self.assertEqual(result["transport"], transport)
            self.assertEqual([e["symbol"] for e in result["audit"]["unresolved"]],
                             ["first#B#B", "second#B#B"])
            self.assertEqual(result["audit"]["sha256"], runner.digest(trace))
            self.assertIn("Unresolved", result["audit"]["validation_error"])
            self.assertFalse(result["guest_execution_tested"])
            self.assertFalse(result["g2_passed"])

    def test_later_failure_retains_only_validated_entry_observation(self):
        with tempfile.TemporaryDirectory(dir=DRIVER.resolve().parent) as directory:
            output = Path(directory)
            work = output / "session"
            work.mkdir()
            trace = work / "startup-audit.jsonl"
            variants = [(valid_events() + [event("unresolved", 3_000_000, symbol="late")], True),
                        ([event("guest_entry")], False),
                        ([event("configured", strict_imports=True), event("guest_entry")], False)]
            for events, expected_entry in variants:
                with self.subTest(events=events):
                    trace.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
                    result = dict(g2_passed=False, guest_execution_tested=False)
                    runner.collect_failure_evidence(output, result)
                    self.assertEqual(result["guest_execution_tested"], expected_entry)
                    self.assertEqual(result["guest_entry_observed"], expected_entry)
                    self.assertFalse(result["g2_passed"])
                    self.assertIn("validation_error", result["audit"])

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
            self.assertFalse(report["guest_entry_observed"])
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

    def test_abrupt_helper_exit_kills_job_tree(self):
        with tempfile.TemporaryDirectory(dir=DRIVER.resolve().parent) as directory:
            work = Path(directory).resolve()
            command = [str(SUPERVISOR), str(work), str(work / "stdout.txt"),
                       str(work / "stderr.txt"), str(work / "stop.request"),
                       str(work / "supervisor.json"), "5000", sys.executable,
                       str(ROOT / "tests/startup_child.py"), "tree", str(work)]
            helper = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                deadline = time.monotonic() + 3
                while not (work / "heartbeat.txt").exists() and time.monotonic() < deadline:
                    self.assertIsNone(helper.poll(), "helper exited before starting its job")
                    time.sleep(0.02)
                self.assertTrue((work / "heartbeat.txt").exists())
                descendant = int((work / "child-pid.txt").read_text())
                helper.kill()
                helper.wait(timeout=3)
                # Job close is asynchronous; allow a bounded shutdown interval.
                time.sleep(0.2)
                self.assert_dead(descendant)
            finally:
                if helper.poll() is None:
                    helper.kill()
                    helper.wait(timeout=3)


if __name__ == "__main__":
    unittest.main()
