# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Portable audit-policy tests; no FFmpeg binary or guest execution here."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import audit_ffmpeg as audit


class MetadataTests(unittest.TestCase):
    def setUp(self):
        self.contract = json.loads((ROOT / "config/ffmpeg-audit.json").read_text())
        self.configuration = ("--enable-pic --disable-doc --disable-autodetect "
                              "--disable-libfdk-aac --prefix='C:/private build/host-data' "
                              "--extra-cflags='-I C:/private/compiler --enable-gpl'")
        self.metadata = dict(schema_version=1, ffmpeg_version=self.contract["source"]["version"],
            libraries={k: dict(header_version=v["version"], binary_version=v["version"],
                               license=self.contract["expected_license"], configuration=self.configuration)
                       for k, v in self.contract["libraries"].items()})

    def test_expected_metadata_and_public_fields(self):
        result = audit.review_metadata(self.metadata, self.contract)
        self.assertEqual(set(result["libraries"]), set(self.contract["libraries"]))
        self.assertTrue(result["license_enabling_options_absent"])
        self.assertEqual(result["semantic_configure_flags"],
                         ["--disable-autodetect", "--disable-doc", "--disable-libfdk-aac", "--enable-pic"])
        serialized = json.dumps(result)
        for private in ("private", "compiler", "prefix", "extra-cflags", "configuration"):
            self.assertNotIn(private, serialized)
        self.assertNotIn("redistribution_approved", result)

    def test_source_identity_and_exact_library_set(self):
        variants = []
        wrong_version = copy.deepcopy(self.metadata); wrong_version["ffmpeg_version"] = "5.1.2"; variants.append(wrong_version)
        missing = copy.deepcopy(self.metadata); del missing["libraries"]["avcodec"]; variants.append(missing)
        extra = copy.deepcopy(self.metadata); extra["libraries"]["unexpected"] = {}; variants.append(extra)
        schema = copy.deepcopy(self.metadata); schema["schema_version"] = 2; variants.append(schema)
        boolean = copy.deepcopy(self.metadata); boolean["schema_version"] = True; variants.append(boolean)
        for value in variants:
            with self.subTest(value=value), self.assertRaises(ValueError):
                audit.review_metadata(value, self.contract)

    def test_header_binary_and_license_mismatches(self):
        for key, value in (("header_version", 1), ("binary_version", 1),
                           ("header_version", True), ("binary_version", "1"),
                           ("license", "nonfree and unredistributable"), ("license", "GPL version 3")):
            candidate = copy.deepcopy(self.metadata)
            candidate["libraries"]["avcodec"][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                audit.review_metadata(candidate, self.contract)

    def test_each_library_configuration_is_checked(self):
        for name in self.contract["libraries"]:
            candidate = copy.deepcopy(self.metadata)
            candidate["libraries"][name]["configuration"] += " --enable-nonfree"
            with self.subTest(name=name), self.assertRaises(ValueError):
                audit.review_metadata(candidate, self.contract)

    def test_configuration_consistency(self):
        self.metadata["libraries"]["avcodec"]["configuration"] += " --disable-doc"
        with self.assertRaisesRegex(ValueError, "disagree"):
            audit.review_metadata(self.metadata, self.contract)

    def test_top_level_license_switches_fail(self):
        for option in ("gpl", "version3", "nonfree", "libfdk-aac"):
            for suffix in ("", "=yes"):
                with self.subTest(option=option, suffix=suffix), self.assertRaises(ValueError):
                    audit.configuration_flags("--disable-everything --enable-" + option + suffix)

    def test_invalid_or_unbounded_configuration(self):
        for value in (None, 1, "x" * 65537, "--extra-cflags='unterminated"):
            with self.subTest(value=str(value)[:30]), self.assertRaises(ValueError):
                audit.configuration_flags(value)

    def test_cached_tamper_is_not_downloaded_over(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source"
            path.write_bytes(b"valid input")
            expected = audit.sha(path.read_bytes())
            audit.check_file(path, expected)
            path.write_bytes(b"changed input")
            with patch.object(audit.urllib.request, "urlopen") as network:
                with self.assertRaisesRegex(ValueError, "checksum"):
                    audit.fetch("https://example.invalid/unused", path, expected)
                network.assert_not_called()
            self.assertEqual(path.read_bytes(), b"changed input")

    def test_output_is_private_to_build(self):
        self.assertEqual(audit.private_directory(ROOT / "build/release-audit/test"),
                         (ROOT / "build/release-audit/test").resolve())
        with self.assertRaises(ValueError):
            audit.private_directory(ROOT / "research/results")


if __name__ == "__main__":
    unittest.main()
