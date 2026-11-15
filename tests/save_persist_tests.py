# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Portable checks of the save persistence runner; a fake engine stands in for shadPS4."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import psf
import run_save_persist as persist
import run_save_roundtrip as save
import title_save_store as store

DIRECTORY = save.DIRECTORY


class FakeEngine:
    """Acts like the two fixtures on the staged app: the writer stores, the reader only reads."""
    def __init__(self, writer_fails=False, reader_corrupts=False, reader_ignores_title=False):
        self.writer_fails, self.reader_corrupts, self.reader_ignores_title = writer_fails, reader_corrupts, reader_ignores_title
        self.launches = []

    def supervise(self, supervisor, command, work, timeout, poll):
        staged = Path(command[2])
        title = psf.read((staged.parent / "sce_sys/param.sfo").read_bytes())["TITLE_ID"]
        challenge = (staged.parent / "challenge.bin").read_bytes()
        folder = work / "user/home/1000/savedata" / title / DIRECTORY
        writer = staged.name == "save_roundtrip.oelf"
        prefix = "save-roundtrip" if writer else "save-readback"
        outputs = [prefix + ": begin"]
        if writer:
            if self.writer_fails:
                outputs.append("save-roundtrip: FAIL create mount 0x809f0007")
            else:
                (folder / "sce_sys").mkdir(parents=True)
                (folder / "result.bin").write_bytes(save.expected(challenge))
                (folder / "sce_sys/param.sfo").write_bytes(psf.write({"TITLE_ID": title, "SAVEDATA_DIRECTORY": DIRECTORY}))
                outputs.append(save.MARKERS[1])
        else:
            candidates = (list((work / "user/home").glob(f"*/savedata/*/{DIRECTORY}/result.bin"))
                          if self.reader_ignores_title else [folder / "result.bin"])
            found = next((c for c in candidates if c.is_file() and c.read_bytes() == save.expected(challenge)), None)
            if found is None:
                outputs.append("save-readback: FAIL mount existing 0x809f0008")
            else:
                outputs.append(persist.READER_MARKERS[1])
                if self.reader_corrupts:
                    found.write_bytes(b"\0" * 256)
        events = [dict(schema_version=1, event="configured", elapsed_us=0, strict_imports=True),
                  dict(schema_version=1, event="imports_checked", elapsed_us=1, phase="entry", unresolved_count=0),
                  dict(schema_version=1, event="guest_entry", elapsed_us=2)]
        events += [dict(schema_version=1, event="guest_output", elapsed_us=10 + i, text=t) for i, t in enumerate(outputs)]
        (work / "startup-audit.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
        self.launches.append((title, staged.name, outputs[-1]))
        poll()
        return dict(schema_version=1, reason="requested", exit_code=125, forced_termination=True,
                    tree_cleanup=True, root_exit_verified=True)


class SavePersistTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.inputs = {}
        for name in ("engine", "writer", "reader", "supervisor", "report"):
            path = self.root / "inputs" / name
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(name.encode())
            self.inputs[name] = path

    def run_with(self, engine, patches=None):
        # A fresh output folder per run, so one failing run cannot affect the next.
        output = Path(tempfile.mkdtemp(dir=self.root, prefix="out-"))
        done = subprocess.CompletedProcess([], 0, b"vulkan summary", b"")
        # Fake the Windows host completely, including the Windows-only process flags,
        # so the suite behaves the same on the Linux CI runners.
        with patch.object(persist.sys, "platform", "win32"), patch.object(persist.platform, "machine", return_value="AMD64"), \
                patch.object(persist.startup, "background_process_options", return_value={}), \
                patch.object(persist.save, "verify_inputs", return_value={"status": "strict_engine_built"}), \
                patch.object(persist, "verify_reader"), patch.object(persist.shutil, "which", return_value="vulkaninfo"), \
                patch.object(persist.subprocess, "run", return_value=done), \
                patch.object(persist.startup, "supervise", side_effect=engine.supervise):
            patchers = [patch.object(target, name, value) for (target, name), value in (patches or {}).items()]
            for p in patchers:
                p.start()
            try:
                code, result = persist.run_persistence(
                    engine=self.inputs["engine"], engine_report=self.inputs["report"], writer=self.inputs["writer"],
                    reader=self.inputs["reader"], supervisor=self.inputs["supervisor"], output=output)
            finally:
                for p in patchers:
                    p.stop()
        self.assertEqual(json.loads((output / "persist-result.json").read_text())["status"], result["status"])
        return code, result, output

    def test_save_persists_for_its_title_and_stays_hidden_from_another(self):
        engine = FakeEngine()
        code, result, output = self.run_with(engine)
        self.assertEqual((code, result["status"]), (0, "passed"), result.get("error"))
        self.assertEqual(engine.launches, [
            (save.TITLE_ID, "save_roundtrip.oelf", save.MARKERS[1]),
            (save.TITLE_ID, "save_readback.oelf", persist.READER_MARKERS[1]),
            (persist.OTHER_TITLE, "save_readback.oelf", "save-readback: FAIL mount existing 0x809f0008")])
        launches = result["launches"]
        self.assertEqual(launches["a-write"]["staged"]["users"], [])
        self.assertEqual(launches["a-write"]["committed"]["users"], ["1000"])
        self.assertEqual(launches["b-same-title"]["staged"]["users"], ["1000"])
        self.assertEqual(launches["b-same-title"]["save"]["result_sha256"], launches["a-write"]["save"]["result_sha256"])
        self.assertTrue(launches["c-other-title"]["guest_failure"].startswith(persist.ISOLATION_FAILURE))
        self.assertEqual(launches["c-other-title"]["save_folders_after"], [])
        self.assertEqual(result["store_after"]["titles"], [save.TITLE_ID])
        self.assertTrue((output / "store/titles" / save.TITLE_ID / "1000" / DIRECTORY / "result.bin").is_file())

    def test_a_store_that_does_not_keep_the_save_fails_at_the_second_launch(self):
        code, result, _ = self.run_with(FakeEngine(), {(persist.store, "commit"): lambda *a: {"users": ["1000"]}})
        self.assertEqual((code, result["status"]), (1, "failed"))
        self.assertIn("not staged for the same title", result["error"])

    def test_a_store_that_leaks_to_another_title_is_caught(self):
        real = store.stage

        def leaky(state, title, session):
            # Bug under test: every title gets the first title's saves.
            return real(state, save.TITLE_ID if title == persist.OTHER_TITLE else title, session)

        for engine in (FakeEngine(), FakeEngine(reader_ignores_title=True)):
            with self.subTest(reader_ignores_title=engine.reader_ignores_title):
                with patch.object(persist.store, "stage", side_effect=leaky):
                    code, result, output = self.run_with(engine)
                self.assertEqual((code, result["status"]), (1, "failed"))
                self.assertTrue("must start empty" in result["error"] or "became visible" in result["error"]
                                or "Expected guest failure" in result["error"], result["error"])

    def test_isolation_host_check_catches_a_leaked_folder_even_if_the_guest_fails(self):
        real = store.stage

        def leaky_but_reports_empty(state, title, session):
            staged = real(state, save.TITLE_ID if title == persist.OTHER_TITLE else title, session)
            return dict(staged, users=[]) if title == persist.OTHER_TITLE else staged

        code, result, _ = self.run_with(FakeEngine(), {(persist.store, "stage"): leaky_but_reports_empty})
        self.assertEqual((code, result["status"]), (1, "failed"))
        self.assertIn("became visible to another title", result["error"])

    def test_writer_failure_commits_nothing_and_stops(self):
        engine = FakeEngine(writer_fails=True)
        code, result, output = self.run_with(engine)
        self.assertEqual((code, result["status"]), (1, "failed"))
        self.assertEqual(len(engine.launches), 1)
        self.assertNotIn("committed", result["launches"]["a-write"])
        self.assertFalse((output / "store/titles").exists())

    def test_a_reader_pass_is_not_trusted_without_the_host_check(self):
        code, result, _ = self.run_with(FakeEngine(reader_corrupts=True))
        self.assertEqual((code, result["status"]), (1, "failed"))
        self.assertIn("differs from the independent host calculation", result["error"])

    def test_launch_requires_entry_cleanup_and_the_expected_outcome(self):
        work = self.root / "single/session"
        work.mkdir(parents=True)
        events = [dict(schema_version=1, event="configured", elapsed_us=0, strict_imports=True),
                  dict(schema_version=1, event="imports_checked", elapsed_us=1, phase="entry", unresolved_count=0),
                  dict(schema_version=1, event="guest_entry", elapsed_us=2),
                  dict(schema_version=1, event="guest_output", elapsed_us=3, text=persist.READER_MARKERS[0]),
                  dict(schema_version=1, event="guest_output", elapsed_us=4, text=persist.READER_MARKERS[1])]
        good = dict(reason="requested", tree_cleanup=True)
        cases = {"pass": (events, good, None, True), "dirty": (events, dict(good, tree_cleanup=False), None, False),
                 "timeout": (events, dict(good, reason="timeout"), None, False),
                 "unexpected pass": (events, good, persist.ISOLATION_FAILURE, False),
                 "no entry": ([e for e in events if e["event"] != "guest_entry"], good, None, False)}
        for name, (trace, transport, expect, ok) in cases.items():
            with self.subTest(case=name):
                def supervise(supervisor, command, work_dir, timeout, poll):
                    (work_dir / "startup-audit.jsonl").write_text("".join(json.dumps(e) + "\n" for e in trace))
                    return transport
                with patch.object(persist.startup, "supervise", side_effect=supervise):
                    run = lambda: persist.launch(engine=Path("e"), supervisor=Path("s"), work=work, staged=Path("x"),
                                                 markers=persist.READER_MARKERS, failure=persist.READER_FAILURE,
                                                 timeout=30, expect_failure=expect)
                    if ok:
                        self.assertTrue(run()["markers_observed"])
                    else:
                        with self.assertRaises(ValueError):
                            run()

    def test_save_runner_evaluate_defaults_are_unchanged(self):
        events = [dict(schema_version=1, event="configured", elapsed_us=0, strict_imports=True),
                  dict(schema_version=1, event="imports_checked", elapsed_us=1, phase="entry", unresolved_count=0),
                  dict(schema_version=1, event="guest_entry", elapsed_us=2),
                  dict(schema_version=1, event="guest_output", elapsed_us=3, text=save.MARKERS[0]),
                  dict(schema_version=1, event="guest_output", elapsed_us=4, text=save.MARKERS[1])]
        self.assertTrue(save.evaluate(events)["markers_observed"])
        self.assertFalse(save.evaluate(events, persist.READER_MARKERS, persist.READER_FAILURE)["markers_observed"])

    def test_reader_contract_matches_the_reviewed_source(self):
        contract = json.loads((ROOT / "config/save-readback.json").read_text())
        self.assertEqual(save.startup.digest(ROOT / "research/homebrew/save_readback/main.cpp"), contract["source_sha256"])
        with self.assertRaisesRegex(ValueError, "Read-back fixture hash"):
            persist.verify_reader(self.inputs["reader"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
