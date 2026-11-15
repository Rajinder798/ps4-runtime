# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Portable checks of saves kept across registered launches; a fake engine stands in for shadPS4."""
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
import psf
import run_save_counter as counter
import title_save_store as store

TITLE, DIRECTORY = counter.TITLE_ID, counter.DIRECTORY


class FakeEngine:
    """Acts like save_counter on the staged session: reads the staged counter and stores count + 1."""
    def __init__(self, mode="normal"):
        self.mode, self.launches = mode, []

    def supervise(self, supervisor, command, work, timeout, poll):
        staged = Path(command[2])
        title = psf.read((staged.parent / "sce_sys/param.sfo").read_bytes())["TITLE_ID"]
        homes = work / "user/home"
        visible = sorted(str(p.relative_to(homes)).replace("\\", "/") for p in homes.glob("*/savedata/*"))
        existing = homes / "1000/savedata" / title / DIRECTORY / "counter.bin"
        previous = counter.decode(existing.read_bytes()) if existing.is_file() else 0
        outputs = [counter.BEGIN]
        if self.mode == "fail":
            outputs.append("save-counter: FAIL write mount 0x809f0001")
        else:
            written = previous + (2 if self.mode == "wrong_file" else 1)
            folder = existing.parent
            (folder / "sce_sys").mkdir(parents=True, exist_ok=True)
            existing.write_bytes(counter.encode(written))
            (folder / "sce_sys/param.sfo").write_bytes(psf.write({"TITLE_ID": title, "SAVEDATA_DIRECTORY": DIRECTORY}))
            if self.mode == "other_title":
                (homes / "1000/savedata/PRTS00001/PS4RTSAVE01").mkdir(parents=True)
            shown = previous + (5 if self.mode == "wrong_line" else 1)
            outputs.append(f"save-counter: PASS previous={previous} count={shown}")
        events = [dict(schema_version=1, event="configured", elapsed_us=0, strict_imports=True),
                  dict(schema_version=1, event="imports_checked", elapsed_us=1, phase="entry", unresolved_count=0),
                  dict(schema_version=1, event="guest_entry", elapsed_us=2)]
        events += [dict(schema_version=1, event="guest_output", elapsed_us=10 + i, text=t) for i, t in enumerate(outputs)]
        (work / "startup-audit.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
        self.launches.append(dict(title=title, visible=visible, previous=previous, line=outputs[-1],
                                  config=(work / "user/config.json").read_text() if (work / "user/config.json").exists() else None))
        try:
            poll()
        except ValueError:
            pass  # The real supervisor records a failing poll and stops the engine.
        return dict(schema_version=1, reason="requested", exit_code=125, forced_termination=True,
                    tree_cleanup=self.mode != "no_cleanup", root_exit_verified=True)


class LaunchSaveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / "state"
        self.paths = {}
        for name in ("engine", "report", "supervisor", "save-counter", "hello-world"):
            path = self.root / "inputs" / name
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(name.encode())
            self.paths[name] = path
        done = subprocess.CompletedProcess([], 0, b"vulkan summary", b"")
        # Fake the Windows host completely, so the suite behaves the same on Linux CI.
        for target, name, value in ((launcher.sys, "platform", "win32"), (counter.startup, "background_process_options", lambda: {}),
                                    (counter.save, "verify_inputs", lambda *a, **k: {"status": "strict_engine_built"}),
                                    (launcher.research, "verify_inputs", lambda *a, **k: {"status": "strict_engine_built"}),
                                    (counter.shutil, "which", lambda name: "vulkaninfo"),
                                    (counter.subprocess, "run", lambda *a, **k: done)):
            patcher = patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(launcher.platform, "machine", return_value="AMD64")
        patcher.start()
        self.addCleanup(patcher.stop)
        launcher.register(self.home, self.paths["engine"], self.paths["report"], self.paths["supervisor"],
                          {"save-counter": self.paths["save-counter"], "hello-world": self.paths["hello-world"]})

    def launch(self, engine):
        with patch.object(counter.startup, "supervise", side_effect=engine.supervise):
            code, response = launcher.launch(self.home, launcher.SAVE_PROFILE)
        if response["session_id"]:
            stored = json.loads((Path(response["logs_directory"]) / "launch-result.json").read_text())
            self.assertEqual(stored["status"], response["status"])
        return code, response

    def stored_count(self):
        path = self.home / "titles" / TITLE / "1000" / DIRECTORY / "counter.bin"
        return counter.decode(path.read_bytes()) if path.exists() else 0

    def snapshot(self):
        root = self.home / "titles"
        return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*"))
                if p.is_file() and not p.name.endswith(".lock")} if root.exists() else {}

    def test_registered_launches_keep_the_title_save(self):
        engine, sessions = FakeEngine(), set()
        for expected in (1, 2, 3):
            code, response = self.launch(engine)
            self.assertEqual((code, response["status"]), (0, "completed"), response.get("error"))
            self.assertEqual(response["completion"], "fixture_observed_and_stopped")
            self.assertEqual((response["save_previous_count"], response["save_count"]), (expected - 1, expected))
            self.assertTrue(response["saves_committed"])
            self.assertEqual(response["saves_staged"]["users"], [] if expected == 1 else ["1000"])
            self.assertEqual(self.stored_count(), expected)
            sessions.add(response["session_id"])
        self.assertEqual(len(sessions), 3)
        self.assertEqual([l["previous"] for l in engine.launches], [0, 1, 2])
        self.assertEqual(sorted(p.name for p in (self.home / "titles").iterdir() if not p.name.startswith(".")), [TITLE])

    def test_other_titles_saves_are_never_staged(self):
        other = self.home / "titles/PRTS00001/1000/PS4RTSAVE01"
        other.mkdir(parents=True)
        (other / "result.bin").write_bytes(b"x" * 256)
        engine = FakeEngine()
        self.assertEqual(self.launch(engine)[0], 0)
        self.assertEqual(self.launch(engine)[0], 0)
        self.assertEqual(engine.launches[0]["visible"], [])
        self.assertEqual(engine.launches[1]["visible"], [f"1000/savedata/{TITLE}"])
        self.assertEqual((other / "result.bin").read_bytes(), b"x" * 256)

    def assert_failed_launch_keeps_store(self, mode, code, error):
        self.assertEqual(self.launch(FakeEngine())[0], 0)
        before = self.snapshot()
        result, response = self.launch(FakeEngine(mode))
        self.assertEqual((result, response["error"]["code"]), (code, error), response)
        self.assertFalse(response["saves_committed"])
        self.assertEqual(self.snapshot(), before)
        # The next good launch continues from the kept save, not from the failed session.
        good = FakeEngine()
        self.assertEqual(self.launch(good)[0], 0)
        self.assertEqual(good.launches[0]["previous"], 1)
        self.assertEqual(self.stored_count(), 2)
        return response

    def test_guest_failure_commits_nothing(self):
        response = self.assert_failed_launch_keeps_store("fail", 5, "guest_failed")
        self.assertTrue(response["guest_entry_observed"])

    def test_wrong_file_on_disk_is_caught_by_the_host(self):
        self.assert_failed_launch_keeps_store("wrong_file", 5, "guest_failed")

    def test_guest_reporting_another_count_fails(self):
        self.assert_failed_launch_keeps_store("wrong_line", 5, "guest_failed")

    def test_unconfirmed_cleanup_commits_nothing(self):
        self.assert_failed_launch_keeps_store("no_cleanup", 5, "guest_failed")

    def test_session_with_another_titles_save_is_not_committed(self):
        self.assert_failed_launch_keeps_store("other_title", 6, "save_commit_failed")

    def test_damaged_store_is_refused_before_launch(self):
        self.assertEqual(self.launch(FakeEngine())[0], 0)
        path = self.home / "titles" / TITLE / "1000" / DIRECTORY / "counter.bin"
        path.write_bytes(path.read_bytes()[:-1] + b"\0")
        before, engine = self.snapshot(), FakeEngine()
        code, response = self.launch(engine)
        self.assertEqual((code, response["error"]["code"]), (4, "save_store_failed"))
        self.assertFalse(response["engine_launch_attempted"])
        self.assertEqual((engine.launches, self.snapshot()), ([], before))

    def test_concurrent_launch_of_the_same_title_is_refused(self):
        engine = FakeEngine()
        with store.lock(self.home, TITLE):
            code, response = self.launch(engine)
        self.assertEqual((code, response["error"]["code"]), (4, "save_store_failed"))
        self.assertEqual(engine.launches, [])
        self.assertEqual(self.launch(engine)[0], 0)

    def test_log_preference_reaches_the_engine(self):
        launcher.runtime_settings.update(self.home, launcher.PROFILES, title=launcher.SAVE_PROFILE, level="warning")
        engine = FakeEngine()
        code, response = self.launch(engine)
        self.assertEqual((code, response["effective_settings"]), (0, {"log_level": "warning"}))
        self.assertEqual(json.loads(engine.launches[0]["config"])["Log"]["filter"], "*:warning")

    def test_configuration_schema_4(self):
        config = launcher.read_config(self.home)
        self.assertEqual(config["schema_version"], 4)
        self.assertIn("fixture", launcher.check_inputs(config, "hello-world"))
        for version, fixtures in ((4, {"hello-world"}), (3, {"save-counter", "live-av"}), (1, {"save-counter"})):
            broken = dict(config, schema_version=version,
                          fixtures={k: config["fixtures"].get(k, config["fixtures"]["hello-world"]) for k in fixtures})
            with self.assertRaises(ValueError):
                launcher.validate_config(broken)

    def test_counter_format(self):
        self.assertEqual(counter.decode(counter.encode(7)), 7)
        for blob in (counter.encode(7)[:-1], b"X" + counter.encode(7)[1:], counter.encode(7)[:8] + b"\x07\0\0\0\0\0\0\0",
                     counter.encode(0), counter.encode(counter.MAX_COUNT)):
            with self.assertRaises(ValueError):
                counter.decode(blob)
        self.assertEqual(counter.markers(4)[1], "save-counter: PASS previous=4 count=5")


if __name__ == "__main__":
    unittest.main()
