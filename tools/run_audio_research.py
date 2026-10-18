# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Fixed guest AudioOut -> SDL disk sink research; no hardware playback claim."""
import argparse
import json
import math
import os
from pathlib import Path
import platform
import secrets
import shutil
import subprocess
import sys

import audio_evidence
import run_homebrew_startup as startup

PROFILE = "audio-pattern"
PHASES = tuple(f"audio-pattern: phase={phase} submitted blocks=192" for phase in range(4))


def progress(events):
    result = startup.evaluate(events, PROFILE)
    phases, begun = [], False
    for event in events:
        if event.get("event") != "guest_output":
            continue
        text = event["text"]
        if text == startup.AUDIO_MARKERS[0]:
            begun = True
        elif text in PHASES:
            phase = PHASES.index(text)
            if not begun or phase != len(phases):
                raise ValueError("Duplicate/out-of-order audio phase")
            phases.append(phase)
        elif text == startup.AUDIO_MARKERS[1] and phases != [0, 1, 2, 3]:
            raise ValueError("Audio completion without all submitted phases")
    return dict(**result, phases=phases)


def run_attempt(*, engine, engine_report, fixture, supervisor, output, timeout=30, audio_case="normal", shutdown="terminate"):
    if (not math.isfinite(timeout) or not 5 <= timeout <= 120 or any(output.iterdir()) or
            audio_case not in ("normal", "silence", "swapped") or shutdown not in ("terminate", "window-close")):
        raise ValueError("An empty output and reviewed audio case/timeout are required")
    result = dict(schema_version=1, status="failed", profile=PROFILE, audio_case=audio_case,
        audio_sink_verified=False, hardware_playback_tested=False, guest_entry_observed=False,
        guest_execution_tested=False, engine_launch_attempted=False, host=platform.platform(),
        cpu=platform.processor(), upstream_redistribution_approved=False)
    from window_shutdown import WindowClose
    closing = WindowClose()
    result.update(shutdown=shutdown, window_close_verified=False)
    try:
        if sys.platform != "win32" or platform.machine().lower() not in ("amd64", "x86_64"):
            raise ValueError("Audio research requires Windows x86-64")
        engine, fixture, supervisor = (p.resolve(strict=True) for p in (engine, fixture, supervisor))
        result["build"] = startup.verify_inputs(engine, engine_report.resolve(strict=True), fixture, PROFILE)
        result.update(engine_sha256=startup.digest(engine), fixture_sha256=startup.digest(fixture),
                      supervisor_sha256=startup.digest(supervisor))
        vulkan = shutil.which("vulkaninfo")
        if not vulkan:
            raise ValueError("vulkaninfo is required for this engine's host diagnostics")
        diagnostic = subprocess.run([vulkan, "--summary"], capture_output=True, timeout=10, check=False)
        (output / "vulkan-summary.txt").write_bytes(diagnostic.stdout + diagnostic.stderr)
        if diagnostic.returncode:
            raise ValueError("Vulkan host diagnostic failed")
        work = output / "session"
        startup.prepare_session(work)
        (work / "user/config.json").write_text(json.dumps({"Log":{"filter":"*:info","flush_level":"trace"}}))
        app = work / "app"; app.mkdir()
        staged = app / "audio_pattern.oelf"
        shutil.copyfile(fixture, staged)
        if startup.digest(staged) != result["fixture_sha256"]:
            raise ValueError("Staged fixture mismatch")
        choices, challenge = list(range(4)), []
        for unused in range(4):
            value = secrets.choice(choices); choices.remove(value); challenge.append(value)
        (app / "audio.bin").write_bytes(bytes(challenge + [{"normal":0,"silence":1,"swapped":2}[audio_case]]))
        result["challenge"] = challenge
        trace, pcm = work / "startup-audit.jsonl", work / "sdl-output.raw"
        environment = os.environ.copy()
        environment.update(SDL_AUDIO_DRIVER="disk", SDL_AUDIO_DISK_OUTPUT_FILE=str(pcm),
            SDL_AUDIO_DISK_TIMESCALE="1", SDL_AUDIO_FREQUENCY="48000", SDL_AUDIO_CHANNELS="2", SDL_AUDIO_FORMAT="F32LE")
        result["sink_environment"] = {k:v for k,v in environment.items() if k in
            ("SDL_AUDIO_DRIVER","SDL_AUDIO_DISK_TIMESCALE","SDL_AUDIO_FREQUENCY","SDL_AUDIO_CHANNELS","SDL_AUDIO_FORMAT")}
        command = [engine, "--game", staged, "--ignore-game-patch", "--startup-audit", trace]
        result["command"] = list(map(str, command))
        owner = []
        def poll():
            ready = progress(startup.read_events(trace))["markers_observed"]
            return closing.poll(ready, owner[0], engine) if shutdown == "window-close" else ready
        result["engine_launch_attempted"] = True
        result["transport"] = startup.supervise(supervisor, command, work, timeout,
            poll, environment=environment, on_started=owner.append)
        evidence = progress(startup.read_events(trace, final=True))
        result.update(guest_entry_observed=evidence["guest_entry_observed"], guest_execution_tested=evidence["guest_entry_observed"],
                      phases=evidence["phases"], guest_completed=evidence["markers_observed"])
        expected_reason = "exited" if shutdown == "window-close" else "requested"
        if result["transport"]["reason"] != expected_reason or not evidence["markers_observed"]:
            raise ValueError("Missing qualifying guest audio completion")
        stderr = (work / "stderr.txt").read_text(encoding="utf-8", errors="replace")
        result["audio_analysis"] = audio_evidence.verify(pcm, stderr, challenge)
        if shutdown == "window-close":
            result["window_close"] = closing.verify(result["transport"])
            result["window_close_verified"] = True
        result.update(status="passed", audio_sink_verified=True)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        result["error"] = str(error)
    finally:
        if closing.request is not None:
            result["window_close_request"] = closing.request
        if result["engine_launch_attempted"]:
            try:
                startup.collect_failure_evidence(output, result)
            except (OSError, ValueError) as error:
                result["postmortem_error"] = str(error)
        (output / "audio-result.json").write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    return (0 if result["audio_sink_verified"] else 1), result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("engine","engine-report","fixture","supervisor","output"):
        parser.add_argument("--"+name,type=Path,required=True)
    parser.add_argument("--audio-case",choices=("normal","silence","swapped"),default="normal")
    parser.add_argument("--shutdown",choices=("terminate","window-close"),default="terminate")
    parser.add_argument("--timeout",type=float,default=30)
    args = parser.parse_args()
    if not math.isfinite(args.timeout) or not 5 <= args.timeout <= 120:
        parser.error("--timeout must be finite and between 5 and 120 seconds")
    args.output = args.output.resolve()
    try:
        args.output.mkdir(parents=True,exist_ok=False)
    except OSError as error:
        parser.error(f"--output must be a new writable directory: {error}")
    code,result = run_attempt(**vars(args))
    print(json.dumps(result,indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
