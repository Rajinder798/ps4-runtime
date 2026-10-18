# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Host policy/ownership tests; no hosted guest or audio-device claim."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import process_audio as audio

HELPER = Path(sys.argv.pop(1))


def report():
    return dict(schema_version=1, status="captured", backend="wasapi-process-loopback", root_pid=42, supervisor_pid=41,
        include_target_tree=True, owned_process_verified=True, default_render_active=True, engine_render_session_active=True,
        root_exited=True, stop_requested=False, sample_format="F32LE", sample_rate=48000, channels=2, frames=48000,
        packets=100, windows_build=26220, endpoint_muted=False, endpoint_volume=1, discontinuities=0, timestamp_errors=0)


class PolicyTests(unittest.TestCase):
    def test_capture_requires_exact_process_filter_format_size_and_termination_evidence(self):
        good = report()
        audio.validate_report(good, 42, 41, 384000)
        for bad in (None, [], "captured"):
            with self.assertRaises(ValueError):
                audio.validate_report(bad, 42, 41, 384000)
        for field, value in (("schema_version",True), ("root_pid",43), ("supervisor_pid",40), ("include_target_tree",False),
                ("owned_process_verified",False), ("default_render_active",False), ("engine_render_session_active",False),
                ("root_exited",False), ("stop_requested",True), ("backend","disk"), ("status","failed"),
                ("sample_rate",44100), ("channels",1), ("sample_format","S16LE"), ("frames",True), ("frames",47999),
                ("windows_build",19045), ("packets",0), ("endpoint_volume",float("nan")), ("endpoint_volume",2),
                ("endpoint_muted",0), ("discontinuities",-1), ("timestamp_errors",None)):
            with self.subTest(field=field), self.assertRaises(ValueError):
                audio.validate_report(dict(good, **{field:value}), 42, 41, 384000)
        for field in good:
            bad = dict(good); del bad[field]
            with self.subTest(missing=field), self.assertRaises(ValueError):
                audio.validate_report(bad, 42, 41, 384000)

    def test_wasapi_environment_is_local_and_does_not_retain_disk_output_hints(self):
        from unittest.mock import patch
        with patch.dict(os.environ, SDL_AUDIO_DISK_OUTPUT_FILE="unrelated.raw", SDL_AUDIO_DISK_TIMESCALE="99"):
            before = dict(os.environ)
            environment = audio.render_environment()
            self.assertEqual(environment["SDL_AUDIO_DRIVER"], "wasapi")
            self.assertNotIn("SDL_AUDIO_DISK_OUTPUT_FILE", environment)
            self.assertNotIn("SDL_AUDIO_DISK_TIMESCALE", environment)
            self.assertEqual(dict(os.environ), before)

    def test_cli_rejects_capture_options_before_creating_output_or_launching(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "attempt"
            command = [sys.executable, str(ROOT / "tools/run_videoout_research.py")]
            for name in ("engine", "engine-report", "fixture", "supervisor"):
                command.extend(["--"+name, str(ROOT / "absent")])
            cases = [("--audio-backend","wasapi"), ("--capture-helper",str(ROOT / "absent")),
                ("--profile","interactive-av","--shutdown","window-close","--audio-backend","wasapi"),
                ("--profile","interactive-av","--shutdown","window-close","--audio-backend","wasapi",
                 "--capture-helper",str(ROOT / "absent"),"--timeout","61")]
            for options in cases:
                with self.subTest(options=options):
                    result = subprocess.run([*command,"--output",str(output),*options],capture_output=True,timeout=10)
                    self.assertEqual(result.returncode,2)
                    self.assertFalse(output.exists())


@unittest.skipUnless(sys.platform == "win32", "Windows native helper ownership tests")
class HelperTests(unittest.TestCase):
    def test_help_and_invalid_arguments_do_not_open_audio(self):
        self.assertEqual(subprocess.run([str(HELPER),"--help"],capture_output=True,timeout=5).returncode,0)
        for arguments in ([],["--exclude-tree"],["--capture","-1","0","engine","output","1000"]):
            with self.subTest(arguments=arguments):
                result = subprocess.run([str(HELPER),*arguments],capture_output=True,timeout=5)
                self.assertEqual(result.returncode,1)
                self.assertIn(b"process-audio-capture:",result.stderr)

    def test_unrelated_process_is_rejected_before_creating_capture_files(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory).resolve()
            # The test Python process is not a child of the nominated supervisor.
            result = subprocess.run([str(HELPER),"--capture",str(os.getpid()),str(os.getpid()),
                str(Path(sys.executable).resolve()),str(output),"1000"],capture_output=True,timeout=5)
            self.assertEqual(result.returncode,1)
            self.assertIn(b"sibling supervisor",result.stderr)
            self.assertEqual(list(output.iterdir()),[])


if __name__ == "__main__":
    unittest.main()
