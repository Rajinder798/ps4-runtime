# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Portable checks of the per-title save store; no engine or guest is run."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import run_homebrew_startup as startup
import title_save_store as store

TITLE, OTHER = "PRTS00001", "PRTS00002"


def session(root, name):
    work = Path(root) / name
    startup.prepare_session(work)
    return work


def write_save(work, title=TITLE, user="1000", directory="PS4RTSAVE01", data=b"\x01" * 256):
    folder = work / "user/home" / user / "savedata" / title / directory
    (folder / "sce_sys").mkdir(parents=True)
    (folder / "result.bin").write_bytes(data)
    (folder / "sce_sys/param.sfo").write_bytes(b"\0PSF" + title.encode())
    return folder


def make_link(link, target):
    """A real link where the OS allows one: a symlink, else a Windows directory junction."""
    try:
        os.symlink(target, link, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            raise
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], check=True, capture_output=True)


def snapshot(root):
    root = Path(root)
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()} if root.exists() else None


class TitleSaveStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = self.root / "state"

    def test_commit_then_stage_round_trips_into_a_fresh_session(self):
        first = session(self.root, "first")
        write_save(first, data=b"\x2a" * 256)
        committed = store.commit(self.state, TITLE, first)
        self.assertEqual((committed["users"], committed["files"], committed["bytes"]), (["1000"], 2, 256 + 13))
        second = session(self.root, "second")
        staged = store.stage(self.state, TITLE, second)
        self.assertEqual((staged["users"], staged["files"]), (["1000"], 2))
        restored = second / "user/home/1000/savedata" / TITLE / "PS4RTSAVE01/result.bin"
        self.assertEqual(restored.read_bytes(), b"\x2a" * 256)
        self.assertEqual(sorted(p.name for p in (second / "user/home/1000/savedata").iterdir()), [TITLE])
        self.assertEqual(list(self.state.joinpath("titles").glob(".*")), [], "no leftover temporary folders")

    def test_titles_are_isolated_in_both_directions(self):
        a = session(self.root, "a")
        write_save(a, TITLE, data=b"A" * 256)
        store.commit(self.state, TITLE, a)
        b = session(self.root, "b")
        self.assertEqual(store.stage(self.state, OTHER, b)["users"], [], "another title sees nothing")
        self.assertEqual([p for p in (b / "user/home").rglob("*") if TITLE in p.parts], [])
        write_save(b, OTHER, data=b"B" * 256)
        store.commit(self.state, OTHER, b)
        c = session(self.root, "c")
        store.stage(self.state, TITLE, c)
        self.assertEqual(sorted(p.name for p in (c / "user/home/1000/savedata").iterdir()), [TITLE])
        self.assertEqual((c / "user/home/1000/savedata" / TITLE / "PS4RTSAVE01/result.bin").read_bytes(), b"A" * 256)

    def test_empty_store_stages_nothing_and_second_commit_replaces_first(self):
        work = session(self.root, "empty")
        self.assertEqual(store.stage(self.state, TITLE, work), {"title_id": TITLE, "users": [], "files": 0, "bytes": 0})
        write_save(work, data=b"1" * 256)
        store.commit(self.state, TITLE, work)
        later = session(self.root, "later")
        store.stage(self.state, TITLE, later)
        (later / "user/home/1000/savedata" / TITLE / "PS4RTSAVE01/result.bin").write_bytes(b"2" * 256)
        write_save(later, user="1001", directory="SECOND")
        store.commit(self.state, TITLE, later)
        stored = self.state / "titles" / TITLE
        self.assertEqual((stored / "1000/PS4RTSAVE01/result.bin").read_bytes(), b"2" * 256)
        self.assertEqual(sorted(p.name for p in stored.iterdir()), ["1000", "1001"])

    def test_refused_sessions_leave_the_previous_store_unchanged(self):
        base = session(self.root, "base")
        write_save(base)
        store.commit(self.state, TITLE, base)
        before = snapshot(self.state / "titles" / TITLE)
        cases = {
            "other title": lambda w: write_save(w, OTHER),
            "stray file": lambda w: (w / "user/home/1000/savedata/stray.bin").write_bytes(b"x"),
            "title as file": lambda w: (w / "user/home/1002/savedata" / TITLE).write_bytes(b"x"),
            "link inside": lambda w: make_link(write_save(w) / "outside", self.root),
            "too many files": lambda w: [(folder / f"f{i}").write_bytes(b"")
                                         for folder in [write_save(w, directory="MANY")] for i in range(store.MAX_FILES)],
        }
        for name, damage in cases.items():
            with self.subTest(case=name):
                work = session(self.root, "refused-" + name.replace(" ", "-"))
                damage(work)
                with self.assertRaises(store.StoreError):
                    store.commit(self.state, TITLE, work)
                self.assertEqual(snapshot(self.state / "titles" / TITLE), before)
                self.assertEqual(list((self.state / "titles").glob(".*")), [])

    def test_oversized_data_is_refused(self):
        work = session(self.root, "big")
        write_save(work)
        with patch.object(store, "MAX_BYTES", 100), self.assertRaisesRegex(store.StoreError, "size or file limit"):
            store.commit(self.state, TITLE, work)
        self.assertFalse((self.state / "titles" / TITLE).exists())

    def test_failed_swap_restores_the_previous_copy(self):
        base = session(self.root, "base")
        write_save(base, data=b"old" * 10)
        store.commit(self.state, TITLE, base)
        before = snapshot(self.state / "titles" / TITLE)
        work = session(self.root, "new")
        write_save(work, data=b"new" * 10)
        real = os.replace
        calls = []

        def failing(source, target):
            calls.append(Path(source).name)
            if len(calls) == 2:
                raise OSError("injected swap failure")
            return real(source, target)

        with patch.object(store.os, "replace", side_effect=failing), self.assertRaises(OSError):
            store.commit(self.state, TITLE, work)
        self.assertEqual(snapshot(self.state / "titles" / TITLE), before)
        self.assertEqual(list((self.state / "titles").glob(".*")), [])

    def test_invalid_ids_unprepared_and_reused_sessions_are_refused(self):
        work = session(self.root, "ids")
        for title in ("prts00001", "PRTS0001", "PRTS000011", "../PRTS0", "", None):
            with self.subTest(title=title):
                with self.assertRaises(store.StoreError):
                    store.stage(self.state, title, work)
                with self.assertRaises(store.StoreError):
                    store.commit(self.state, title, work)
        write_save(work)
        store.commit(self.state, TITLE, work)
        with self.assertRaisesRegex(store.StoreError, "fresh session"):
            store.stage(self.state, TITLE, work)
        with self.assertRaisesRegex(store.StoreError, "prepare_session"):
            store.stage(self.state, TITLE, self.root / "never-prepared")
        (self.state / "titles" / TITLE / "notes.txt").write_text("x")
        with self.assertRaisesRegex(store.StoreError, "Unexpected entry"):
            store.stage(self.state, TITLE, session(self.root, "stray-store"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
