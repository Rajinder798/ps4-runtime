# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
"""V2-only adapter; historical startup verifier remains frozen."""
import json
from pathlib import Path
from run_homebrew_startup import digest
ROOT = Path(__file__).resolve().parents[1]

def verify_inputs(engine, engine_report, fixture, profile="live-av-v2"):
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
    if profile != "live-av-v2":
        raise ValueError("Only the independent live-av-v2 profile is supported")
    fixture_contract = json.loads((ROOT / "config/live-av-v2.json").read_text())
    if (fixture_contract["schema_version"] != 1 or
            digest(ROOT / "research/homebrew/live_av_v2/main.cpp") != fixture_contract["source_sha256"]):
        raise ValueError("Reviewed v2 source checksum mismatch")
    fixture_hash = fixture_contract["oelf_sha256"]
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
