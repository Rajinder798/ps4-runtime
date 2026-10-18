# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Audit semantics and real Windows process-tree tests, not PS4 execution tests."""
import ctypes
import json
import os
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
import window_shutdown as shutdown

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
    def test_window_close_policy_rejects_missing_forced_crashed_or_foreign_exit(self):
        closing = shutdown.WindowClose()
        good = dict(reason="exited", root_pid=42, exit_code=0, tree_cleanup=True,
                    active_before_cleanup=0, forced_termination=False)
        with self.assertRaises(ValueError):
            closing.verify(good)
        closing.request = dict(root_pid=42, transport="owned SDL window WM_CLOSE")
        self.assertTrue(closing.verify(good)["verified"])
        for field, value in (("reason", "timeout"), ("reason", "requested"), ("root_pid", 43),
                             ("exit_code", 17), ("exit_code", False), ("tree_cleanup", False), ("active_before_cleanup", 1),
                             ("active_before_cleanup", False), ("forced_termination", True)):
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                closing.verify(dict(good, **{field:value}))
        for field in good:
            bad = dict(good); del bad[field]
            with self.subTest(missing=field), self.assertRaises(ValueError):
                closing.verify(bad)

    def test_close_is_not_requested_before_evidence_and_grace_is_bounded(self):
        closing = shutdown.WindowClose()
        with patch("videoout_capture.request_close", return_value=dict(root_pid=42, transport="owned SDL window WM_CLOSE")) as send:
            self.assertFalse(closing.poll(False, 1, Path("engine")))
            send.assert_not_called()
            with patch("window_shutdown.time.monotonic", return_value=10):
                self.assertFalse(closing.poll(True, 1, Path("engine")))
                self.assertFalse(closing.poll(True, 1, Path("engine")))
            send.assert_called_once_with(1, Path("engine"))
            with patch("window_shutdown.time.monotonic", return_value=10 + shutdown.GRACE_SECONDS + 0.1):
                with self.assertRaisesRegex(ValueError, "grace period"):
                    closing.poll(True, 1, Path("engine"))

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
                video_source = root / "research/homebrew/videoout_pattern/main.cpp"
                video_source.parent.mkdir(parents=True)
                video_source.write_bytes(b"original video fixture")
                video_fixture = root / "video.oelf"
                video_fixture.write_bytes(b"video fixture")
                (root / "config/videoout-pattern.json").write_text(json.dumps(dict(schema_version=1,
                    source_sha256=runner.digest(video_source), oelf_sha256=runner.digest(video_fixture))))
                self.assertEqual(runner.verify_inputs(paths["engine"], report_path,
                    video_fixture, "videoout-pattern"), report)
                with self.assertRaises(ValueError):
                    runner.verify_inputs(paths["engine"], report_path, paths["fixture"], "videoout-pattern")
                video_source.write_bytes(b"changed fixture")
                with self.assertRaisesRegex(ValueError, "source checksum"):
                    runner.verify_inputs(paths["engine"], report_path, video_fixture, "videoout-pattern")
                pad_source = root / "research/homebrew/pad_videoout/main.cpp"
                pad_source.parent.mkdir(parents=True)
                pad_source.write_bytes(b"original pad fixture")
                pad_fixture = root / "pad.oelf"
                pad_fixture.write_bytes(b"pad fixture")
                (root / "config/pad-videoout.json").write_text(json.dumps(dict(schema_version=1,
                    source_sha256=runner.digest(pad_source), oelf_sha256=runner.digest(pad_fixture))))
                self.assertEqual(runner.verify_inputs(paths["engine"], report_path,
                    pad_fixture, "pad-videoout"), report)
                with self.assertRaises(ValueError):
                    runner.verify_inputs(paths["engine"], report_path, video_fixture, "pad-videoout")
                pad_source.write_bytes(b"changed fixture")
                with self.assertRaisesRegex(ValueError, "source checksum"):
                    runner.verify_inputs(paths["engine"], report_path, pad_fixture, "pad-videoout")
                audio_source = root / "research/homebrew/audio_pattern/main.cpp"
                audio_source.parent.mkdir(parents=True)
                audio_source.write_bytes(b"original audio fixture")
                audio_fixture = root / "audio.oelf"
                audio_fixture.write_bytes(b"audio fixture")
                (root / "config/audio-pattern.json").write_text(json.dumps(dict(schema_version=1,
                    source_sha256=runner.digest(audio_source), oelf_sha256=runner.digest(audio_fixture))))
                self.assertEqual(runner.verify_inputs(paths["engine"], report_path,
                    audio_fixture, "audio-pattern"), report)
                with self.assertRaises(ValueError):
                    runner.verify_inputs(paths["engine"], report_path, video_fixture, "audio-pattern")
                audio_source.write_bytes(b"changed fixture")
                with self.assertRaisesRegex(ValueError, "source checksum"):
                    runner.verify_inputs(paths["engine"], report_path, audio_fixture, "audio-pattern")
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
    def test_owned_window_close_exits_without_forced_cleanup(self):
        closing, work, result = self.close_window("window")
        self.assertTrue(closing.verify(result)["verified"])
        self.assertEqual((work / "close-observed.txt").read_text(), "WM_CLOSE")
        self.assertFalse((work / "stop.request").exists())

    def test_window_close_root_exit_with_descendant_is_not_clean_shutdown(self):
        closing, work, result = self.close_window("window-orphan")
        self.assertEqual(result["exit_code"], 0)
        self.assertTrue(result["forced_termination"])
        self.assertGreater(result["active_before_cleanup"], 0)
        with self.assertRaises(ValueError):
            closing.verify(result)
        self.assert_dead(int((work / "child-pid.txt").read_text()))

    def test_ignored_window_close_uses_bounded_fallback(self):
        with patch.object(shutdown, "GRACE_SECONDS", 0.2):
            with self.assertRaisesRegex(ValueError, "grace period"):
                self.close_window("window-ignore")
        work = self.last_close_work
        self.assertEqual((work / "close-observed.txt").read_text(), "WM_CLOSE")
        report = json.loads((work / "supervisor.json").read_text())
        self.assertTrue(report["tree_cleanup"])
        self.assertTrue(report["forced_termination"])
        self.assertEqual(report["reason"], "requested")
        self.assert_dead(report["root_pid"])

    def close_window(self, mode):
        directory = tempfile.TemporaryDirectory(dir=DRIVER.resolve().parent)
        self.addCleanup(directory.cleanup)
        work = Path(directory.name).resolve()
        self.last_close_work = work
        closing, owners = shutdown.WindowClose(), []
        def poll():
            return closing.poll((work / "window-ready.txt").exists(), owners[0], Path(sys.executable).resolve())
        result = runner.supervise(SUPERVISOR,
            [Path(sys.executable).resolve(), ROOT / "tests/startup_child.py", mode, work],
            work, 4, poll, on_started=owners.append)
        return closing, work, result

    def test_child_audio_environment_override_is_process_local(self):
        with tempfile.TemporaryDirectory(dir=DRIVER.resolve().parent) as directory:
            work = Path(directory).resolve()
            before = dict(os.environ)
            environment = dict(before, SDL_AUDIO_DRIVER="test-only-driver")
            result = runner.supervise(SUPERVISOR,
                [Path(sys.executable).resolve(), ROOT / "tests/startup_child.py", "environment", work],
                work, 3, lambda: False, environment=environment)
            self.assertEqual(result["reason"], "exited")
            self.assertTrue(result["tree_cleanup"])
            self.assertEqual(json.loads((work / "environment.json").read_text()), {"driver":"test-only-driver"})
            self.assertEqual(dict(os.environ), before)

    def test_started_callback_and_foreign_window_rejection(self):
        from videoout_capture import request_screenshot, request_close
        with tempfile.TemporaryDirectory(dir=DRIVER.resolve().parent) as directory:
            work = Path(directory).resolve()
            owners = []
            def poll():
                if not (work / "heartbeat.txt").exists():
                    return False
                with self.assertRaisesRegex(ValueError, "engine child owned"):
                    request_screenshot(owners[0], DRIVER.resolve())
                with self.assertRaisesRegex(ValueError, "engine child owned"):
                    request_close(owners[0], DRIVER.resolve())
                return True
            result = runner.supervise(SUPERVISOR,
                [Path(sys.executable).resolve(), ROOT / "tests/startup_child.py", "tree", work],
                work, 3, poll, on_started=owners.append)
            self.assertEqual(len(owners), 1)
            self.assertNotEqual(owners[0], result["root_pid"])
            self.assertEqual(result["reason"], "requested")
            self.assertTrue(result["tree_cleanup"])

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
