# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later

"""Bounded user-controlled live AV research, without scripted gameplay input."""
import argparse
import json
import math
from pathlib import Path
import platform
import secrets
import shutil
import subprocess
import sys
import time

import live_av_evidence as evidence
import run_homebrew_startup as startup
from process_audio import ProcessCapture, render_environment
from videoout_evidence import CaptureMismatch


def run_attempt(*, engine, engine_report, fixture, supervisor, capture_helper, output, timeout=30,
                audio_case="normal", palette_case="valid"):
    if (type(timeout) not in (int, float) or not math.isfinite(timeout) or not 8 <= timeout <= 30 or
            any(output.iterdir()) or audio_case not in ("normal", "silence", "swapped") or
            palette_case not in ("valid", "missing")):
        raise ValueError("Fresh output, an 8–30 second budget and reviewed cases are required")
    result = dict(schema_version=1, profile="live-av", status="failed", guest_entry_observed=False,
                  engine_launch_attempted=False, guest_execution_tested=False, guest_completed=False,
                  running_observed=False, graphics_verified=False, input_verified=False,
                  windows_render_verified=False, active_guest_close_verified=False, captures=[],
                  input_source="external_keyboard", automated_gameplay_input_sent=False,
                  hardware_acoustic_output_tested=False, upstream_redistribution_approved=False,
                  timeout_seconds=timeout, audio_case=audio_case, palette_case=palette_case)
    capture = None
    try:
        if sys.platform != "win32" or platform.machine().lower() not in ("amd64", "x86_64"):
            raise ValueError("Live AV research requires Windows x86-64")
        engine, engine_report, fixture, supervisor = [p.resolve(strict=True) for p in
                                                     (engine, engine_report, fixture, supervisor)]
        result["build"] = startup.verify_inputs(engine, engine_report, fixture, "live-av")
        result.update(engine_sha256=startup.digest(engine), fixture_sha256=startup.digest(fixture),
                      supervisor_sha256=startup.digest(supervisor), host=platform.platform(), cpu=platform.processor())
        vulkan = shutil.which("vulkaninfo")
        if vulkan is None:
            raise ValueError("vulkaninfo is required to record the graphics host")
        diagnostic = subprocess.run([vulkan, "--summary"], capture_output=True, timeout=10,
                                    **startup.background_process_options())
        (output / "vulkan-summary.txt").write_bytes(diagnostic.stdout + diagnostic.stderr)
        if diagnostic.returncode:
            raise ValueError("Vulkan diagnostic failed")
        work = output / "session"
        startup.prepare_session(work)
        (work / "user/config.json").write_text(json.dumps(dict(Log=dict(filter="*:info", flush_level="trace"),
                                                             General=dict(volume_slider=100))))
        app = work / "app"
        app.mkdir()
        staged = app / "live_av.oelf"
        shutil.copyfile(fixture, staged)
        if startup.digest(staged) != result["fixture_sha256"]:
            raise ValueError("Staged live fixture changed")
        palette = secrets.SystemRandom().sample(range(8), 4)
        challenge = secrets.SystemRandom().sample(range(4), 4)
        if palette_case == "valid":
            (app / "palette.bin").write_bytes(bytes(palette))
        (app / "audio.bin").write_bytes(bytes(challenge + [{"normal": 0, "silence": 1, "swapped": 2}[audio_case]]))
        result.update(palette=palette, audio_challenge=challenge)
        capture = ProcessCapture(capture_helper, work, timeout)
        trace = work / "startup-audit.jsonl"
        command = [engine, "--game", staged, "--ignore-game-patch", "--startup-audit", trace]
        result["command"] = list(map(str, command))
        owner, consumed, qualified = [], set(), set()
        request_time, requested_sequence = 0.0, None

        def publish():
            temporary = output / "live-status.tmp"
            temporary.write_text(json.dumps(dict(schema_version=1, supervisor_pid=owner[0],
                root_pid=capture.root_pid, captures=result["captures"],
                render_capture_ready=capture.ready_at is not None)))
            temporary.replace(output / "live-status.json")

        def started(pid):
            owner.append(pid)
            publish()

        def poll():
            nonlocal request_time, requested_sequence
            state = evidence.progress(startup.read_events(trace))
            result.update({k: state[k] for k in ("guest_entry_observed", "running_observed")})
            if not state["running_observed"] or not capture.ready(owner[0], engine):
                return False
            latest = state["samples"][-1]
            sequence = latest["sequence"]
            if sequence in qualified:
                return False
            if requested_sequence != sequence or time.monotonic() - request_time > 0.4:
                from videoout_capture import request_screenshot
                request_screenshot(owner[0], engine)
                request_time, requested_sequence = time.monotonic(), sequence
            for path in sorted(set((work / "user/screenshots").glob("*.png")) - consumed):
                try:
                    image = evidence.verify_image(path, bytes(palette), sequence, latest["buttons"])
                except CaptureMismatch:
                    consumed.add(path)
                    continue
                except ValueError:
                    # Live input may change before readback completes. A stale
                    # or partial image never qualifies; retry the latest state.
                    if path.stat().st_size > 4 * 1024 * 1024:
                        raise ValueError("Live screenshot exceeds size limit")
                    continue
                consumed.add(path)
                qualified.add(sequence)
                image["path"] = str(path.relative_to(output))
                result["captures"].append(image)
                publish()
                break
            return False  # Only the external window close ends a successful session.

        result["engine_launch_attempted"] = True
        result["transport"] = startup.supervise(supervisor, command, work, timeout, poll,
            on_started=started, environment=render_environment())
        transport = result["transport"]
        state = evidence.progress(startup.read_events(trace, final=True))
        result.update(state)
        result["guest_execution_tested"] = state["guest_entry_observed"]
        if (transport["reason"] != "exited" or transport["exit_code"] != 0 or transport["forced_termination"] or
                transport["active_before_cleanup"] != 0 or not transport["tree_cleanup"] or not state["running_observed"]):
            raise ValueError("Live guest did not close normally with an independently empty process tree")
        result["input_analysis"] = evidence.verify_input(work / "user/data/live-input.bin", state["samples"], result["captures"])
        result.update(graphics_verified=True, input_verified=True)
        samples, checksum = capture.decode(transport)
        result["audio_analysis"] = dict(**evidence.analyze_audio(samples, challenge,
            result["input_analysis"]["pressed_at_close"]), pcm_sha256=checksum)
        result.update(status="passed", windows_render_verified=True, active_guest_close_verified=True)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        result["error"] = str(error)
    finally:
        if capture is not None:
            result["process_capture"] = capture.close()
        if result["engine_launch_attempted"]:
            try:
                work = output / "session"
                if (work / "supervisor.json").exists():
                    result["transport"] = json.loads((work / "supervisor.json").read_text())
                events = startup.read_events(work / "startup-audit.jsonl", final=True)
                result["audit"] = dict(sha256=startup.digest(work / "startup-audit.jsonl"), event_count=len(events),
                    unresolved=[e for e in events if e.get("event") == "unresolved"])
                # Preserve a validated guest-entry prefix even after a later failure.
                for i, event in enumerate(events):
                    if event["event"] == "guest_entry":
                        result["guest_entry_observed"] = startup.evaluate(events[:i + 1])["guest_entry_observed"]
                        result["guest_execution_tested"] = result["guest_entry_observed"]
                        break
            except (OSError, ValueError) as error:
                result["postmortem_error"] = str(error)
        (output / "live-result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return (0 if result["status"] == "passed" else 1), result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("engine", "engine-report", "fixture", "supervisor", "capture-helper", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=30)
    args = parser.parse_args()
    if not math.isfinite(args.timeout) or not 8 <= args.timeout <= 30:
        parser.error("--timeout must be between 8 and 30 seconds")
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    print("Focus the live window. Hold N for a second, release for a second; repeat twice, then close the window.", flush=True)
    code, result = run_attempt(**vars(args))
    print(json.dumps(result, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
