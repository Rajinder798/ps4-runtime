# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Independent generated amplitude/CLI rejection checks, without guest claims."""
from array import array
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import audio_evidence as evidence


def signal(percent, *, swap=False):
    samples = array("f", [0]) * (evidence.RATE * 2)
    # Independent sine oracle: sqrt(2) converts desired RMS to sine amplitude.
    amplitude = math.sqrt(2) * (2000 / 32768) * percent / 100
    frequencies = (500, 750) if swap else (750, 500)
    for frame in range(evidence.RATE):
        samples.extend(amplitude * math.sin(2 * math.pi * hz * frame / evidence.RATE) for hz in frequencies)
    samples.extend(array("f", [0]) * (evidence.RATE * 2))
    return samples


class VolumeTests(unittest.TestCase):
    def test_known_rms_at_each_nonzero_level_and_wrong_gain_rejection(self):
        # Generate signs from trigonometry, independently of guest period/modulo
        # code, to obtain the fixture's known square-wave RMS and peak.
        for percent in (50, 100):
            amplitude = (2000 / 32768) * percent / 100
            samples = array("f", [0]) * (evidence.RATE * 2)
            for frame in range(evidence.RATE):
                samples.extend(amplitude if math.sin(2 * math.pi * hz * (frame + 0.25) / evidence.RATE) > 0 else -amplitude
                               for hz in (750, 500))
            samples.extend(array("f", [0]) * (evidence.RATE * 2))
            # A valid tone window can straddle its onset. The volume oracle
            # must find four later full-amplitude windows with the same bound.
            onset = 2 * evidence.RATE
            samples[onset:onset+2000] = array("f", [0]) * 2000
            result = evidence.analyze_volume(samples, [0, 1, 2, 3], percent)
            self.assertTrue(result["tone_verified"])
            self.assertAlmostEqual(result["expected_rms"], amplitude)
            with self.assertRaisesRegex(ValueError, "amplitude"):
                evidence.analyze_volume(samples, [0, 1, 2, 3], 150 - percent)
        # Correct fundamental alone cannot compensate for a wrong amplitude.
        with self.assertRaises(ValueError):
            evidence.analyze_volume(signal(100), [0, 1, 2, 3], 50)

    def test_mute_requires_entire_capture_silent_and_finite(self):
        samples = signal(0)
        result = evidence.analyze_volume(samples, [0, 1, 2, 3], 0)
        self.assertTrue(result["muted"])
        self.assertFalse(result["tone_verified"])
        for value in (0.001, math.nan, math.inf):
            bad = array("f", samples); bad[-1] = value
            with self.assertRaises(ValueError):
                evidence.analyze_volume(bad, [0, 1, 2, 3], 0)
        with self.assertRaises(ValueError):
            evidence.analyze_volume(samples, [0, 1, 2, 3], 50)

    def test_invalid_levels_challenges_bounds_and_wrong_channels_reject(self):
        for percent in (True, False, 50.0, -1, 1, 101, "50", None):
            with self.assertRaises(ValueError):
                evidence.analyze_volume(signal(0), [0, 1, 2, 3], percent)
        for samples, challenge in ((signal(50, swap=True), [0, 1, 2, 3]),
                                   (signal(0), [0, 0, 1, 2]), (array("f", [0]) * 10, [0, 1, 2, 3])):
            with self.assertRaises(ValueError):
                evidence.analyze_volume(samples, challenge, 50)

    def test_cli_rejects_unsupported_scope_and_levels_before_output_or_launch(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "attempt"
            command = [sys.executable, str(ROOT / "tools/run_videoout_research.py")]
            for name in ("engine", "engine-report", "fixture", "supervisor"):
                command.extend(["--" + name, str(ROOT / "absent")])
            for options in (("--volume-percent", "50"),
                            ("--profile", "interactive-av", "--shutdown", "window-close", "--volume-percent", "101"),
                            ("--profile", "interactive-av", "--shutdown", "window-close", "--volume-percent", "50.0")):
                result = subprocess.run([*command, "--output", str(output), *options], capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 2)
                self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
