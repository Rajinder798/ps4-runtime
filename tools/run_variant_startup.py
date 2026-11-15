# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Bounded Windows research launch of an engine variant and sample.

A separate runner, like the save-roundtrip and live-av-v2 contracts:
the shared run_homebrew_startup.py is pinned by reviewed G4 records,
so its unchanged helpers (hashing, audit reading, session preparation
and supervision) are reused here.
"""
import argparse
import json
import math
from pathlib import Path
import platform
import shutil
import subprocess
import sys

import run_homebrew_startup as startup
import runtime_settings

ROOT = Path(__file__).resolve().parents[1]


def verify_inputs(engine, engine_report, fixture, profile="hello-world", variant="release-no-libressl"):
    audit = json.loads((ROOT / "config/g2-integration-audit.json").read_text(encoding="utf-8"))
    contract = json.loads((ROOT / "config/startup-research.json").read_text(encoding="utf-8"))
    report = json.loads(engine_report.read_text(encoding="utf-8"))

    components_path = ROOT / "config/engine-link-components.json"
    if not components_path.exists():
        raise ValueError("Engine link components config not found")
    components_config = json.loads(components_path.read_text(encoding="utf-8"))
    if variant not in components_config.get("variants", {}):
        raise ValueError(f"Unknown engine variant: {variant}")
    variant_contract_path = ROOT / "config/release-variant.json" if variant == "release-no-libressl" else ROOT / f"config/{variant}.json"
    if not variant_contract_path.exists():
        raise ValueError(f"Variant contract not found for {variant}")
    variant_contract = json.loads(variant_contract_path.read_text(encoding="utf-8"))
    base = variant_contract["base"]
    if (base["upstream_revision"] != contract["upstream_revision"] or
            base["patch_sha256"] != contract["patch_sha256"] or
            base["expected_patched_tree"] != contract["expected_patched_tree"] or
            base["audit_header_sha256"] != contract["audit_header_sha256"] or
            base["services_header_sha256"] != contract["services_header_sha256"] or
            base["aac_header_sha256"] != contract["aac_header_sha256"]):
        raise ValueError("Release variant base differs from the strict research contract")
    if (report.get("status") != "release_variant_engine_built" or
            report.get("upstream_revision") != base["upstream_revision"] or
            report.get("patch_sha256") != base["patch_sha256"] or
            report.get("audit_header_sha256") != base["audit_header_sha256"] or
            report.get("services_header_sha256") != base["services_header_sha256"] or
            report.get("aac_header_sha256") != base["aac_header_sha256"] or
            report.get("strict_tree") != base["expected_patched_tree"] or
            report.get("release_variant_patch_sha256") != variant_contract["patch_sha256"] or
            report.get("release_variant_header_sha256") != variant_contract["header_sha256"] or
            report.get("patched_tree") != variant_contract["expected_tree"] or
            report.get("cmake_defines") != variant_contract["cmake_defines"] or
            report.get("executable_sha256") != startup.digest(engine)):
        raise ValueError("Engine does not match the release variant build evidence and locked patch")
    if startup.digest(ROOT / contract["patch_path"]) != contract["patch_sha256"]:
        raise ValueError("Research patch checksum mismatch")
    if startup.digest(ROOT / contract["audit_header_path"]) != contract["audit_header_sha256"]:
        raise ValueError("Audit header checksum mismatch")
    if startup.digest(ROOT / contract["services_header_path"]) != contract["services_header_sha256"]:
        raise ValueError("Kernel services header checksum mismatch")
    if startup.digest(ROOT / contract["aac_header_path"]) != contract["aac_header_sha256"]:
        raise ValueError("AAC decoder header checksum mismatch")
    if startup.digest(ROOT / variant_contract["patch_path"]) != variant_contract["patch_sha256"]:
        raise ValueError("Release variant patch checksum mismatch")
    if startup.digest(ROOT / variant_contract["header_path"]) != variant_contract["header_sha256"]:
        raise ValueError("Release variant header checksum mismatch")

    if profile == "hello-world":
        fixture_hash = audit["fixture"]["oelf_sha256"]
    elif profile in ("service-roundtrip", "videoout-pattern", "pad-videoout", "audio-pattern", "interactive-av", "live-av", "pad-axes", "pad-hotplug-av"):
        fixture_contract = json.loads((ROOT / f"config/{profile}.json").read_text(encoding="utf-8"))
        if (fixture_contract["schema_version"] != 1 or
                startup.digest(ROOT / f"research/homebrew/{profile.replace('-', '_')}/main.cpp") != fixture_contract["source_sha256"]):
            raise ValueError("Reviewed fixture source checksum mismatch")
        fixture_hash = fixture_contract["oelf_sha256"]
    else:
        raise ValueError("Unknown fixture profile")
    if startup.digest(fixture) != fixture_hash:
        raise ValueError("Homebrew fixture hash differs from the selected build")
    return report


def run_attempt(*, engine, engine_report, fixture, supervisor, output, timeout=30, profile="hello-world", log_level=None, variant="release-no-libressl"):
    """Run in a caller-created empty output directory; return (exit code, evidence)."""
    if (not math.isfinite(timeout) or not 3 <= timeout <= 120 or
            profile not in ("hello-world", "service-roundtrip") or any(output.iterdir()) or
            (log_level is not None and log_level not in runtime_settings.LOG_LEVELS)):
        raise ValueError("A valid profile, timeout and empty output directory are required")
    result = {"schema_version": 1, "status": "failed", "g2_passed": False, "profile": profile,
              "variant": variant, "guest_execution_tested": False, "guest_entry_observed": False,
              "engine_launch_attempted": False, "host": platform.platform(),
              "cpu": platform.processor(), "timeout_seconds": timeout,
              "upstream_redistribution_approved": False}
    code = 1
    try:
        if sys.platform != "win32" or platform.machine().lower() not in ("amd64", "x86_64"):
            raise ValueError("Research runner requires Windows x86-64")
        engine, fixture, supervisor = (p.resolve(strict=True) for p in (engine, fixture, supervisor))
        result["build"] = verify_inputs(engine, engine_report.resolve(strict=True), fixture, profile, variant=variant)
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
        if log_level is not None:
            engine_settings = {"Log": {"filter": "*:" + log_level, "flush_level": "trace"}}
            (work / "user/config.json").write_text(json.dumps(engine_settings) + "\n", encoding="utf-8")
            result["requested_settings"] = {"log_level": log_level}
        if profile == "service-roundtrip":
            fixture, challenge = startup.prepare_service(work, fixture)
            if startup.digest(fixture) != result["fixture_sha256"]:
                raise ValueError("Staged fixture checksum mismatch")
        trace = work / "startup-audit.jsonl"
        command = [engine, "--game", fixture, "--ignore-game-patch", "--startup-audit", trace]
        result["command"] = list(map(str, command))
        result["engine_launch_attempted"] = True
        transport = startup.supervise(supervisor, command, work, timeout,
                                      lambda: startup.evaluate(startup.read_events(trace), profile)["markers_observed"])
        evidence = startup.evaluate(startup.read_events(trace, final=True), profile)
        result.update(transport=transport, guest_execution_tested=evidence["guest_entry_observed"], **evidence)
        if transport["reason"] != "requested" or not evidence["markers_observed"]:
            raise ValueError("Engine exited/timed out before the qualifying guest markers")
        if profile == "service-roundtrip":
            result["service_roundtrip"] = startup.verify_service(work, challenge)
        result.update(status="passed", g2_passed=True)
        code = 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        result["error"] = str(error)
    finally:
        if result["engine_launch_attempted"] and not result["g2_passed"]:
            try:
                startup.collect_failure_evidence(output, result)
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
    parser.add_argument("--variant", default="release-no-libressl", help="Engine variant name (default: release-no-libressl)")
    args = parser.parse_args()
    if not math.isfinite(args.timeout) or not 3 <= args.timeout <= 120:
        parser.error("--timeout must be finite and between 3 and 120 seconds")
    output = args.output.resolve()
    try:
        output.mkdir(parents=True, exist_ok=False)
    except OSError as error:
        parser.error(f"--output must be a new writable directory: {error}")
    code, result = run_attempt(engine=args.engine, engine_report=args.engine_report,
                               fixture=args.fixture, supervisor=args.supervisor, output=output,
                               timeout=args.timeout, profile=args.profile, variant=args.variant)
    print(json.dumps(result, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
