# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Bounded Windows research run of the save-roundtrip fixture on the strict-audit engine.

A separate runner, like the live-av-v2 contract: the shared run_homebrew_startup.py
is pinned by reviewed G4 records, so only its unchanged helpers (hashing, audit
reading, session preparation and supervision) are reused here.
"""
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

import psf
import run_homebrew_startup as startup

ROOT = Path(__file__).resolve().parents[1]
PROFILE = "save-roundtrip"
MARKERS = ("save-roundtrip: begin", "save-roundtrip: PASS bytes=256 remount=1 search=1")
FAILURE = "save-roundtrip: FAIL"
# Original title identity for the save fixture; not the identity of any published title.
TITLE_ID, DIRECTORY = "PRTS00001", "PS4RTSAVE01"


def verify_inputs(engine, engine_report, fixture):
    """Same strict-build checks as the shared runner, bound to the save fixture contract."""
    audit = json.loads((ROOT / "config/g2-integration-audit.json").read_text())
    contract = json.loads((ROOT / "config/startup-research.json").read_text())
    report = json.loads(engine_report.read_text())
    if (report.get("status") != "strict_engine_built" or
            report.get("upstream_revision") != audit["upstream"]["revision"] or
            any(report.get(key) != contract[key] for key in
                ("patch_sha256", "audit_header_sha256", "services_header_sha256", "aac_header_sha256")) or
            report.get("patched_tree") != contract["expected_patched_tree"] or
            report.get("aac_backend") != "ffmpeg-aac-lc" or
            report.get("fdk_linkage_verified_absent") is not True or
            report.get("aac_tests", {}).get("status") != "passed" or
            report.get("executable_sha256") != startup.digest(engine)):
        raise ValueError("Engine does not match the strict build evidence and locked patch")
    fixture_contract = json.loads((ROOT / "config/save-roundtrip.json").read_text())
    if (fixture_contract["schema_version"] != 1 or
            startup.digest(ROOT / "research/homebrew/save_roundtrip/main.cpp") != fixture_contract["source_sha256"]):
        raise ValueError("Reviewed fixture source checksum mismatch")
    if startup.digest(fixture) != fixture_contract["oelf_sha256"]:
        raise ValueError("Homebrew fixture hash differs from the selected build")
    for key in ("patch", "audit_header", "services_header", "aac_header"):
        if startup.digest(ROOT / contract[key + "_path"]) != contract[key + "_sha256"]:
            raise ValueError(f"Research input checksum mismatch: {key}")
    return report


def evaluate(events):
    """Strict-audit rules of the shared runner, with this fixture's markers and failure line."""
    configured = checked = entered = False
    begin = passed = None
    previous = -1
    for event in events:
        if (not isinstance(event, dict) or event.get("schema_version") != 1 or
                type(event.get("elapsed_us")) is not int or event["elapsed_us"] < previous):
            raise ValueError("Invalid or non-monotonic strict audit")
        previous = event["elapsed_us"]
        kind = event.get("event")
        if kind == "configured":
            if configured or event.get("strict_imports") is not True:
                raise ValueError("Invalid strict configuration")
            configured = True
        elif not configured:
            raise ValueError("Audit event before configuration")
        elif kind == "unresolved":
            raise ValueError("Unresolved import/relocation: " + json.dumps(event, ensure_ascii=True))
        elif kind == "imports_checked":
            if type(event.get("unresolved_count")) is not int or event["unresolved_count"] != 0:
                raise ValueError("Import check failed")
            checked = checked or event.get("phase") == "entry"
        elif kind == "guest_entry":
            if not checked or entered:
                raise ValueError("Guest entry without a unique strict import check")
            entered = True
        elif kind == "guest_output":
            text = event.get("text")
            if not isinstance(text, str):
                raise ValueError("Invalid guest output")
            if text.startswith(FAILURE):
                raise ValueError("Guest save test failed: " + text)
            if text in MARKERS:
                if not entered:
                    raise ValueError("Marker before guest entry")
                if text == MARKERS[0]:
                    if begin is not None or passed is not None:
                        raise ValueError("Duplicate/out-of-order begin marker")
                    begin = event["elapsed_us"]
                elif begin is None or passed is not None:
                    raise ValueError("Duplicate/out-of-order PASS marker")
                else:
                    passed = event["elapsed_us"]
        else:
            raise ValueError("Unknown strict audit event")
    return {"guest_entry_observed": entered, "markers_observed": passed is not None}


def expected(challenge):
    if len(challenge) != 256:
        raise ValueError("Save challenge must contain 256 bytes")
    return bytes(((value + 0x3C) ^ (index * 7)) % 256 for index, value in enumerate(challenge))


def prepare(work, fixture):
    """Fresh app mount with its own minimal param.sfo and random input.

    The title ID makes the engine store saves under a known title folder, as it
    does for a packaged title. Only the guest creates the save data.
    """
    app = work / "app"
    (app / "sce_sys").mkdir(parents=True)
    staged = app / "save_roundtrip.oelf"
    shutil.copyfile(fixture, staged)
    (app / "sce_sys/param.sfo").write_bytes(psf.write(
        {"TITLE_ID": TITLE_ID, "TITLE": "PS4 Runtime save fixture", "APP_VER": "01.00"}))
    challenge = secrets.token_bytes(256)
    (app / "challenge.bin").write_bytes(challenge)
    return staged, challenge


def verify_save(work, challenge):
    """Find the one save the guest created and check it against the host's own calculation."""
    homes = work / "user/home"
    found = sorted(homes.glob(f"*/savedata/{TITLE_ID}/{DIRECTORY}"))
    stray = sorted(homes.glob(f"*/savedata/{DIRECTORY}"))
    if len(found) != 1 or stray:
        raise ValueError(f"Expected exactly one save directory under title {TITLE_ID}; "
                         f"found {len(found)}, outside the title folder {len(stray)}")
    result = found[0] / "result.bin"
    if not result.is_file() or result.stat().st_size != 256 or result.read_bytes() != expected(challenge):
        raise ValueError("Saved file differs from the independent host calculation")
    metadata = psf.read((found[0] / "sce_sys/param.sfo").read_bytes())
    if metadata.get("TITLE_ID") != TITLE_ID or metadata.get("SAVEDATA_DIRECTORY") != DIRECTORY:
        raise ValueError("Save metadata does not name the fixture title and directory")
    # found[0] is <home>/<user>/savedata/<title>/<directory>.
    return {"status": "passed", "bytes_verified": 256, "user_id": found[0].parents[2].name,
            "title_id": TITLE_ID, "directory": DIRECTORY,
            "challenge_sha256": hashlib.sha256(challenge).hexdigest(), "result_sha256": startup.digest(result)}


def collect_failure_evidence(output, result):
    """Keep the supervisor report and audit summary; guest entry counts only from a valid prefix."""
    work = output / "session"
    if (work / "supervisor.json").exists():
        result["transport"] = json.loads((work / "supervisor.json").read_text(encoding="utf-8"))
    trace = work / "startup-audit.jsonl"
    if not trace.exists():
        return
    events = startup.read_events(trace, final=True)
    audit = {"sha256": startup.digest(trace), "event_count": len(events),
             "unresolved": [e for e in events if isinstance(e, dict) and e.get("event") == "unresolved"]}
    result["audit"] = audit
    try:
        evaluate(events)
    except ValueError as error:
        audit["validation_error"] = str(error)
    for index, event in enumerate(events):
        if isinstance(event, dict) and event.get("event") == "guest_entry":
            try:
                observed = evaluate(events[:index + 1])["guest_entry_observed"]
            except ValueError:
                observed = False
            result.update(guest_entry_observed=observed, guest_execution_tested=observed)
            break


def run_attempt(*, engine, engine_report, fixture, supervisor, output, timeout=30):
    """Run in a caller-created empty output directory; return (exit code, evidence)."""
    if not math.isfinite(timeout) or not 3 <= timeout <= 120 or any(output.iterdir()):
        raise ValueError("A valid timeout and empty output directory are required")
    result = {"schema_version": 1, "status": "failed", "passed": False, "profile": PROFILE,
              "guest_execution_tested": False, "guest_entry_observed": False, "engine_launch_attempted": False,
              "host": platform.platform(), "cpu": platform.processor(), "timeout_seconds": timeout,
              "upstream_redistribution_approved": False}
    code = 1
    try:
        if sys.platform != "win32" or platform.machine().lower() not in ("amd64", "x86_64"):
            raise ValueError("Research runner requires Windows x86-64")
        engine, fixture, supervisor = (p.resolve(strict=True) for p in (engine, fixture, supervisor))
        result["build"] = verify_inputs(engine, engine_report.resolve(strict=True), fixture)
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
        work = output / "session"
        startup.prepare_session(work)
        staged, challenge = prepare(work, fixture)
        if startup.digest(staged) != result["fixture_sha256"]:
            raise ValueError("Staged fixture checksum mismatch")
        trace = work / "startup-audit.jsonl"
        command = [engine, "--game", staged, "--ignore-game-patch", "--startup-audit", trace]
        result["command"] = list(map(str, command))
        result["engine_launch_attempted"] = True
        transport = startup.supervise(supervisor, command, work, timeout,
                                      lambda: evaluate(startup.read_events(trace))["markers_observed"])
        evidence = evaluate(startup.read_events(trace, final=True))
        result.update(transport=transport, guest_execution_tested=evidence["guest_entry_observed"], **evidence)
        if transport["reason"] != "requested" or not evidence["markers_observed"]:
            raise ValueError("Engine exited/timed out before the qualifying guest markers")
        result["save_roundtrip"] = verify_save(work, challenge)
        result.update(status="passed", passed=True)
        code = 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        result["error"] = str(error)
    finally:
        if result["engine_launch_attempted"] and not result["passed"]:
            try:
                collect_failure_evidence(output, result)
            except (OSError, ValueError) as error:
                result["postmortem_error"] = str(error)
        (output / "save-result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return code, result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("engine", "engine-report", "fixture", "supervisor"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="New research directory")
    parser.add_argument("--timeout", type=float, default=30)
    args = parser.parse_args()
    if not math.isfinite(args.timeout) or not 3 <= args.timeout <= 120:
        parser.error("--timeout must be finite and between 3 and 120 seconds")
    output = args.output.resolve()
    try:
        output.mkdir(parents=True, exist_ok=False)
    except OSError as error:
        parser.error(f"--output must be a new writable directory: {error}")
    code, result = run_attempt(engine=args.engine, engine_report=args.engine_report, fixture=args.fixture,
                               supervisor=args.supervisor, output=output, timeout=args.timeout)
    print(json.dumps(result, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
