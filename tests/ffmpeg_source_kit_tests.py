# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Portable source-kit tests with original tiny source/patch fixtures."""
import copy
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import ffmpeg_source_kit as kit


def tar_bytes(entries):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, data, mode in entries:
            member = tarfile.TarInfo(name)
            if isinstance(data, bytes) and mode != 0:
                member.size, member.mode = len(data), mode
                archive.addfile(member, io.BytesIO(data))
            else:
                member.type = data
                member.linkname = "../../outside"
                archive.addfile(member)
    return buffer.getvalue()


class SourceKitTests(unittest.TestCase):
    def setUp(self):
        first = b"--- a/tone.c\n+++ b/tone.c\n@@ -1 +1 @@\n-original\n+middle\n"
        second = b"--- a/tone.c\n+++ b/tone.c\n@@ -1 +1 @@\n-middle\n+final\n"
        port = b"PATCHES\n    first.patch\n    second.patch # ordered\n)\nOPTIONS old\n"
        wrapper_patch = (b"--- a/ports/ffmpeg/portfile.cmake\n+++ b/ports/ffmpeg/portfile.cmake\n"
                         b"@@ -4,2 +4,2 @@\n )\n-OPTIONS old\n+OPTIONS selected\n")
        source = {"tone.c": (b"original\n", False), "configure": (b"#!/bin/sh\nexit 0\n", True),
                  "LICENSE.md": (b"Original test fixture notice\n", False)}
        vcpkg = {"ports/ffmpeg/portfile.cmake": (port, False),
                 "ports/ffmpeg/first.patch": (first, False),
                 "ports/ffmpeg/second.patch": (second, False),
                 "LICENSE.txt": (b"Original recipe test notice\n", False)}
        wrapper = {"ffmpeg.patch": (wrapper_patch, False),
                   "LICENSE": (b"Original wrapper test notice\n", False)}
        self.inputs = {name: tar_bytes([("root/" + n, data, 0o755 if executable else 0o644)
                                      for n, (data, executable) in files.items()])
                       for name, files in (("ffmpeg", source), ("vcpkg", vcpkg), ("wrapper", wrapper))}
        self.audit = dict(source=dict(version="test", revision="f" * 40, tag="test",
                url="https://invalid.example/ffmpeg", sha512=kit.digest(self.inputs["ffmpeg"], "sha512"),
                notices=[dict(path="LICENSE.md", sha256=kit.digest(source["LICENSE.md"][0]))]),
            vcpkg=dict(files=[dict(path="portfile.cmake", sha256=kit.digest(port))]),
            wrapper=dict(files=[dict(path="ffmpeg.patch", sha256=kit.digest(wrapper_patch))]))
        final = dict(source); final["tone.c"] = (b"final\n", False)
        self.contract = dict(schema_version=1, source_patch_order=["first.patch", "second.patch"],
            patched_source_tree_sha256=kit.tree_hash(final),
            **{name: dict(url="https://invalid.example/" + name, revision="a" * 40,
                          prefix="root", sha256=kit.digest(self.inputs[name]))
               for name in ("vcpkg", "wrapper")})
        # FFmpeg archive root is specified by the existing audit tag convention.
        self.inputs["ffmpeg"] = tar_bytes([("FFmpeg-test/" + n, data, 0o755 if executable else 0o644)
                                          for n, (data, executable) in source.items()])
        self.audit["source"]["sha512"] = kit.digest(self.inputs["ffmpeg"], "sha512")

    def test_actual_ordered_patch_application_and_offline_verification(self):
        with patch.object(kit.urllib.request, "urlopen") as network:
            files = kit.reconstruct(self.inputs, self.audit, self.contract)
            result = kit.verify({n: v[0] for n, v in files.items()}, self.audit, self.contract)
            network.assert_not_called()
        self.assertEqual(files["source/ffmpeg/tone.c"][0], b"final\n")
        self.assertIn(b"OPTIONS selected", files["recipe/ports/ffmpeg/portfile.cmake"][0])
        self.assertIn(b"+final", files["changes/ffmpeg.diff"][0])
        self.assertTrue(files["source/ffmpeg/configure"][1])
        self.assertFalse(result["upstream_redistribution_approved"])
        self.assertFalse(result["independent_binary_rebuild_verified"])
        self.assertFalse(result["static_relink_kit_complete"])

    def test_wrong_patch_order_and_source_tree_fail(self):
        wrong = copy.deepcopy(self.contract); wrong["source_patch_order"].reverse()
        with self.assertRaisesRegex(ValueError, "Ordered"):
            kit.check_inputs(self.inputs, self.audit, wrong)
        wrong = copy.deepcopy(self.contract); wrong["patched_source_tree_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "Patched source"):
            kit.reconstruct(self.inputs, self.audit, wrong)

    def test_added_source_is_present_in_combined_diff(self):
        original = {"original.c": (b"original\n", False)}
        addition = (b"diff --git a/new.c b/new.c\nnew file mode 100644\n"
                    b"--- /dev/null\n+++ b/new.c\n@@ -0,0 +1 @@\n+added\n")
        changed, changes = kit.apply_patches(original, [addition])
        self.assertEqual(changed["new.c"][0], b"added\n")
        self.assertIn(b"+++ b/new.c", changes)
        replayed, _ = kit.apply_patches(original, [changes])
        self.assertEqual(replayed, changed)

    def test_forged_manifest_does_not_authorize_source_tampering(self):
        files = kit.reconstruct(self.inputs, self.audit, self.contract)
        files["source/ffmpeg/tone.c"] = (b"tampered\n", False)
        files["manifest.json"] = (kit.encoded(dict(schema_version=1,
            files=kit.inventory({n: v for n, v in files.items() if n != "manifest.json"}))), False)
        with self.assertRaisesRegex(ValueError, "reconstructed"):
            kit.verify({n: v[0] for n, v in files.items()}, self.audit, self.contract)

    def test_extra_and_missing_files_fail(self):
        files = {n: v[0] for n, v in kit.reconstruct(self.inputs, self.audit, self.contract).items()}
        for extra in (True, False):
            candidate = dict(files)
            if extra:
                candidate["unreviewed.exe"] = b"extra"
            else:
                del candidate["notices/ffmpeg/LICENSE.md"]
            with self.subTest(extra=extra), self.assertRaisesRegex(ValueError, "reconstructed"):
                kit.verify(candidate, self.audit, self.contract)

    def test_changed_snapshot_and_recipe_fail(self):
        for name in self.inputs:
            candidate = dict(self.inputs); candidate[name] += b"changed"
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "checksum"):
                kit.check_inputs(candidate, self.audit, self.contract)
        wrong = copy.deepcopy(self.audit); wrong["vcpkg"]["files"][0]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "recipe"):
            kit.check_inputs(self.inputs, wrong, self.contract)

    def test_archive_paths_links_duplicates_and_collisions_fail(self):
        cases = [[("../escape", b"x", 0o644)], [("other/file", b"x", 0o644)],
            [("root/link", tarfile.SYMTYPE, 0)], [("root/link", tarfile.LNKTYPE, 0)],
            [("root/device", tarfile.CHRTYPE, 0)], [("root/CON.txt", b"x", 0o644)],
            [("root/a:stream", b"x", 0o644)], [("root/a/./file", b"x", 0o644)],
            [("root/a\\file", b"x", 0o644)], [("root/a.", b"x", 0o644)],
            [("root/.git/config", b"x", 0o644)],
            [("root/file", b"1", 0o644), ("root/file", b"2", 0o644)],
            [("root/File", b"1", 0o644), ("root/file", b"2", 0o644)],
            [("root/Dir/one", b"1", 0o644), ("root/dir/two", b"2", 0o644)],
            [("root/a", b"1", 0o644), ("root/a/b", b"2", 0o644)]]
        for entries in cases:
            with self.subTest(entries=entries), self.assertRaises(ValueError):
                kit.read_tar(tar_bytes(entries), "root")

    def test_archive_resource_bounds(self):
        data = tar_bytes([("root/file", b"123", 0o644)])
        for name, value in (("MAX_FILE", 2), ("MAX_EXPANDED", 2), ("MAX_MEMBERS", 0), ("MAX_ARCHIVE", 2)):
            with self.subTest(name=name), patch.object(kit, name, value), self.assertRaises(ValueError):
                kit.read_tar(data, "root")

    def test_deterministic_pack_and_zip_permission_validation(self):
        files = {"source/configure": (b"original\n", True), "notice": (b"notice\n", False)}
        files["manifest.json"] = (kit.encoded(dict(files=kit.inventory(files))), False)
        with tempfile.TemporaryDirectory() as temporary:
            one, two = Path(temporary) / "one.zip", Path(temporary) / "two.zip"
            kit.pack(files, one); kit.pack(dict(reversed(list(files.items()))), two)
            self.assertEqual(one.read_bytes(), two.read_bytes())
            self.assertEqual(kit.read_zip(one)["source/configure"], b"original\n")
            with zipfile.ZipFile(two, "w") as archive:
                for name, (data, _) in files.items():
                    member = zipfile.ZipInfo(name); member.create_system = 3
                    member.external_attr = 0o100644 << 16  # strip executable bit
                    archive.writestr(member, data)
            with self.assertRaisesRegex(ValueError, "permissions"):
                kit.read_zip(two)

    def test_missing_or_tampered_cache_never_downloaded_over(self):
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary)
            with patch.object(kit.urllib.request, "urlopen") as network:
                with self.assertRaisesRegex(ValueError, "Missing offline"):
                    kit.fetch_inputs(cache, self.audit, self.contract, True)
                (cache / "ffmpeg.tar.gz").write_bytes(b"changed")
                with self.assertRaisesRegex(ValueError, "Cached source checksum"):
                    kit.fetch_inputs(cache, self.audit, self.contract, False)
                network.assert_not_called()

    def test_zip_traversal_and_links_fail_before_extraction(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "malicious.zip"
            for name, mode in (("../outside", 0o100644), ("link", 0o120777)):
                with zipfile.ZipFile(path, "w") as archive:
                    member = zipfile.ZipInfo(name); member.create_system = 3
                    member.external_attr = mode << 16
                    archive.writestr(member, b"../../outside")
                with self.subTest(name=name), self.assertRaises(ValueError):
                    kit.read_zip(path)

    def test_output_stays_private(self):
        self.assertEqual(kit.private_path(ROOT / "build/source-kit-test"), (ROOT / "build/source-kit-test").resolve())
        with self.assertRaises(ValueError):
            kit.private_path(ROOT / "research/results")


if __name__ == "__main__":
    unittest.main()
