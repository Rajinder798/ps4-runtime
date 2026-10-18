# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Bounded fixed-fixture VideoOut/Vulkan readback research; not a game launcher."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import platform
import secrets
import shutil
import subprocess
import sys
import time

import run_homebrew_startup as startup
from videoout_evidence import CaptureMismatch, verify_capture

PROFILE = "videoout-pattern"
READY = ("videoout-pattern: phase=0 ready", "videoout-pattern: phase=1 ready")


def progress(events):
    result = startup.evaluate(events, PROFILE)
    phases, begun = [], False
    for event in events:
        if event.get("event") != "guest_output":
            continue
        text = event["text"]
        if text == startup.VIDEO_MARKERS[0]:
            begun = True
        elif text in READY:
            phase = READY.index(text)
            if not begun or phase != len(phases):
                raise ValueError("Duplicate/out-of-order VideoOut phase")
            phases.append(phase)
        elif text == startup.VIDEO_MARKERS[1] and phases != [0, 1]:
            raise ValueError("VideoOut completion without both phases")
    return dict(**result, phases=phases)


def run_attempt(*, engine, engine_report, fixture, supervisor, output, timeout=45, palette_case="valid"):
    if (not math.isfinite(timeout) or not 5 <= timeout <= 120 or any(output.iterdir()) or
            palette_case not in ("valid", "missing", "truncated")):
        raise ValueError("An empty output directory, valid timeout and palette case are required")
    result = dict(schema_version=1, status="failed", profile=PROFILE, graphics_verified=False,
        guest_execution_tested=False, guest_entry_observed=False, engine_launch_attempted=False,
        host=platform.platform(), cpu=platform.processor(), timeout_seconds=timeout,
        palette_case=palette_case, captures=[], upstream_redistribution_approved=False)
    try:
        if sys.platform != "win32" or platform.machine().lower() not in ("amd64", "x86_64"):
            raise ValueError("VideoOut research requires Windows x86-64")
        engine, fixture, supervisor = (p.resolve(strict=True) for p in (engine, fixture, supervisor))
        result["build"] = startup.verify_inputs(engine, engine_report.resolve(strict=True), fixture, PROFILE)
        result.update(engine_sha256=startup.digest(engine), fixture_sha256=startup.digest(fixture),
                      supervisor_sha256=startup.digest(supervisor))
        vulkan = shutil.which("vulkaninfo")
        if not vulkan:
            raise ValueError("vulkaninfo is required to record the graphics host")
        diagnostic = subprocess.run([vulkan, "--summary"], capture_output=True, timeout=10, check=False)
        (output / "vulkan-summary.txt").write_bytes(diagnostic.stdout + diagnostic.stderr)
        if diagnostic.returncode:
            raise ValueError("Vulkan diagnostic failed")
        work = output / "session"
        startup.prepare_session(work)
        (work / "user/config.json").write_text(json.dumps({"Log": {"filter": "*:info", "flush_level": "trace"}}))
        app = work / "app"
        app.mkdir()
        (app / "phase.bin").write_bytes(b"\0")
        staged = app / "videoout_pattern.oelf"
        shutil.copyfile(fixture, staged)
        if startup.digest(staged) != result["fixture_sha256"]:
            raise ValueError("Staged fixture checksum mismatch")
        choices, palette = list(range(8)), []
        for unused in range(4):
            value = secrets.choice(choices)
            choices.remove(value)
            palette.append(value)
        challenge = bytes(palette)
        result["palette"] = palette
        result["palette_sha256"] = hashlib.sha256(challenge).hexdigest()
        if palette_case != "missing":
            (app / "palette.bin").write_bytes(challenge if palette_case == "valid" else challenge[:2])
        trace = work / "startup-audit.jsonl"
        command = [engine, "--game", staged, "--ignore-game-patch", "--startup-audit", trace]
        result["command"] = list(map(str, command))
        owner, requested, consumed = [], {}, set()
        def started(pid):
            owner.append(pid)
        def poll():
            evidence = progress(startup.read_events(trace))
            phase = len(result["captures"])
            if phase < 2 and len(evidence["phases"]) > phase:
                if phase not in requested:
                    from videoout_capture import request_screenshot
                    request = request_screenshot(owner[0], engine)
                    requested[phase] = time.monotonic()
                    result.setdefault("screenshot_requests", []).append(dict(phase=phase, **request))
                images = set((work / "user/screenshots").glob("*.png")) - consumed
                for path in sorted(images):
                    if path.stat().st_size > 4 * 1024 * 1024:
                        raise ValueError("Screenshot exceeds size limit")
                    try:
                        capture = verify_capture(path, challenge, phase)
                    except CaptureMismatch:
                        raise
                    except ValueError:
                        # The pinned presenter writes directly; retry an incomplete
                        # PNG until the finite deadline, never accept partial data.
                        continue
                    capture["path"] = str(path.relative_to(output))
                    # Atomically publish the next phase only after all pixels pass.
                    temporary = app / "phase.tmp"
                    temporary.write_bytes(bytes([phase + 1]))
                    try:
                        temporary.replace(app / "phase.bin")
                    except PermissionError:
                        # A Windows guest read may briefly deny delete sharing.
                        # Retry within the same finite screenshot deadline.
                        continue
                    result["captures"].append(capture)
                    consumed.add(path)
                    break
                if time.monotonic() - requested[phase] > 12:
                    raise ValueError("Timed out waiting for a qualifying Vulkan screenshot")
            return len(result["captures"]) == 2 and evidence["markers_observed"]
        result["engine_launch_attempted"] = True
        result["transport"] = startup.supervise(supervisor, command, work, timeout, poll, on_started=started)
        evidence = progress(startup.read_events(trace, final=True))
        result.update(guest_entry_observed=evidence["guest_entry_observed"],
                      guest_execution_tested=evidence["guest_entry_observed"], phases=evidence["phases"])
        if result["transport"]["reason"] != "requested" or not evidence["markers_observed"] or len(result["captures"]) != 2:
            raise ValueError("Guest/rendering evidence incomplete before exit/timeout")
        result.update(status="passed", graphics_verified=True)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        result["error"] = str(error)
    finally:
        if result["engine_launch_attempted"]:
            try:
                startup.collect_failure_evidence(output, result)
            except (OSError, ValueError) as error:
                result["postmortem_error"] = str(error)
        (output / "videoout-result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return (0 if result["graphics_verified"] else 1), result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("engine", "engine-report", "fixture", "supervisor", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=45)
    parser.add_argument("--palette-case", choices=("valid", "missing", "truncated"), default="valid")
    args = parser.parse_args()
    if not math.isfinite(args.timeout) or not 5 <= args.timeout <= 120:
        parser.error("--timeout must be finite and between 5 and 120 seconds")
    args.output = args.output.resolve()
    try:
        args.output.mkdir(parents=True, exist_ok=False)
    except OSError as error:
        parser.error(f"--output must be a new writable directory: {error}")
    code, result = run_attempt(**vars(args))
    print(json.dumps(result, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
