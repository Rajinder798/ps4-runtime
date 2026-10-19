# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later

"""Portable live evidence rejection; generated signals/images are host tests only."""
from array import array
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import live_av_evidence as live
from videoout_tests import png, unfiltered


def events(buttons=(0, 0x4000, 0, 0x4000, 0)):
    result = [dict(schema_version=1, elapsed_us=0, event="configured", strict_imports=True),
              dict(schema_version=1, elapsed_us=1, event="imports_checked", phase="entry", unresolved_count=0),
              dict(schema_version=1, elapsed_us=2, event="guest_entry")]
    texts = [live.BEGIN, live.READY]
    texts += [f"live-av: sample={i} buttons={b} timestamp={100+i} flip={10+i*30} audio_blocks={2+i*24}"
              for i, b in enumerate(buttons)]
    return result + [dict(schema_version=1, elapsed_us=3+i, event="guest_output", text=t) for i, t in enumerate(texts)]


def pcm(kinds, swapped=False):
    result = array("f")
    for tone in kinds:
        if not tone:
            result.extend(array("f", [0]) * (48000 * 2))
        else:
            for i in range(48000):
                pair = [2000 / 32768 if i % period < period // 2 else -2000 / 32768 for period in (64, 96)]
                result.extend(pair[::-1] if swapped else pair)
    return result


class LiveEvidenceTests(unittest.TestCase):
    def test_strict_live_trace_never_claims_finite_guest_completion(self):
        state = live.progress(events())
        self.assertTrue(state["running_observed"])
        self.assertTrue(state["guest_entry_observed"])
        self.assertFalse(state["guest_completed"])
        for case in ("order", "unresolved", "duplicate", "failure", "old-file", "timestamp", "flip"):
            bad = [dict(e) for e in events()]
            if case == "order": bad[3], bad[4] = bad[4], bad[3]; bad[3]["elapsed_us"], bad[4]["elapsed_us"] = 3, 4
            elif case == "unresolved": bad.append(dict(schema_version=1, elapsed_us=99, event="unresolved", symbol="missing"))
            elif case == "duplicate": bad[6]["text"] = bad[5]["text"]
            elif case == "failure": bad[6]["text"] = "live-av: FAIL pad read"
            elif case == "old-file": bad[6]["text"] = bad[6]["text"].replace("sample=1", "sample=2")
            elif case == "timestamp": bad[6]["text"] = bad[6]["text"].replace("timestamp=101", "timestamp=100")
            else: bad[6]["text"] = bad[6]["text"].replace("flip=40", "flip=10")
            with self.subTest(case=case), self.assertRaises(ValueError): live.progress(bad)

    def test_guest_file_two_cycles_and_each_unique_image_are_required(self):
        samples = live.progress(events())["samples"]
        captures = [dict(sequence=i, image_phase=i % 2) for i in range(5)]
        data = b"".join(struct.pack("<IIQQ", s["sequence"], s["buttons"], s["timestamp"], s["flip"]) for s in samples)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "input.bin"
            path.write_bytes(data)
            self.assertTrue(live.verify_input(path, samples, captures)["two_cycles_verified"])
            for bad in (data[:-1], data + b"x", bytes([1]) + data[1:]):
                path.write_bytes(bad)
                with self.assertRaises(ValueError): live.verify_input(path, samples, captures)
            path.write_bytes(data)
            with self.assertRaises(ValueError): live.verify_input(path, samples, captures[:-1])
            wrong = live.progress(events((0, 0x2000, 0, 0x2000, 0)))["samples"]
            path.write_bytes(b"".join(struct.pack("<IIQQ", s["sequence"], s["buttons"], s["timestamp"], s["flip"]) for s in wrong))
            with self.assertRaises(ValueError): live.verify_input(path, wrong, captures)

    def test_png_binds_challenge_buttons_and_exact_observation_not_repeated_state(self):
        palette = bytes([1, 2, 4, 7])
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "frame.png"
            path.write_bytes(png(unfiltered(live.expected_pixels(palette, 0, 0))))
            self.assertEqual(live.verify_image(path, palette, 0, 0)["pixels_verified"], 230400)
            for challenge, sequence, buttons in ((palette, 2, 0), (palette, 0, 0x4000), (bytes([0, 2, 4, 7]), 0, 0)):
                with self.subTest(sequence=sequence, buttons=buttons), self.assertRaises(ValueError):
                    live.verify_image(path, challenge, sequence, buttons)

    def test_pcm_requires_two_sustained_cycles_and_tone_when_closed_pressed(self):
        challenge = [0, 1, 2, 3]
        result = live.analyze_audio(pcm([0, 1, 0, 1, 0]), challenge, False)
        self.assertEqual(len(result["matched_windows"]), 5)
        self.assertEqual(len(live.analyze_audio(pcm([0, 1, 0, 1, 0, 1]), challenge, True)["matched_windows"]), 6)
        for kinds, swapped, pressed in (([0, 1, 0], False, False), ([0, 0, 0, 0, 0], False, False),
                                        ([0, 1, 0, 1, 0], True, False), ([0, 1, 0, 1, 0], False, True)):
            with self.subTest(kinds=kinds, swapped=swapped, pressed=pressed), self.assertRaises(ValueError):
                live.analyze_audio(pcm(kinds, swapped), challenge, pressed)

    def test_locked_source_and_cli_budget_rejection(self):
        contract = json.loads((ROOT / "config/live-av.json").read_text())
        self.assertEqual(hashlib.sha256((ROOT / "research/homebrew/live_av/main.cpp").read_bytes()).hexdigest(), contract["source_sha256"])
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "unused"
            common = [sys.executable, str(ROOT / "tools/run_live_av.py")]
            for name in ("engine", "engine-report", "fixture", "supervisor", "capture-helper"):
                common.extend(["--" + name, str(output)])
            for budget in ("7", "31", "nan", "inf"):
                p = subprocess.run([*common, "--output", str(output), "--timeout", budget], capture_output=True, timeout=10)
                self.assertEqual(p.returncode, 2)
                self.assertFalse(output.exists())
            output.mkdir()
            marker = output / "existing.txt"
            marker.write_bytes(b"preserve")
            p = subprocess.run([*common, "--output", str(output)], capture_output=True, timeout=10)
            self.assertEqual(p.returncode, 2)
            self.assertIn(b"--output must be a new writable directory", p.stderr)
            self.assertEqual(marker.read_bytes(), b"preserve")
            self.assertEqual(list(output.iterdir()), [marker])

    def test_saved_volume_qualification_requires_fixed_gain_and_two_cycles_without_changing_old_oracle(self):
        full=pcm([0,1,0,1,0]);half=array("f",(x*0.5 for x in full));mute=array("f",[0])*len(full)
        challenge=[0,1,2,3]
        self.assertTrue(live.analyze_session_volume(half,challenge,50)["two_cycles_verified"])
        self.assertFalse(live.analyze_session_volume(mute,challenge,0)["tone_verified"])
        for data,percent in ((full,50),(half,100),(full,0),(pcm([0,1,0]),100)):
            with self.subTest(percent=percent),self.assertRaises(ValueError):
                live.analyze_session_volume(data,challenge,percent)
        with self.assertRaises(ValueError):
            live.analyze_audio(half,challenge,False)


if __name__ == "__main__":
    unittest.main()
