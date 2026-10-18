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
import struct

import run_homebrew_startup as startup
from videoout_evidence import CaptureMismatch, verify_capture

PROFILE = "videoout-pattern"
READY = ("videoout-pattern: phase=0 ready", "videoout-pattern: phase=1 ready")
PAD_PROFILE = "pad-videoout"
PAD_READY = ("pad-videoout: state=0 buttons=0 ready", "pad-videoout: state=1 buttons=16384 ready",
             "pad-videoout: state=2 buttons=0 ready")


def progress(events, profile=PROFILE):
    if profile not in (PROFILE, PAD_PROFILE):
        raise ValueError("Unknown graphics fixture")
    result = startup.evaluate(events, profile)
    ready = READY if profile == PROFILE else PAD_READY
    markers = startup.VIDEO_MARKERS if profile == PROFILE else startup.PAD_MARKERS
    phases, begun = [], False
    for event in events:
        if event.get("event") != "guest_output":
            continue
        text = event["text"]
        if text == markers[0]:
            begun = True
        elif text in ready:
            phase = ready.index(text)
            if not begun or phase != len(phases):
                raise ValueError("Duplicate/out-of-order VideoOut phase")
            phases.append(phase)
        elif text == markers[1] and phases != list(range(len(ready))):
            raise ValueError("VideoOut completion without both phases")
    return dict(**result, phases=phases)


def verify_pad_observations(path):
    data = path.read_bytes() if path.is_file() and path.stat().st_size == 48 else b""
    if len(data) != 48:
        raise ValueError("Missing or wrong-size guest pad observations")
    if any(data[offset + 5:offset + 8] != b"\0\0\0" for offset in (0, 16, 32)):
        raise ValueError("Invalid reserved bytes in guest pad observations")
    records = [dict(buttons=buttons, connected=connected, timestamp=timestamp)
               for buttons, connected, timestamp in struct.iter_unpack("<IB3xQ", data)]
    if ([r["buttons"] for r in records] != [0, 0x4000, 0] or
            any(r["connected"] != 1 or r["timestamp"] <= 0 for r in records) or
            not records[0]["timestamp"] < records[1]["timestamp"] < records[2]["timestamp"]):
        raise ValueError("Guest pad observations do not prove connected neutral/press/release")
    return dict(records=records, sha256=hashlib.sha256(data).hexdigest())


def run_attempt(*, engine, engine_report, fixture, supervisor, output, timeout=45, palette_case="valid",
                profile=PROFILE, input_case="press-release"):
    if (not math.isfinite(timeout) or not 5 <= timeout <= 120 or any(output.iterdir()) or
            palette_case not in ("valid", "missing", "truncated") or profile not in (PROFILE, PAD_PROFILE) or
            input_case not in ("press-release", "absent", "wrong-button") or
            (profile == PROFILE and input_case != "press-release")):
        raise ValueError("An empty output directory and valid reviewed profile, timeout and test cases are required")
    result = dict(schema_version=1, status="failed", profile=profile, graphics_verified=False,
        guest_execution_tested=False, guest_entry_observed=False, engine_launch_attempted=False,
        host=platform.platform(), cpu=platform.processor(), timeout_seconds=timeout,
        palette_case=palette_case, captures=[], upstream_redistribution_approved=False)
    is_pad = profile == PAD_PROFILE
    phase_count = 3 if is_pad else 2
    if is_pad:
        result.update(input_verified=False, input_case=input_case, input_events=[])
    try:
        if sys.platform != "win32" or platform.machine().lower() not in ("amd64", "x86_64"):
            raise ValueError("VideoOut research requires Windows x86-64")
        engine, fixture, supervisor = (p.resolve(strict=True) for p in (engine, fixture, supervisor))
        result["build"] = startup.verify_inputs(engine, engine_report.resolve(strict=True), fixture, profile)
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
        staged = app / (profile.replace("-", "_") + ".oelf")
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
            evidence = progress(startup.read_events(trace), profile)
            phase = len(result["captures"])
            if phase < phase_count and len(evidence["phases"]) > phase:
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
                        capture = verify_capture(path, challenge, phase % 2)
                    except CaptureMismatch:
                        raise
                    except ValueError:
                        # The pinned presenter writes directly; retry an incomplete
                        # PNG until the finite deadline, never accept partial data.
                        continue
                    capture["path"] = str(path.relative_to(output))
                    if is_pad:
                        capture.update(image_phase=capture["phase"], phase=phase)
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
                    if is_pad and phase in (0, 1) and input_case != "absent":
                        from videoout_capture import send_key
                        key = "circle" if input_case == "wrong-button" else "cross"
                        action = send_key(owner[0], engine, key, phase == 0)
                        result["input_events"].append(dict(after_phase=phase, **action))
                    break
                if time.monotonic() - requested[phase] > 12:
                    raise ValueError("Timed out waiting for a qualifying Vulkan screenshot")
            return len(result["captures"]) == phase_count and evidence["markers_observed"]
        result["engine_launch_attempted"] = True
        result["transport"] = startup.supervise(supervisor, command, work, timeout, poll, on_started=started)
        evidence = progress(startup.read_events(trace, final=True), profile)
        result.update(guest_entry_observed=evidence["guest_entry_observed"],
                      guest_execution_tested=evidence["guest_entry_observed"], phases=evidence["phases"])
        if result["transport"]["reason"] != "requested" or not evidence["markers_observed"] or len(result["captures"]) != phase_count:
            raise ValueError("Guest/rendering evidence incomplete before exit/timeout")
        if is_pad:
            result["pad_observations"] = verify_pad_observations(work / "user/data/input-result.bin")
            actions = [(e["after_phase"], e["key"], e["down"], e["root_pid"]) for e in result["input_events"]]
            pid = result["transport"]["root_pid"]
            if actions != [(0, "cross", True, pid), (1, "cross", False, pid)]:
                raise ValueError("Missing owned-engine Cross press/release transport evidence")
            mapping = work / "user/input_config/default.ini"
            if not {"cross = n", "circle = b"} <= set(line.strip() for line in mapping.read_text().splitlines()):
                raise ValueError("The pinned keyboard mapping was not retained")
            result["input_config_sha256"] = startup.digest(mapping)
            result["input_verified"] = True
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
    parser.add_argument("--profile", choices=(PROFILE, PAD_PROFILE), default=PROFILE)
    parser.add_argument("--input-case", choices=("press-release", "absent", "wrong-button"), default="press-release")
    args = parser.parse_args()
    if args.profile == PROFILE and args.input_case != "press-release":
        parser.error("--input-case requires --profile pad-videoout")
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
