# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""One registered launch of the save-counter fixture, with its saves kept between launches.

Called by the launch contract (tools/ps4_launch.py) with the user's state folder.
Inside the per-title lock it prepares a fresh session, stages the title's stored
saves from `<state>/titles/PRTS00003` (title_save_store.stage), runs the fixture on
the strict-audit engine and checks the new counter on disk. Only then does it
commit the session's saves back. Any failure leaves the store as it was.
"""
import json
import math
from pathlib import Path
import platform
import shutil
import struct
import subprocess
import sys

import psf
import run_homebrew_startup as startup
import run_save_roundtrip as save
import runtime_settings
import title_save_store as store

PROFILE = "save-counter"
# Original title identity for this fixture; not the identity of any published title.
TITLE_ID, DIRECTORY = "PRTS00003", "PS4RTCOUNT"
BEGIN, FAILURE, PASS = "save-counter: begin", "save-counter: FAIL", "save-counter: PASS "
MAGIC, MAX_COUNT = b"PS4RTCNT", 1_000_000


def encode(count):
    """The fixture's 16-byte counter.bin: magic, count, ~count (little-endian)."""
    return struct.pack("<8sII", MAGIC, count, count ^ 0xFFFFFFFF)


def decode(blob):
    if len(blob) != 16:
        raise ValueError("counter.bin must be 16 bytes")
    magic, count, check = struct.unpack("<8sII", blob)
    if magic != MAGIC or check != count ^ 0xFFFFFFFF or not 1 <= count < MAX_COUNT:
        raise ValueError("counter.bin is damaged or out of range")
    return count


def markers(previous):
    return BEGIN, f"save-counter: PASS previous={previous} count={previous + 1}"


def counter_folders(work):
    homes = work / "user/home"
    return sorted(homes.glob(f"*/savedata/{TITLE_ID}/{DIRECTORY}")), sorted(homes.glob(f"*/savedata/{DIRECTORY}"))


def staged_count(work):
    """The counter carried into the fresh session from the store: (count, user), or (0, None)."""
    found, stray = counter_folders(work)
    if stray or len(found) > 1:
        raise ValueError("The staged saves hold more than one counter")
    if not found:
        return 0, None
    try:
        return decode((found[0] / "counter.bin").read_bytes()), found[0].parents[2].name
    except (OSError, ValueError) as error:
        raise ValueError(f"The stored save of title {TITLE_ID} is damaged: {error}") from error


def check(events, expected):
    """Strict-audit rules, plus: a PASS line with any other count is a failure, not a wait."""
    for event in events:
        if (isinstance(event, dict) and event.get("event") == "guest_output" and
                isinstance(event.get("text"), str) and event["text"].startswith(PASS) and event["text"] != expected[1]):
            raise ValueError("Guest counter differs from the staged save: " + event["text"])
    return save.evaluate(events, expected, FAILURE)


def verify_counter(work, previous, user):
    """Independent host check of the counter the guest left in the session."""
    found, stray = counter_folders(work)
    if len(found) != 1 or stray:
        raise ValueError(f"Expected exactly one counter save under title {TITLE_ID}; "
                         f"found {len(found)}, outside the title folder {len(stray)}")
    saved_user = found[0].parents[2].name
    if user is not None and saved_user != user:
        raise ValueError("The counter moved to a different user")
    count = decode((found[0] / "counter.bin").read_bytes())
    if count != previous + 1:
        raise ValueError(f"Stored counter is {count}, expected {previous + 1}")
    metadata = psf.read((found[0] / "sce_sys/param.sfo").read_bytes())
    if metadata.get("TITLE_ID") != TITLE_ID or metadata.get("SAVEDATA_DIRECTORY") != DIRECTORY:
        raise ValueError("Save metadata does not name the fixture title and directory")
    return {"status": "passed", "user_id": saved_user, "previous_count": previous, "count": count,
            "counter_sha256": startup.digest(found[0] / "counter.bin")}


def prepare_app(work, fixture):
    app = work / "app"
    (app / "sce_sys").mkdir(parents=True)
    staged = app / "save_counter.oelf"
    shutil.copyfile(fixture, staged)
    (app / "sce_sys/param.sfo").write_bytes(psf.write(
        {"TITLE_ID": TITLE_ID, "TITLE": "PS4 Runtime save counter fixture", "APP_VER": "01.00"}))
    return staged


def run_attempt(*, engine, engine_report, fixture, supervisor, output, state, timeout=30, log_level=None):
    """Run in a caller-created empty output directory; return (exit code, evidence).

    `failed_phase` names where a failure happened: `prepare`, `stage` (store refused
    or damaged; nothing launched), `guest`, `verify` or `commit`. The store changes
    only in a successful `commit`.
    """
    if (not math.isfinite(timeout) or not 3 <= timeout <= 120 or any(output.iterdir()) or
            (log_level is not None and log_level not in runtime_settings.LOG_LEVELS)):
        raise ValueError("A valid timeout, log level and empty output directory are required")
    result = {"schema_version": 1, "status": "failed", "passed": False, "profile": PROFILE, "title_id": TITLE_ID,
              "guest_execution_tested": False, "guest_entry_observed": False, "engine_launch_attempted": False,
              "host": platform.platform(), "cpu": platform.processor(), "timeout_seconds": timeout,
              "saves_committed": False, "upstream_redistribution_approved": False}
    code, phase = 1, "prepare"
    try:
        if sys.platform != "win32" or platform.machine().lower() not in ("amd64", "x86_64"):
            raise ValueError("Research runner requires Windows x86-64")
        engine, fixture, supervisor = (p.resolve(strict=True) for p in (engine, fixture, supervisor))
        result["build"] = save.verify_inputs(engine, engine_report.resolve(strict=True), fixture, PROFILE)
        result.update(engine_sha256=startup.digest(engine), fixture_sha256=startup.digest(fixture),
                      supervisor_sha256=startup.digest(supervisor))
        vulkan = shutil.which("vulkaninfo")
        if not vulkan:
            raise ValueError("vulkaninfo is required to record the graphics host")
        diagnostics = subprocess.run([vulkan, "--summary"], capture_output=True, timeout=10, check=False,
                                     **startup.background_process_options())
        (output / "vulkan-summary.txt").write_bytes(diagnostics.stdout + diagnostics.stderr)
        if diagnostics.returncode:
            raise ValueError("Vulkan host diagnostic failed; see vulkan-summary.txt")
        phase = "stage"
        with store.lock(state, TITLE_ID):
            work = output / "session"
            startup.prepare_session(work)
            if log_level is not None:
                # Same supported engine log group as the shared runner.
                engine_settings = {"Log": {"filter": "*:" + log_level, "flush_level": "trace"}}
                (work / "user/config.json").write_text(json.dumps(engine_settings) + "\n", encoding="utf-8")
                result["requested_settings"] = {"log_level": log_level}
            result["staged"] = store.stage(state, TITLE_ID, work)
            previous, user = staged_count(work)
            result["previous_count"] = previous
            phase = "prepare"
            staged = prepare_app(work, fixture)
            if startup.digest(staged) != result["fixture_sha256"]:
                raise ValueError("Staged fixture checksum mismatch")
            expected = markers(previous)
            result["expected_marker"] = expected[1]
            trace = work / "startup-audit.jsonl"
            command = [engine, "--game", staged, "--ignore-game-patch", "--startup-audit", trace]
            result["command"] = list(map(str, command))
            phase = "guest"
            result["engine_launch_attempted"] = True
            transport = startup.supervise(supervisor, command, work, timeout,
                                          lambda: check(startup.read_events(trace), expected)["markers_observed"])
            evidence = check(startup.read_events(trace, final=True), expected)
            result.update(transport=transport, guest_execution_tested=evidence["guest_entry_observed"], **evidence)
            if (transport.get("reason") != "requested" or not evidence["markers_observed"] or
                    transport.get("tree_cleanup") is not True):
                raise ValueError("Engine exited/timed out before the qualifying guest markers, or cleanup was not confirmed")
            phase = "verify"
            result["save_counter"] = verify_counter(work, previous, user)
            phase = "commit"
            result["committed"] = store.commit(state, TITLE_ID, work)
            result["saves_committed"] = True
        result.update(status="passed", passed=True)
        code = 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        result.update(error=str(error), failed_phase=phase)
    finally:
        if result["engine_launch_attempted"] and not result["passed"]:
            try:
                save.collect_failure_evidence(output, result)
                trace = output / "session/startup-audit.jsonl"
                if trace.exists():
                    result["guest_failure"] = next((e["text"] for e in startup.read_events(trace, final=True)
                        if isinstance(e, dict) and e.get("event") == "guest_output" and
                        isinstance(e.get("text"), str) and e["text"].startswith(FAILURE)), None)
            except (OSError, ValueError) as error:
                result["postmortem_error"] = str(error)
        (output / "save-result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return code, result
