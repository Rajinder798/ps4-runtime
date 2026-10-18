# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Bounded Windows research launch of the pinned, strict-audit engine and sample."""
import argparse
import hashlib
import json
import math
import secrets
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time
import runtime_settings

ROOT = Path(__file__).resolve().parents[1]
MAX_AUDIT_BYTES = 4 * 1024 * 1024
MAX_LOG_BYTES = 64 * 1024 * 1024
MARKERS = ("main: Hello world! Waiting 2 seconds!", "main: Done. Infinitely looping...")
SERVICE_MARKERS = ("service-roundtrip: begin", "service-roundtrip: PASS threads=2 bytes=256 seek=128")
VIDEO_MARKERS = ("videoout-pattern: begin", "videoout-pattern: PASS phases=2 cleanup=1")
PAD_MARKERS = ("pad-videoout: begin", "pad-videoout: PASS states=3 cleanup=1")
AUDIO_MARKERS = ("audio-pattern: begin", "audio-pattern: PASS phases=4 blocks=768 cleanup=1")
AV_MARKERS = ("interactive-av: begin", "interactive-av: PASS states=3 audio_thread=1 cleanup=1")


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def read_events(path, final=False):
    if not path.exists():
        return []
    if path.stat().st_size > MAX_AUDIT_BYTES:
        raise ValueError("Strict audit exceeds size limit")
    content = path.read_bytes()
    if not final and not content.endswith(b"\n"):
        content = content.rsplit(b"\n", 1)[0] + b"\n" if b"\n" in content else b""
    elif final and content and not content.endswith(b"\n"):
        raise ValueError("Truncated strict audit")
    return [json.loads(line) for line in content.decode("utf-8").splitlines()]


def evaluate(events, profile="hello-world"):
    """Validate engine events; this does not attest an engine binary by itself."""
    if profile not in ("hello-world", "service-roundtrip", "videoout-pattern", "pad-videoout", "audio-pattern", "interactive-av"):
        raise ValueError("Unknown fixture profile")
    markers = {"hello-world": MARKERS, "service-roundtrip": SERVICE_MARKERS,
               "videoout-pattern": VIDEO_MARKERS, "pad-videoout": PAD_MARKERS,
               "audio-pattern": AUDIO_MARKERS, "interactive-av": AV_MARKERS}[profile]
    configured = checked = entered = False
    first = second = None
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
            if event.get("phase") == "entry":
                checked = True
        elif kind == "guest_entry":
            if not checked or entered:
                raise ValueError("Guest entry without a unique strict import check")
            entered = True
        elif kind == "guest_output":
            text = event.get("text")
            if not isinstance(text, str):
                raise ValueError("Invalid guest output")
            if profile == "service-roundtrip" and text.startswith("service-roundtrip: FAIL"):
                raise ValueError("Guest service test failed: " + text)
            if profile == "videoout-pattern" and text.startswith("videoout-pattern: FAIL"):
                raise ValueError("Guest VideoOut test failed: " + text)
            if profile == "pad-videoout" and text.startswith("pad-videoout: FAIL"):
                raise ValueError("Guest pad test failed: " + text)
            if profile == "audio-pattern" and text.startswith("audio-pattern: FAIL"):
                raise ValueError("Guest audio test failed: " + text)
            if profile == "interactive-av" and text.startswith("interactive-av: FAIL"):
                raise ValueError("Guest combined test failed: " + text)
            if text in markers:
                if not entered:
                    raise ValueError("Marker before guest entry")
                if text == markers[0]:
                    if first is not None or second is not None:
                        raise ValueError("Duplicate/out-of-order greeting")
                    first = event["elapsed_us"]
                else:
                    if first is None or second is not None:
                        raise ValueError("Duplicate/out-of-order loop marker")
                    second = event["elapsed_us"]
        else:
            raise ValueError("Unknown strict audit event")
    if profile == "hello-world" and second is not None and second - first < 1_900_000:
        raise ValueError("Guest markers did not exercise the two-second sleep")
    return {"guest_entry_observed": entered, "markers_observed": second is not None,
            "marker_interval_us": None if second is None else second - first}


def background_process_options():
    # Console-free shortcut parents must not create helper consoles or inherit
    # a console's close/Ctrl-C lifecycle. Pipe/file diagnostics still work.
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}


def supervise(supervisor, command, work, timeout, on_poll, *, on_started=None, environment=None):
    """Transport/lifetime layer, also exercised with ordinary test processes."""
    stdout, stderr = work / "stdout.txt", work / "stderr.txt"
    stop, report = work / "stop.request", work / "supervisor.json"
    arguments = [str(supervisor), str(work), str(stdout), str(stderr), str(stop),
                 str(report), str(round(timeout * 1000)), *map(str, command)]
    monitor_error = None
    started = time.monotonic()
    with (work / "supervisor-stderr.txt").open("wb") as errors:
        child = subprocess.Popen(arguments, stdout=subprocess.DEVNULL, stderr=errors, env=environment,
                                 **background_process_options())
        try:
            if on_started is not None:
                on_started(child.pid)
            while child.poll() is None:
                try:
                    if sum(p.stat().st_size for p in work.rglob("*") if p.is_file()) > MAX_LOG_BYTES:
                        raise ValueError("Research output exceeds size limit")
                    if on_poll():
                        stop.touch(exist_ok=True)
                except (ValueError, OSError) as error:
                    monitor_error = str(error)
                    stop.touch(exist_ok=True)
                if time.monotonic() - started > timeout + 10:
                    raise RuntimeError("Supervisor exceeded cleanup budget")
                time.sleep(0.02)
        finally:
            # On interruption, ask for cleanup first. If the helper is stuck, closing
            # its job handle on termination still kills the assigned engine tree.
            if child.poll() is None:
                stop.touch(exist_ok=True)
                try:
                    child.wait(timeout=6)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=5)
        if child.returncode != 0 or not report.exists():
            raise RuntimeError(f"Supervisor failed (exit_code={child.returncode}, report_present={report.exists()}): " +
                               (work / "supervisor-stderr.txt").read_text(errors="replace"))
    result = json.loads(report.read_text())
    if result.get("schema_version") != 1 or result.get("tree_cleanup") is not True:
        raise RuntimeError("Process-tree cleanup not confirmed")
    if monitor_error:
        raise ValueError(monitor_error)
    return result


def verify_inputs(engine, engine_report, fixture, profile="hello-world"):
    audit = json.loads((ROOT / "config/g2-integration-audit.json").read_text())
    contract = json.loads((ROOT / "config/startup-research.json").read_text())
    report = json.loads(engine_report.read_text())
    if (report.get("status") != "strict_engine_built" or
            report.get("upstream_revision") != audit["upstream"]["revision"] or
            report.get("patch_sha256") != contract["patch_sha256"] or
            report.get("audit_header_sha256") != contract["audit_header_sha256"] or
            report.get("services_header_sha256") != contract["services_header_sha256"] or
            report.get("aac_header_sha256") != contract["aac_header_sha256"] or
            report.get("patched_tree") != contract["expected_patched_tree"] or
            report.get("aac_backend") != "ffmpeg-aac-lc" or
            report.get("fdk_linkage_verified_absent") is not True or
            report.get("aac_tests", {}).get("status") != "passed" or
            report.get("executable_sha256") != digest(engine)):
        raise ValueError("Engine does not match the strict build evidence and locked patch")
    if profile == "hello-world":
        fixture_hash = audit["fixture"]["oelf_sha256"]
    elif profile in ("service-roundtrip", "videoout-pattern", "pad-videoout", "audio-pattern", "interactive-av"):
        fixture_contract = json.loads((ROOT / f"config/{profile}.json").read_text())
        if (fixture_contract["schema_version"] != 1 or
                digest(ROOT / f"research/homebrew/{profile.replace('-', '_')}/main.cpp") != fixture_contract["source_sha256"]):
            raise ValueError("Reviewed fixture source checksum mismatch")
        fixture_hash = fixture_contract["oelf_sha256"]
    else:
        raise ValueError("Unknown fixture profile")
    if digest(fixture) != fixture_hash:
        raise ValueError("Homebrew fixture hash differs from the selected build")
    if digest(ROOT / contract["patch_path"]) != contract["patch_sha256"]:
        raise ValueError("Research patch checksum mismatch")
    if digest(ROOT / contract["audit_header_path"]) != contract["audit_header_sha256"]:
        raise ValueError("Audit header checksum mismatch")
    if digest(ROOT / contract["services_header_path"]) != contract["services_header_sha256"]:
        raise ValueError("Kernel services header checksum mismatch")
    if digest(ROOT / contract["aac_header_path"]) != contract["aac_header_sha256"]:
        raise ValueError("AAC decoder header checksum mismatch")
    return report


def collect_failure_evidence(output, result):
    """Keep postmortem evidence even when the monitor rejects a live trace.

    Observation of guest entry is separate from passing G2. Only a validated
    prefix ending at guest_entry establishes that observation; raw event names
    or matching host log text cannot establish it.
    """
    work = output / "session"
    transport = work / "supervisor.json"
    if transport.exists():
        result["transport"] = json.loads(transport.read_text(encoding="utf-8"))
    trace = work / "startup-audit.jsonl"
    if not trace.exists():
        return
    events = read_events(trace, final=True)
    audit = {"sha256": digest(trace), "event_count": len(events),
             "unresolved": [e for e in events if isinstance(e, dict) and e.get("event") == "unresolved"]}
    result["audit"] = audit
    try:
        evaluate(events, result.get("profile", "hello-world"))
    except ValueError as error:
        audit["validation_error"] = str(error)
    for index, event in enumerate(events):
        if isinstance(event, dict) and event.get("event") == "guest_entry":
            try:
                observed = evaluate(events[:index + 1], result.get("profile", "hello-world"))["guest_entry_observed"]
            except ValueError:
                observed = False
            result.update(guest_entry_observed=observed, guest_execution_tested=observed)
            break


def prepare_session(work):
    """Create empty default homes for the pinned engine, never reuse a profile.

    UserManager::CreateDefaultUsers opens a modal migration dialog when home
    1000 is absent, even without old saves. These empty directories let the
    engine create its normal users.json without entering that migration path.
    """
    work.mkdir()
    for user_id in range(1000, 1004):
        for name in ("savedata", "trophy", "inputs"):
            (work / "user" / "home" / str(user_id) / name).mkdir(parents=True)


def service_expected(challenge):
    if len(challenge) != 256:
        raise ValueError("Service challenge must contain 256 bytes")
    return bytes(((value ^ 0xa5) + index) % 256 for index, value in enumerate(challenge))


def prepare_service(work, fixture):
    """Fresh app mount and random input. Only the guest writes the result file."""
    app = work / "app"
    app.mkdir()
    staged = app / "service_roundtrip.oelf"
    shutil.copyfile(fixture, staged)
    challenge = secrets.token_bytes(256)
    (app / "challenge.bin").write_bytes(challenge)
    return staged, challenge


def verify_service(work, challenge):
    result = work / "user/data/service-result.bin"
    if not result.is_file() or result.stat().st_size != 256 or result.read_bytes() != service_expected(challenge):
        raise ValueError("Guest output file differs from the independent host calculation")
    return {"status": "passed", "bytes_verified": 256, "threads_joined": 2,
            "challenge_sha256": hashlib.sha256(challenge).hexdigest(), "result_sha256": digest(result)}


def run_attempt(*, engine, engine_report, fixture, supervisor, output, timeout=30, profile="hello-world", log_level=None):
    """Run in a caller-created empty output directory; return (exit code, evidence)."""
    if (not math.isfinite(timeout) or not 3 <= timeout <= 120 or
            profile not in ("hello-world", "service-roundtrip") or any(output.iterdir()) or
            (log_level is not None and log_level not in runtime_settings.LOG_LEVELS)):
        raise ValueError("A valid profile, timeout and empty output directory are required")
    result = {"schema_version": 1, "status": "failed", "g2_passed": False, "profile": profile,
              "guest_execution_tested": False, "guest_entry_observed": False,
              "engine_launch_attempted": False,
              "host": platform.platform(),
              "cpu": platform.processor(), "timeout_seconds": timeout,
              "upstream_redistribution_approved": False}
    code = 1
    try:
        if sys.platform != "win32" or platform.machine().lower() not in ("amd64", "x86_64"):
            raise ValueError("Research runner requires Windows x86-64")
        engine, fixture, supervisor = (p.resolve(strict=True) for p in (engine, fixture, supervisor))
        result["build"] = verify_inputs(engine, engine_report.resolve(strict=True), fixture, profile)
        result.update(engine_sha256=digest(engine), fixture_sha256=digest(fixture),
                      supervisor_sha256=digest(supervisor))
        # Diagnostics are captured separately and are not treated as guest evidence.
        vulkan = shutil.which("vulkaninfo")
        if not vulkan:
            raise ValueError("vulkaninfo is required to record the graphics host")
        diagnostics = subprocess.run([vulkan, "--summary"], capture_output=True, timeout=10, check=False,
                                     **background_process_options())
        (output / "vulkan-summary.txt").write_bytes(diagnostics.stdout + diagnostics.stderr)
        if diagnostics.returncode:
            raise ValueError("Vulkan host diagnostic failed; see vulkan-summary.txt")
        work = output / "session"
        prepare_session(work)
        if log_level is not None:
            # The pinned engine merges this supported JSON group over defaults.
            # Immediate flush retains accepted messages before bounded termination.
            engine_settings = {"Log": {"filter": "*:" + log_level, "flush_level": "trace"}}
            (work / "user/config.json").write_text(json.dumps(engine_settings) + "\n", encoding="utf-8")
            result["requested_settings"] = {"log_level": log_level}
        if profile == "service-roundtrip":
            fixture, challenge = prepare_service(work, fixture)
            if digest(fixture) != result["fixture_sha256"]:
                raise ValueError("Staged fixture checksum mismatch")
        trace = work / "startup-audit.jsonl"
        command = [engine, "--game", fixture, "--ignore-game-patch", "--startup-audit", trace]
        result["command"] = list(map(str, command))
        result["engine_launch_attempted"] = True
        transport = supervise(supervisor, command, work, timeout,
                              lambda: evaluate(read_events(trace), profile)["markers_observed"])
        evidence = evaluate(read_events(trace, final=True), profile)
        result.update(transport=transport, guest_execution_tested=evidence["guest_entry_observed"], **evidence)
        if transport["reason"] != "requested" or not evidence["markers_observed"]:
            raise ValueError("Engine exited/timed out before the qualifying guest markers")
        if profile == "service-roundtrip":
            result["service_roundtrip"] = verify_service(work, challenge)
        result.update(status="passed", g2_passed=True)
        code = 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        result["error"] = str(error)
    finally:
        if result["engine_launch_attempted"] and not result["g2_passed"]:
            try:
                collect_failure_evidence(output, result)
            except (OSError, ValueError) as error:
                result["postmortem_error"] = str(error)
        (output / "startup-result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return code, result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--engine-report", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--supervisor", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="New research directory")
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--profile", choices=("hello-world", "service-roundtrip"), default="hello-world")
    args = parser.parse_args()
    if not math.isfinite(args.timeout) or not 3 <= args.timeout <= 120:
        parser.error("--timeout must be finite and between 3 and 120 seconds")
    output = args.output.resolve()
    try:
        output.mkdir(parents=True, exist_ok=False)
    except OSError as error:
        parser.error(f"--output must be a new writable directory: {error}")
    code, result = run_attempt(engine=args.engine, engine_report=args.engine_report,
        fixture=args.fixture, supervisor=args.supervisor, output=output, timeout=args.timeout, profile=args.profile)
    print(json.dumps(result, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
