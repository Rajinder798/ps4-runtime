# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Bounded Windows research launch of the pinned, strict-audit engine and sample."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
MAX_AUDIT_BYTES = 4 * 1024 * 1024
MAX_LOG_BYTES = 64 * 1024 * 1024
MARKERS = ("main: Hello world! Waiting 2 seconds!", "main: Done. Infinitely looping...")


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


def evaluate(events):
    """Validate engine events; this does not attest an engine binary by itself."""
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
            if text in MARKERS:
                if not entered:
                    raise ValueError("Marker before guest entry")
                if text == MARKERS[0]:
                    if first is not None or second is not None:
                        raise ValueError("Duplicate/out-of-order greeting")
                    first = event["elapsed_us"]
                else:
                    if first is None or second is not None:
                        raise ValueError("Duplicate/out-of-order loop marker")
                    second = event["elapsed_us"]
        else:
            raise ValueError("Unknown strict audit event")
    if second is not None and second - first < 1_900_000:
        raise ValueError("Guest markers did not exercise the two-second sleep")
    return {"guest_entry_observed": entered, "markers_observed": second is not None,
            "marker_interval_us": None if second is None else second - first}


def supervise(supervisor, command, work, timeout, on_poll):
    """Transport/lifetime layer, also exercised with ordinary test processes."""
    stdout, stderr = work / "stdout.txt", work / "stderr.txt"
    stop, report = work / "stop.request", work / "supervisor.json"
    arguments = [str(supervisor), str(work), str(stdout), str(stderr), str(stop),
                 str(report), str(round(timeout * 1000)), *map(str, command)]
    monitor_error = None
    started = time.monotonic()
    with (work / "supervisor-stderr.txt").open("wb") as errors:
        child = subprocess.Popen(arguments, stdout=subprocess.DEVNULL, stderr=errors)
        try:
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
            raise RuntimeError("Supervisor failed: " + (work / "supervisor-stderr.txt").read_text(errors="replace"))
    result = json.loads(report.read_text())
    if result.get("schema_version") != 1 or result.get("tree_cleanup") is not True:
        raise RuntimeError("Process-tree cleanup not confirmed")
    if monitor_error:
        raise ValueError(monitor_error)
    return result


def verify_inputs(engine, engine_report, fixture):
    audit = json.loads((ROOT / "config/g2-integration-audit.json").read_text())
    contract = json.loads((ROOT / "config/startup-research.json").read_text())
    report = json.loads(engine_report.read_text())
    if (report.get("status") != "strict_engine_built" or
            report.get("upstream_revision") != audit["upstream"]["revision"] or
            report.get("patch_sha256") != contract["patch_sha256"] or
            report.get("audit_header_sha256") != contract["audit_header_sha256"] or
            report.get("executable_sha256") != digest(engine)):
        raise ValueError("Engine does not match the strict build evidence and locked patch")
    if digest(fixture) != audit["fixture"]["oelf_sha256"]:
        raise ValueError("Homebrew fixture hash differs from the selected build")
    if digest(ROOT / contract["patch_path"]) != contract["patch_sha256"]:
        raise ValueError("Research patch checksum mismatch")
    if digest(ROOT / contract["audit_header_path"]) != contract["audit_header_sha256"]:
        raise ValueError("Audit header checksum mismatch")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--engine-report", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--supervisor", type=Path, required=True)
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
    result = {"schema_version": 1, "status": "failed", "g2_passed": False,
              "guest_execution_tested": False, "engine_launch_attempted": False,
              "host": platform.platform(),
              "cpu": platform.processor(), "timeout_seconds": args.timeout,
              "upstream_redistribution_approved": False}
    code = 1
    try:
        if sys.platform != "win32" or platform.machine().lower() not in ("amd64", "x86_64"):
            raise ValueError("Research runner requires Windows x86-64")
        engine, fixture, supervisor = (p.resolve(strict=True) for p in (args.engine, args.fixture, args.supervisor))
        result["build"] = verify_inputs(engine, args.engine_report.resolve(strict=True), fixture)
        result.update(engine_sha256=digest(engine), fixture_sha256=digest(fixture),
                      supervisor_sha256=digest(supervisor))
        # Diagnostics are captured separately and are not treated as guest evidence.
        vulkan = shutil.which("vulkaninfo")
        if not vulkan:
            raise ValueError("vulkaninfo is required to record the graphics host")
        diagnostics = subprocess.run([vulkan, "--summary"], capture_output=True, timeout=10, check=False)
        (output / "vulkan-summary.txt").write_bytes(diagnostics.stdout + diagnostics.stderr)
        if diagnostics.returncode:
            raise ValueError("Vulkan host diagnostic failed; see vulkan-summary.txt")
        work = output / "session"
        (work / "user").mkdir(parents=True)
        trace = work / "startup-audit.jsonl"
        command = [engine, "--game", fixture, "--ignore-game-patch", "--startup-audit", trace]
        result["command"] = list(map(str, command))
        result["engine_launch_attempted"] = True
        transport = supervise(supervisor, command, work, args.timeout,
                              lambda: evaluate(read_events(trace))["markers_observed"])
        evidence = evaluate(read_events(trace, final=True))
        result.update(transport=transport, guest_execution_tested=evidence["guest_entry_observed"], **evidence)
        if transport["reason"] != "requested" or not evidence["markers_observed"]:
            raise ValueError("Engine exited/timed out before the qualifying guest markers")
        result.update(status="passed", g2_passed=True)
        code = 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        result["error"] = str(error)
    finally:
        (output / "startup-result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
