# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Portable evidence rejection tests; generated PNGs are not guest rendering."""
import binascii
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import run_homebrew_startup as startup
import run_videoout_research as runner
import videoout_evidence as image


def chunk(kind, payload):
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", binascii.crc32(kind + payload))


def png(raw, header=None):
    header = header or struct.pack(">IIBBBBB", image.WIDTH, image.HEIGHT, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def unfiltered(pixels):
    stride = image.WIDTH * 4
    return b"".join(b"\0" + pixels[start:start + stride] for start in range(0, len(pixels), stride))


def events():
    records = [("configured", dict(strict_imports=True)),
               ("imports_checked", dict(phase="entry", unresolved_count=0)), ("guest_entry", {})]
    records += [("guest_output", dict(text=text)) for text in
                (startup.VIDEO_MARKERS[0], *runner.READY, startup.VIDEO_MARKERS[1])]
    return [dict(schema_version=1, elapsed_us=i, event=kind, **fields) for i, (kind, fields) in enumerate(records)]


class VideoOutTests(unittest.TestCase):
    def test_pad_observations_reject_missing_wrong_disconnected_and_stale_states(self):
        records = [(0, 1, 100), (0x4000, 1, 200), (0, 1, 300)]
        def encode(values):
            return b"".join(struct.pack("<IB3xQ", *value) for value in values)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input-result.bin"
            with self.assertRaises(ValueError):
                runner.verify_pad_observations(path)
            path.write_bytes(encode(records))
            self.assertEqual(runner.verify_pad_observations(path)["records"][1]["buttons"], 0x4000)
            cases = [encode(records)[:-1], encode(records) + b"x", encode([(0,1,100)] * 3)]
            for index, replacement in ((0, (0x4000,1,100)), (1, (0x2000,1,200)),
                    (1, (0x4000,0,200)), (1, (0x4000,1,0)), (2, (0x4000,1,300)), (2, (0,1,200))):
                altered = list(records)
                altered[index] = replacement
                cases.append(encode(altered))
            reserved = bytearray(encode(records)); reserved[5] = 1
            cases.append(bytes(reserved))
            for index, data in enumerate(cases):
                path.write_bytes(data)
                with self.subTest(index=index), self.assertRaises(ValueError):
                    runner.verify_pad_observations(path)

    def test_pad_requires_ordered_neutral_cross_release_markers(self):
        valid = events()[:3]
        texts = (startup.PAD_MARKERS[0], *runner.PAD_READY, startup.PAD_MARKERS[1])
        valid += [dict(schema_version=1, elapsed_us=i+3, event="guest_output", text=text) for i,text in enumerate(texts)]
        self.assertTrue(runner.progress(valid, runner.PAD_PROFILE)["markers_observed"])
        self.assertFalse(runner.progress(valid)["markers_observed"])
        for case in ("missing-release", "wrong-button", "duplicate", "fail", "unresolved"):
            bad = [dict(e) for e in valid]
            if case == "missing-release":
                del bad[6]
            elif case == "wrong-button":
                bad[5]["text"] = "pad-videoout: state=1 buttons=8192 ready"
            elif case == "duplicate":
                bad[6]["text"] = runner.PAD_READY[1]
            elif case == "fail":
                bad[6]["text"] = "pad-videoout: FAIL input timeout"
            else:
                bad.append(dict(schema_version=1,elapsed_us=8,event="unresolved",symbol="missing"))
            with self.subTest(case=case), self.assertRaises(ValueError):
                runner.progress(bad, runner.PAD_PROFILE)

    def test_native_transport_rejects_unreviewed_keys_and_implicit_boolean(self):
        from videoout_capture import send_key
        for key, down in (("arbitrary", True), ("n", True), ("cross", 1), ("circle", None)):
            with self.subTest(key=key, down=down), self.assertRaises(ValueError):
                send_key(0, ROOT / "absent", key, down)

    def test_input_negative_option_is_not_silently_ignored_by_video_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "attempt"
            command = [sys.executable, str(ROOT / "tools/run_videoout_research.py")]
            for name in ("engine", "engine-report", "fixture", "supervisor"):
                command.extend(["--" + name, str(ROOT / "absent")])
            result = subprocess.run([*command, "--output", str(output), "--input-case", "absent"], capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 2)
            self.assertFalse(output.exists())

    def test_missing_prerequisite_records_no_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            command = [sys.executable, str(ROOT / "tools/run_videoout_research.py")]
            for name in ("engine", "engine-report", "fixture", "supervisor"):
                command.extend(["--" + name, str(path / "absent")])
            result = subprocess.run([*command, "--output", str(path / "attempt")], capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 1)
            report = json.loads((path / "attempt/videoout-result.json").read_text())
            self.assertFalse(report["engine_launch_attempted"])
            self.assertFalse(report["guest_entry_observed"])
            self.assertFalse(report["graphics_verified"])

    def test_pixel_oracle_has_fixed_boundaries_orientation_and_phase(self):
        palette = bytes([1, 2, 4, 7])
        pixels = image.expected_pixels(palette, 0)
        def at(x, y):
            offset = (y * image.WIDTH + x) * 4
            return pixels[offset:offset + 4]
        self.assertEqual(at(0, 0), bytes([255, 0, 0, 255]))
        self.assertEqual(at(79, 44), at(0, 0))
        self.assertEqual(at(80, 0), bytes([0, 255, 0, 255]))
        self.assertEqual(at(0, 45), at(80, 0))
        self.assertEqual(at(160, 0), bytes([0, 0, 255, 255]))
        self.assertEqual(at(639, 359), at(160, 0))
        self.assertNotEqual(pixels, image.expected_pixels(palette, 1))
        for challenge, phase in ((b"", 0), (b"\0\0\1\2", 0), (b"\0\1\2\10", 0), (palette, 2)):
            with self.subTest(challenge=challenge, phase=phase), self.assertRaises(ValueError):
                image.expected_pixels(challenge, phase)

    def test_all_five_png_filters_using_known_constant_vectors(self):
        pixel = bytes([17, 99, 211, 255])
        row = pixel * image.WIDTH
        zero = bytes(len(row))
        half = bytes(v - v // 2 for v in pixel)
        for mode in range(5):
            if mode == 0:
                first = following = row
            elif mode == 1:
                first = following = pixel + zero[4:]
            elif mode == 2:
                first, following = row, zero
            elif mode == 3:
                first, following = pixel + half * (image.WIDTH - 1), half + zero[4:]
            else:
                first, following = pixel + zero[4:], zero
            raw = bytes([mode]) + first + (bytes([mode]) + following) * (image.HEIGHT - 1)
            with self.subTest(mode=mode):
                self.assertEqual(image.decode_png(png(raw)), row * image.HEIGHT)

    def test_png_integrity_format_and_decompression_limits(self):
        raw = (b"\0" + bytes(image.WIDTH * 4)) * image.HEIGHT
        good = png(raw)
        bad_crc = bytearray(good)
        bad_crc[-1] ^= 1
        cases = [b"", good[:-1], good + b"trailing", bytes(bad_crc), good[:20],
                 b"x" * (image.MAX_PNG_BYTES + 1), png(raw[:-1]), png(raw + b"extra"),
                 png(bytes(8 * len(raw))), png(b"\5" + raw[1:]),
                 png(raw, struct.pack(">IIBBBBB", 2**31, 360, 8, 6, 0, 0, 0)),
                 png(raw, struct.pack(">IIBBBBB", 640, 360, 8, 2, 0, 0, 0)),
                 good[:33] + chunk(b"NOPE", b"") + good[33:],
                 good[:33] + chunk(b"IHDR", good[16:29]) + good[33:],
                 good[:33] + chunk(b"IDAT", b"not zlib") + chunk(b"IEND", b"")]
        for index, data in enumerate(cases):
            with self.subTest(index=index), self.assertRaises(ValueError):
                image.decode_png(data)

    def test_valid_png_wrong_pixel_phase_or_challenge_cannot_pass(self):
        challenge = bytes([1, 2, 4, 7])
        pixels = image.expected_pixels(challenge, 0)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "game.png"
            path.write_bytes(png(unfiltered(pixels)))
            result = image.verify_capture(path, challenge, 0)
            self.assertEqual(result["pixels_verified"], 230400)
            for palette, phase in ((challenge, 1), (bytes([0, 2, 4, 7]), 0)):
                with self.assertRaises(image.CaptureMismatch):
                    image.verify_capture(path, palette, phase)
            altered = bytearray(pixels)
            altered[-2] ^= 1
            path.write_bytes(png(unfiltered(altered)))
            with self.assertRaises(image.CaptureMismatch):
                image.verify_capture(path, challenge, 0)

    def test_strict_guest_phase_order_and_failure_rejection(self):
        valid = events()
        self.assertTrue(runner.progress(valid)["markers_observed"])
        self.assertFalse(startup.evaluate(valid)["markers_observed"])
        for case in ("order", "duplicate", "fail", "no-entry", "no-begin", "unresolved", "missing-phase"):
            bad = [dict(e) for e in valid]
            if case == "order":
                bad[4]["text"], bad[5]["text"] = bad[5]["text"], bad[4]["text"]
            elif case == "duplicate":
                bad[5]["text"] = bad[4]["text"]
            elif case == "fail":
                bad[5]["text"] = "videoout-pattern: FAIL submit"
            elif case == "no-entry":
                del bad[2]
            elif case == "no-begin":
                del bad[3]
            elif case == "unresolved":
                bad.append(dict(schema_version=1, elapsed_us=7, event="unresolved", symbol="missing"))
            else:
                del bad[5]
            with self.subTest(case=case), self.assertRaises(ValueError):
                runner.progress(bad)


if __name__ == "__main__":
    unittest.main()
