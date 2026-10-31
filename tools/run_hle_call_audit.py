# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Bounded Windows run of a G2 fixture under the diagnostic HLE call audit engine.

Uses the same supervisor, fresh session and strict-audit rules as
`run_homebrew_startup.py`; the engine is the separately built variant described by
config/hle-call-audit.json. The strict runner rejects this engine's extra events,
so neither engine can be substituted for the other.
"""
import argparse
import json
import math
from pathlib import Path
import platform
import shutil
import subprocess
import sys

import engine_coverage
import hle_call_audit
import run_homebrew_startup as startup
import runtime_settings

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = {"hello-world": "hello_world.oelf", "service-roundtrip": "service_roundtrip.oelf"}


def load_contract():
    contract = json.loads((ROOT / "config/hle-call-audit.json").read_text(encoding="utf-8"))
    base = json.loads((ROOT / "config/startup-research.json").read_text(encoding="utf-8"))
    if contract.get("schema_version") != 1:
        raise ValueError("Unsupported HLE call audit contract")
    for key, value in contract["base"].items():
        if base.get(key) != value:
            raise ValueError(f"HLE call audit contract targets a different strict research input: {key}")
    for key in ("patch", "header"):
        if startup.digest(ROOT / contract[f"{key}_path"]) != contract[f"{key}_sha256"]:
            raise ValueError(f"HLE call audit {key} checksum mismatch")
    return contract


def verify_engine(engine, engine_report):
    contract = load_contract()
    report = json.loads(Path(engine_report).read_text(encoding="utf-8"))
    expected = dict(contract["base"], status="hle_call_audit_engine_built",
                    hle_call_audit_patch_sha256=contract["patch_sha256"],
                    hle_call_audit_header_sha256=contract["header_sha256"],
                    patched_tree=contract["expected_tree"], executable_sha256=startup.digest(engine))
    expected.pop("expected_patched_tree")
    if any(report.get(key) != value for key, value in expected.items()):
        raise ValueError("Engine does not match the HLE call audit build evidence and locked patches")
    return report, contract


def verify_fixture(fixture, profile):
    if profile == "hello-world":
        expected = json.loads((ROOT / "config/g2-integration-audit.json").read_text())["fixture"]["oelf_sha256"]
    else:
        fixture_contract = json.loads((ROOT / f"config/{profile}.json").read_text())
        if startup.digest(ROOT / "research/homebrew/service_roundtrip/main.cpp") != fixture_contract["source_sha256"]:
            raise ValueError("Reviewed fixture source checksum mismatch")
        expected = fixture_contract["oelf_sha256"]
    if startup.digest(fixture) != expected:
        raise ValueError("Homebrew fixture hash differs from the selected build")


def run_attempt(*, engine, engine_report, fixture, imports, supervisor, output, source=None,
                timeout=30, profile="hello-world", log_level=None):
    """Run in a caller-created empty output directory; return (exit code, evidence)."""
    if (not math.isfinite(timeout) or not 3 <= timeout <= 120 or profile not in FIXTURES or any(output.iterdir()) or
            (log_level is not None and log_level not in runtime_settings.LOG_LEVELS)):
        raise ValueError("A valid profile, timeout and empty output directory are required")
    result = {"schema_version": 1, "status": "failed", "profile": profile, "engine_variant": "hle-call-audit",
              "guest_execution_tested": False, "engine_launch_attempted": False,
              "host": platform.platform(), "cpu": platform.processor(), "timeout_seconds": timeout,
              "upstream_redistribution_approved": False}
    code = 1
    try:
        if sys.platform != "win32" or platform.machine().lower() not in ("amd64", "x86_64"):
            raise ValueError("Research runner requires Windows x86-64")
        engine, fixture, supervisor = (p.resolve(strict=True) for p in (engine, fixture, supervisor))
        build, contract = verify_engine(engine, engine_report.resolve(strict=True))
        verify_fixture(fixture, profile)
        inventory = json.loads(imports.read_text(encoding="utf-8"))
        result.update(engine_sha256=build["executable_sha256"], patched_tree=build["patched_tree"],
                      fixture_sha256=startup.digest(fixture), imports_sha256=startup.digest(imports),
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
        if log_level is not None:
            # Same supported engine log group as the strict runner; immediate flush survives termination.
            (work / "user/config.json").write_text(json.dumps(
                {"Log": {"filter": "*:" + log_level, "flush_level": "trace"}}) + "\n", encoding="utf-8")
            result["requested_settings"] = {"log_level": log_level}
        if profile == "service-roundtrip":
            staged, challenge = startup.prepare_service(work, fixture)
            if startup.digest(staged) != result["fixture_sha256"]:
                raise ValueError("Staged fixture checksum mismatch")
            fixture = staged
        trace = work / "startup-audit.jsonl"
        command = [engine, "--game", fixture, "--ignore-game-patch", "--startup-audit", trace]
        result["command"] = list(map(str, command))
        result["engine_launch_attempted"] = True

        def markers_observed():
            events = startup.read_events(trace)
            if not any(isinstance(e, dict) and e.get("event") == "hle_call_audit" for e in events):
                return False  # Readiness follows HLE registration; the prefix is still incomplete.
            rest, _, _ = hle_call_audit.split(events)
            return startup.evaluate(rest, profile)["markers_observed"]

        transport = startup.supervise(supervisor, command, work, timeout, markers_observed)
        events = startup.read_events(trace, final=True)
        names = engine_coverage.nid_names(source) if source else {}
        audit = hle_call_audit.report(inventory, events, profile, names)
        result.update(transport=transport, guest_execution_tested=True, audit_sha256=startup.digest(trace))
        if transport["reason"] != "requested" or not audit["markers_observed"]:
            raise ValueError("Engine exited/timed out before the qualifying guest markers")
        if profile == "service-roundtrip":
            result["service_roundtrip"] = startup.verify_service(work, challenge)
        markers = {e["text"]: e["elapsed_us"] for e in events if e.get("event") == "guest_output"}
        oracles = [dict(oracle, before_us=markers[oracle["before_marker"]])
                   for oracle in contract["oracles"][profile]]
        result["oracles"] = hle_call_audit.check_oracles(audit, oracles)
        result["hle_call_audit"] = audit
        if not all(outcome["passed"] for outcome in result["oracles"]):
            raise ValueError("An independent guest observation lacks the HLE entry it requires")
        result["status"] = "passed"
        code = 0
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError) as error:
        result["error"] = str(error)
    finally:
        (output / "hle-call-audit-result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return code, result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--engine-report", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--imports", type=Path, required=True, help="`ps4-runtime imports --json` of the fixture")
    parser.add_argument("--supervisor", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="New research directory")
    parser.add_argument("--source", type=Path, help="Engine source, only for AeroLib names")
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--profile", choices=tuple(FIXTURES), default="hello-world")
    parser.add_argument("--log-level", choices=runtime_settings.LOG_LEVELS)
    args = parser.parse_args()
    if not math.isfinite(args.timeout) or not 3 <= args.timeout <= 120:
        parser.error("--timeout must be finite and between 3 and 120 seconds")
    output = args.output.resolve()
    try:
        output.mkdir(parents=True, exist_ok=False)
    except OSError as error:
        parser.error(f"--output must be a new writable directory: {error}")
    code, result = run_attempt(engine=args.engine, engine_report=args.engine_report, fixture=args.fixture,
                               imports=args.imports.resolve(strict=True), supervisor=args.supervisor,
                               output=output, source=args.source, timeout=args.timeout, profile=args.profile,
                               log_level=args.log_level)
    print(json.dumps({key: result.get(key) for key in ("status", "error", "oracles")}, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
