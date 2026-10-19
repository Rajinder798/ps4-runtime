# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Owned-engine Windows render-path evidence, separate from SDL disk capture."""
import json
import math
import os
from pathlib import Path
import subprocess
import time

import audio_evidence
import run_homebrew_startup as startup


def render_environment():
    environment = os.environ.copy()
    for key in ("SDL_AUDIO_DISK_OUTPUT_FILE", "SDL_AUDIO_DISK_TIMESCALE"):
        environment.pop(key, None)
    environment.update(SDL_AUDIO_DRIVER="wasapi", SDL_AUDIO_FREQUENCY="48000",
                       SDL_AUDIO_CHANNELS="2", SDL_AUDIO_FORMAT="F32LE")
    return environment


def validate_report(report, root_pid, supervisor_pid, pcm_bytes):
    if (not isinstance(report, dict) or type(report.get("schema_version")) is not int or report["schema_version"] != 1 or report.get("status") != "captured" or
            report.get("backend") != "wasapi-process-loopback" or
            type(report.get("root_pid")) is not int or report["root_pid"] != root_pid or
            type(report.get("supervisor_pid")) is not int or report["supervisor_pid"] != supervisor_pid or
            report.get("sample_format") != "F32LE" or report.get("sample_rate") != 48000 or report.get("channels") != 2 or
            type(report.get("frames")) is not int or report["frames"] <= 0 or report["frames"] * 8 != pcm_bytes or
            type(report.get("packets")) is not int or report["packets"] <= 0 or
            type(report.get("windows_build")) is not int or report["windows_build"] < 20348 or
            any(report.get(key) is not True for key in ("include_target_tree", "owned_process_verified",
                "default_render_active", "engine_render_session_active", "root_exited")) or
            report.get("stop_requested") is not False):
        raise ValueError("Missing exact owned-process Windows render capture evidence")
    if (type(report.get("endpoint_muted")) is not bool or type(report.get("endpoint_volume")) not in (int, float) or
            not math.isfinite(report["endpoint_volume"]) or not 0 <= report["endpoint_volume"] <= 1 or
            any(type(report.get(k)) is not int or report[k] < 0 for k in ("discontinuities", "timestamp_errors"))):
        raise ValueError("Invalid Windows capture diagnostics")


class ProcessCapture:
    def __init__(self, helper, work, timeout):
        self.helper = Path(helper).resolve(strict=True)
        self.output = work / "wasapi-capture"
        self.output.mkdir()
        self.timeout = timeout
        self.process = self.errors = self.supervisor_pid = self.root_pid = self.ready_at = None
        self.result = dict(helper_sha256=startup.digest(self.helper), helper_exit_confirmed=False, helper_forced_termination=False)
        probe = subprocess.run([str(self.helper), "--preflight"], capture_output=True, text=True, timeout=10,
                               **startup.background_process_options())
        if probe.returncode or probe.stderr:
            raise ValueError("Windows render preflight failed: " + probe.stderr.strip())
        self.result["preflight"] = json.loads(probe.stdout)
        if (not isinstance(self.result["preflight"], dict) or self.result["preflight"].get("status") != "available" or
                self.result["preflight"].get("default_render_active") is not True):
            raise ValueError("Active Windows default render endpoint required")

    def ready(self, supervisor_pid, engine):
        if self.process is None:
            from videoout_capture import _owned_window
            self.root_pid = _owned_window(supervisor_pid, engine)[2]
            self.supervisor_pid = supervisor_pid
            self.errors = (self.output.parent / "capture-helper-stderr.txt").open("wb")
            self.process = subprocess.Popen([str(self.helper), "--capture", str(supervisor_pid), str(self.root_pid),
                str(engine), str(self.output), str(round(self.timeout * 1000))], stdout=subprocess.DEVNULL, stderr=self.errors,
                **startup.background_process_options())
            self.began = time.monotonic()
        if self.process.poll() is not None:
            raise ValueError("Process capture helper exited before guest completion: " + self.error_text())
        ready = self.output / "ready.json"
        if ready.exists():
            try:
                report = json.loads(ready.read_text())
            except json.JSONDecodeError:
                report = {}
            if isinstance(report, dict) and report.get("ready") is True and report.get("root_pid") == self.root_pid and report.get("schema_version") == 1:
                if self.ready_at is None:
                    self.ready_at = time.monotonic()
                # Hold initial neutral output long enough for four signal windows.
                return time.monotonic() - self.ready_at >= 0.6
        if time.monotonic() - self.began > 8:
            raise ValueError("Timed out waiting for owned-process render capture readiness")
        return False

    def error_text(self):
        return (self.output.parent / "capture-helper-stderr.txt").read_text(errors="replace").strip()

    def close(self):
        if self.process is not None:
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                (self.output / "stop.request").touch(exist_ok=True)
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.result["helper_forced_termination"] = True
                    self.process.kill()
                    self.process.wait(timeout=5)
            self.result.update(helper_exit_confirmed=True, helper_exit_code=self.process.returncode)
            report = self.output / "capture.json"
            if report.exists():
                try:
                    self.result["capture"] = json.loads(report.read_text())
                except (OSError, ValueError) as error:
                    self.result["capture_read_error"] = str(error)
            if self.error_text():
                self.result["error"] = self.error_text()
        if self.errors is not None:
            self.errors.close()
        return self.result

    def decode(self, transport):
        """Read samples only after exact ownership, format and cleanup checks."""
        result = self.close()
        if (result.get("helper_exit_code") != 0 or result["helper_forced_termination"] or
                self.root_pid != transport.get("root_pid")):
            raise ValueError("Windows process capture helper did not complete normally: " + result.get("error", ""))
        path = self.output / "wasapi-output.raw"
        validate_report(result.get("capture", {}), self.root_pid, self.supervisor_pid, path.stat().st_size)
        return audio_evidence.decode_pcm(path)

    def verify(self, transport, challenge, volume_percent=None):
        samples, checksum = self.decode(transport)
        analysis = (audio_evidence.analyze_interaction(samples, challenge) if volume_percent is None else
                    audio_evidence.analyze_volume(samples, challenge, volume_percent))
        return dict(**analysis, pcm_sha256=checksum)
