# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Portable checks of the save-roundtrip runner and PSF files; no engine or guest is run."""
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import psf
import run_save_roundtrip as save


def event(kind, elapsed=0, **fields):
    return dict(schema_version=1, event=kind, elapsed_us=elapsed, **fields)


def passing_events():
    return [event("configured", strict_imports=True), event("imports_checked", phase="entry", unresolved_count=0),
            event("guest_entry"), event("guest_output", 10, text=save.MARKERS[0]),
            event("guest_output", 20, text=save.MARKERS[1])]


class SaveRunnerTests(unittest.TestCase):
    def test_strict_audit_and_ordered_markers_are_required(self):
        self.assertTrue(save.evaluate(passing_events())["markers_observed"])
        self.assertFalse(save.evaluate(passing_events()[:4])["markers_observed"])
        for kind in ("missing-entry", "reversed", "failure", "duplicate", "unresolved", "unchecked", "marker-early"):
            bad = [dict(e) for e in passing_events()]
            if kind == "missing-entry":
                del bad[2]
            elif kind == "reversed":
                bad[-2]["text"], bad[-1]["text"] = bad[-1]["text"], bad[-2]["text"]
            elif kind == "failure":
                bad.insert(4, event("guest_output", 15, text="save-roundtrip: FAIL create mount 0x809f0008"))
            elif kind == "duplicate":
                bad.append(dict(bad[-1]))
            elif kind == "unresolved":
                bad.append(event("unresolved", 21, symbol="missing#B#B"))
            elif kind == "unchecked":
                bad[1]["unresolved_count"] = 1
            else:
                bad.insert(2, event("guest_output", 0, text=save.MARKERS[0]))
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                save.evaluate(bad)
        for broken in ([event("guest_entry")], [dict(passing_events()[0], elapsed_us=5), passing_events()[1]]):
            with self.assertRaises(ValueError):
                save.evaluate(broken)

    def test_contract_matches_the_reviewed_source(self):
        contract = json.loads((ROOT / "config/save-roundtrip.json").read_text())
        source = ROOT / "research/homebrew/save_roundtrip/main.cpp"
        self.assertEqual(save.startup.digest(source), contract["source_sha256"])
        text = source.read_text()
        for marker in save.MARKERS:
            self.assertIn(f'"{marker}\\n"', text)
        self.assertIn(f'"{save.DIRECTORY}"', text)
        self.assertIn(f'"{save.FAILURE} %s', text)

    def test_inputs_are_bound_to_engine_report_patch_and_fixture(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config").mkdir()
            files = {}
            for name in ("engine", "fixture", "patch", "audit_header", "services_header", "aac_header", "source"):
                files[name] = root / name
                files[name].write_bytes(name.encode())
            contract = {f"{k}_path": k for k in ("patch", "audit_header", "services_header", "aac_header")}
            contract.update({f"{k}_sha256": save.startup.digest(files[k])
                             for k in ("patch", "audit_header", "services_header", "aac_header")})
            contract["expected_patched_tree"] = "b" * 40
            (root / "config/startup-research.json").write_text(json.dumps(contract))
            (root / "config/g2-integration-audit.json").write_text(json.dumps({"upstream": {"revision": "a" * 40}}))
            (root / "research/homebrew/save_roundtrip").mkdir(parents=True)
            (root / "research/homebrew/save_roundtrip/main.cpp").write_bytes(b"source")
            (root / "config/save-roundtrip.json").write_text(json.dumps(dict(
                schema_version=1, source_sha256=save.startup.digest(files["source"]),
                oelf_sha256=save.startup.digest(files["fixture"]))))
            report = dict(status="strict_engine_built", upstream_revision="a" * 40, patched_tree="b" * 40,
                          aac_backend="ffmpeg-aac-lc", fdk_linkage_verified_absent=True, aac_tests={"status": "passed"},
                          executable_sha256=save.startup.digest(files["engine"]),
                          **{k: v for k, v in contract.items() if k.endswith("_sha256")})
            path = root / "report.json"
            with patch.object(save, "ROOT", root):
                path.write_text(json.dumps(report))
                self.assertEqual(save.verify_inputs(files["engine"], path, files["fixture"]), report)
                for key, value in (("status", "built"), ("patched_tree", "c" * 40), ("patch_sha256", "0"),
                                   ("executable_sha256", "0"), ("fdk_linkage_verified_absent", False)):
                    path.write_text(json.dumps(dict(report, **{key: value})))
                    with self.subTest(key=key), self.assertRaisesRegex(ValueError, "strict build evidence"):
                        save.verify_inputs(files["engine"], path, files["fixture"])
                path.write_text(json.dumps(report))
                with self.assertRaisesRegex(ValueError, "fixture hash"):
                    save.verify_inputs(files["engine"], path, files["engine"])
                (root / "research/homebrew/save_roundtrip/main.cpp").write_bytes(b"tampered")
                with self.assertRaisesRegex(ValueError, "source checksum"):
                    save.verify_inputs(files["engine"], path, files["fixture"])
                (root / "research/homebrew/save_roundtrip/main.cpp").write_bytes(b"source")
                files["patch"].write_bytes(b"changed patch")
                with self.assertRaisesRegex(ValueError, "Research input checksum mismatch: patch"):
                    save.verify_inputs(files["engine"], path, files["fixture"])

    def test_saved_file_and_metadata_are_independently_checked(self):
        challenge = bytes(range(256))
        expected = save.expected(challenge)
        # Same arithmetic as the guest: low byte of (value + 0x3c) ^ (index * 7).
        self.assertEqual(expected[:4], bytes((0x3C, 0x3A, 0x30, 0x2A)))
        self.assertEqual(save.expected(bytes(256))[255], (0x3C ^ (255 * 7)) % 256)
        with self.assertRaises(ValueError):
            save.expected(b"short")
        sfo = psf.write({"TITLE_ID": save.TITLE_ID, "SAVEDATA_DIRECTORY": save.DIRECTORY})
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory) / "session"
            save.startup.prepare_session(work)
            home = work / "user/home"
            folder = home / "1000/savedata" / save.TITLE_ID / save.DIRECTORY
            with self.assertRaisesRegex(ValueError, "found 0"):
                save.verify_save(work, challenge)
            (folder / "sce_sys").mkdir(parents=True)
            (folder / "sce_sys/param.sfo").write_bytes(sfo)
            for data in (None, expected[:-1], expected + b"x", bytes([expected[0] ^ 1]) + expected[1:]):
                if data is not None:
                    (folder / "result.bin").write_bytes(data)
                with self.subTest(size=None if data is None else len(data)), \
                        self.assertRaisesRegex(ValueError, "independent host"):
                    save.verify_save(work, challenge)
            (folder / "result.bin").write_bytes(expected)
            report = save.verify_save(work, challenge)
            self.assertEqual((report["user_id"], report["bytes_verified"]), ("1000", 256))
            self.assertEqual(report["result_sha256"], save.startup.digest(folder / "result.bin"))
            with self.assertRaises(ValueError):
                save.verify_save(work, bytes(reversed(challenge)))
            for entries in ({"TITLE_ID": "OTHER0001", "SAVEDATA_DIRECTORY": save.DIRECTORY},
                            {"TITLE_ID": save.TITLE_ID, "SAVEDATA_DIRECTORY": "OTHER"}, {"TITLE_ID": save.TITLE_ID}):
                (folder / "sce_sys/param.sfo").write_bytes(psf.write(entries))
                with self.subTest(entries=entries), self.assertRaisesRegex(ValueError, "metadata"):
                    save.verify_save(work, challenge)
            (folder / "sce_sys/param.sfo").write_bytes(sfo)
            # A save under an empty title component, or for a second user, is not the single expected save.
            stray = home / "1000/savedata" / save.DIRECTORY
            stray.mkdir()
            with self.assertRaisesRegex(ValueError, "outside the title folder 1"):
                save.verify_save(work, challenge)
            stray.rmdir()
            (home / "1001/savedata" / save.TITLE_ID / save.DIRECTORY).mkdir(parents=True)
            with self.assertRaisesRegex(ValueError, "found 2"):
                save.verify_save(work, challenge)

    def test_staging_writes_title_metadata_and_never_a_save(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = root / "fixture.oelf"
            fixture.write_bytes(b"transport fixture, not guest code")
            challenges = []
            for name in ("first", "second"):
                work = root / name
                save.startup.prepare_session(work)
                staged, challenge = save.prepare(work, fixture)
                self.assertEqual(staged.read_bytes(), fixture.read_bytes())
                self.assertEqual((staged.parent / "challenge.bin").read_bytes(), challenge)
                metadata = psf.read((staged.parent / "sce_sys/param.sfo").read_bytes())
                self.assertEqual(metadata["TITLE_ID"], save.TITLE_ID)
                # INSTALL_DIR_SAVEDATA would override the title folder in the pinned engine.
                self.assertNotIn("INSTALL_DIR_SAVEDATA", metadata)
                self.assertEqual(list((work / "user/home").glob("*/savedata/*")), [])
                challenges.append(challenge)
                with self.assertRaises(FileExistsError):
                    save.prepare(work, fixture)
            self.assertNotEqual(*challenges)

    def test_failure_evidence_counts_entry_only_from_a_valid_prefix(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            (output / "session").mkdir()
            trace = output / "session/startup-audit.jsonl"
            failed = passing_events()[:4] + [event("guest_output", 15, text="save-roundtrip: FAIL search 0x0")]
            trace.write_text("".join(json.dumps(e) + "\n" for e in failed))
            result = {}
            save.collect_failure_evidence(output, result)
            self.assertTrue(result["guest_entry_observed"])
            self.assertIn("FAIL search", result["audit"]["validation_error"])
            trace.write_text("".join(json.dumps(e) + "\n" for e in [event("guest_entry")]))
            result = {}
            save.collect_failure_evidence(output, result)
            self.assertFalse(result["guest_entry_observed"])

    def test_runner_refuses_non_windows_hosts_and_bad_arguments(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            for timeout in (2, 121, float("nan")):
                with self.assertRaises(ValueError):
                    save.run_attempt(engine=output, engine_report=output, fixture=output, supervisor=output,
                                     output=output, timeout=timeout)
            with patch.object(save.sys, "platform", "linux"):
                code, result = save.run_attempt(engine=output, engine_report=output, fixture=output,
                                                supervisor=output, output=output)
            self.assertEqual((code, result["passed"], result["engine_launch_attempted"]), (1, False, False))
            self.assertIn("Windows x86-64", result["error"])
            self.assertTrue((output / "save-result.json").exists())

    def test_psf_round_trips_and_reads_the_engine_encoder_layout(self):
        entries = {"TITLE_ID": "PRTS00001", "TITLE": "Fixture é", "COUNT": -2, "BLOB": b"\x00\x01\x02"}
        blob = psf.write(entries)
        self.assertEqual(blob[:8], b"\0PSF\x01\x01\x00\x00")
        self.assertEqual(psf.read(blob), entries)
        # The pinned engine's encoder keeps insertion order, does not pad the key table
        # and aligns each value to 4 bytes from the start of the file.
        rows = [("SAVEDATA_DIRECTORY", psf.TEXT, b"PS4RTSAVE01\0", 32),
                ("SAVEDATA_LIST_PARAM", psf.INTEGER, (0).to_bytes(4, "little"), 4),
                ("TITLE_ID", psf.TEXT, b"PRTS00001\0", 16)]
        key_table = 20 + 16 * len(rows)
        keys = b"".join(k.encode() + b"\0" for k, *_ in rows)
        data_table = key_table + len(keys)
        data, index, key_offset = bytearray(), bytearray(), 0
        for key, kind, value, maximum in rows:
            while (data_table + len(data)) % 4:
                data.append(0)
            index += struct.pack("<HHIII", key_offset, kind, len(value), maximum, len(data))
            data += value.ljust(maximum, b"\0")
            key_offset += len(key) + 1
        engine_style = (b"\0PSF" + struct.pack("<IIII", 0x101, key_table, data_table, len(rows)) +
                        bytes(index) + keys + bytes(data))
        self.assertEqual(psf.read(engine_style), {"SAVEDATA_DIRECTORY": "PS4RTSAVE01", "SAVEDATA_LIST_PARAM": 0,
                                                  "TITLE_ID": "PRTS00001"})
        for bad in (b"", blob[:19], b"XPSF" + blob[4:], blob[:-8], blob[:4] + b"\x02" + blob[5:]):
            with self.subTest(bad=bad[:8]), self.assertRaises(ValueError):
                psf.read(bad)
        for value in (1.5, True, None):
            with self.assertRaises(ValueError):
                psf.write({"KEY": value})


if __name__ == "__main__":
    unittest.main()
