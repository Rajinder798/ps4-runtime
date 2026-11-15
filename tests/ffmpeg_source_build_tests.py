# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Portable checks of the FFmpeg source build's fixed inputs; the build itself runs on Windows."""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import audit_ffmpeg
import build_ffmpeg_source as build


class FfmpegSourceBuildTests(unittest.TestCase):
    def setUp(self):
        self.flags = json.loads(build.RECORD.read_text(encoding="utf-8"))["semantic_configure_flags"]

    def test_toolchain_adds_no_semantic_flags(self):
        # Only toolchain options; every feature/license choice comes from the audited prebuilt.
        reviewed = audit_ffmpeg.configuration_flags(" ".join(build.TOOLCHAIN))
        self.assertEqual(reviewed, [])
        self.assertIn("--extra-cflags=-MT", build.TOOLCHAIN)
        self.assertIn("--cc=clang-cl", build.TOOLCHAIN)

    def test_license_enabling_options_are_absent(self):
        for option in ("--enable-gpl", "--enable-version3", "--enable-nonfree", "--enable-libfdk-aac"):
            self.assertNotIn(option, self.flags)
        self.assertIn("--disable-libfdk-aac", self.flags)

    def test_compare_flags(self):
        build.compare_flags(self.flags, list(self.flags))
        with self.assertRaisesRegex(ValueError, r"missing \['--enable-decoder=aac'\], extra \[\]"):
            build.compare_flags(self.flags, [f for f in self.flags if f != "--enable-decoder=aac"])
        with self.assertRaisesRegex(ValueError, r"extra \['--enable-gpl'\]"):
            build.compare_flags(self.flags, sorted(self.flags + ["--enable-gpl"]))

    @unittest.skipUnless(sys.platform == "win32", "Windows drive paths")
    def test_posix_paths(self):
        self.assertEqual(build.posix(Path("C:/ps4-runtime/build/x")), "/c/ps4-runtime/build/x")


if __name__ == "__main__":
    unittest.main(verbosity=2)
