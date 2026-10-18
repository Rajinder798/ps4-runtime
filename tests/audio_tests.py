# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Generated host PCM rejection tests; not guest audio or hardware evidence."""
from array import array
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import audio_evidence as evidence
import run_audio_research as runner
import run_homebrew_startup as startup


def signal(pairs=((750,500),(375,250)), *, swap=False, silence=False, reverse=False):
    # Sines, rather than the guest's square-wave/integer-period implementation.
    if reverse:
        pairs = pairs[::-1]
    samples = array("f", [0.0]) * (evidence.RATE * 2)
    for pair in pairs:
        if swap:
            pair = pair[::-1]
        for frame in range(evidence.RATE):
            samples.extend(0.0 if silence else 0.04 * math.sin(2 * math.pi * hz * frame / evidence.RATE) for hz in pair)
    samples.extend(array("f", [0.0]) * (evidence.RATE * 2))
    return samples


class AudioTests(unittest.TestCase):
    def test_independent_sine_signals_prove_stereo_sequence_and_silence(self):
        result = evidence.analyze(signal(), [0,1,2,3])
        self.assertEqual(result["frames"], 192000)
        self.assertEqual([w["kind"] for w in result["matched_windows"]], ["silence","tone0","tone1","silence"])
        self.assertEqual(result["expected_tone_pairs_hz"], [(750,500),(375,250)])

    def test_silence_swapped_reversed_and_mono_cannot_pass(self):
        mono = signal()
        mono[1::2] = mono[0::2]
        for name, samples in (("silence", signal(silence=True)),("swap",signal(swap=True)),
                              ("reverse",signal(reverse=True)),("mono",mono)):
            with self.subTest(name=name), self.assertRaises(ValueError):
                evidence.analyze(samples, [0,1,2,3])

    def test_missing_silence_wrong_challenge_and_short_tones_rejected(self):
        samples = signal()
        transient = array("f", [0.0]) * len(samples)
        for offset in (96000, 192000):
            transient[offset:offset+4800] = samples[offset:offset+4800]
        for data, challenge in ((samples[96000:], [0,1,2,3]), (samples[:-96000], [0,1,2,3]),
                                (samples,[1,0,2,3]),(samples,[0,0,1,2]),(samples[:100],[0,1,2,3]),(transient,[0,1,2,3])):
            with self.assertRaises(ValueError):
                evidence.analyze(data, challenge)

    def test_pcm_requires_exact_sink_metadata_and_valid_bounded_frames(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sdl-output.raw"
            header = f"You are using the SDL disk i/o audio driver!\nWriting to file [{path}], format=F32LE channels=2 freq=48000."
            with self.assertRaises(ValueError):
                evidence.decode_capture(path,header)
            path.write_bytes(array("f",[0.0,0.0]).tobytes())
            self.assertEqual(len(evidence.decode_capture(path,header)[0]),2)
            for text in ("", header.replace("48000","44100"),header.replace("channels=2","channels=1"),header.replace(str(path),"other.raw")):
                with self.assertRaises(ValueError):
                    evidence.decode_capture(path,text)
            for data in (b"short",array("f",[math.nan,0]).tobytes(),array("f",[math.inf,0]).tobytes(),array("f",[2,0]).tobytes(),
                         bytes(evidence.MAX_PCM_BYTES+8)):
                path.write_bytes(data)
                with self.assertRaises(ValueError):
                    evidence.decode_capture(path,header)

    def test_four_guest_phases_are_ordered_and_failures_reject_success(self):
        events = [dict(schema_version=1,elapsed_us=0,event="configured",strict_imports=True),
                  dict(schema_version=1,elapsed_us=1,event="imports_checked",phase="entry",unresolved_count=0),
                  dict(schema_version=1,elapsed_us=2,event="guest_entry")]
        texts = (startup.AUDIO_MARKERS[0],*runner.PHASES,startup.AUDIO_MARKERS[1])
        events += [dict(schema_version=1,elapsed_us=i+3,event="guest_output",text=text) for i,text in enumerate(texts)]
        self.assertTrue(runner.progress(events)["markers_observed"])
        self.assertFalse(startup.evaluate(events)["markers_observed"])
        for case in ("missing","reordered","failure","unresolved"):
            bad = [dict(e) for e in events]
            if case == "missing": del bad[6]
            elif case == "reordered": bad[4]["text"],bad[5]["text"] = bad[5]["text"],bad[4]["text"]
            elif case == "failure": bad[5]["text"] = "audio-pattern: FAIL output"
            else: bad.append(dict(schema_version=1,elapsed_us=10,event="unresolved",symbol="missing"))
            with self.subTest(case=case), self.assertRaises(ValueError): runner.progress(bad)

    def test_missing_prerequisite_records_no_guest_or_audio_success(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "attempt"
            command = [sys.executable,str(ROOT / "tools/run_audio_research.py")]
            for name in ("engine","engine-report","fixture","supervisor"):
                command.extend(["--"+name,str(output / "absent")])
            result = subprocess.run([*command,"--output",str(output)],capture_output=True,timeout=10)
            self.assertEqual(result.returncode,1)
            report = json.loads((output / "audio-result.json").read_text())
            self.assertFalse(report["engine_launch_attempted"])
            self.assertFalse(report["guest_entry_observed"])
            self.assertFalse(report["audio_sink_verified"])


if __name__ == "__main__":
    unittest.main()
