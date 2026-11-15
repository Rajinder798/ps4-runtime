# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Shared check that an engine is the reviewed build of a named engine variant.

Used by the research runners when they are pointed at a variant engine (for
example release-no-libressl) instead of the strict research engine. The variant
and its contract file come from config/engine-link-components.json; nothing is
inferred from the variant's name.
"""
import hashlib
import json
from pathlib import Path


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_engine(root, engine_sha256, report, variant, strict):
    """Raise ValueError unless report describes the reviewed build of variant; return its contract.

    root: repository root. engine_sha256: hash of the engine file actually being run.
    report: the variant build report (dict). strict: config/startup-research.json (dict).
    """
    root = Path(root)
    table = json.loads((root / "config/engine-link-components.json").read_text(encoding="utf-8"))
    entry = table.get("variants", {}).get(variant)
    if entry is None:
        raise ValueError(f"Unknown engine variant: {variant}")
    if "contract" not in entry or not (root / entry["contract"]).is_file():
        raise ValueError(f"Variant contract not found for {variant}")
    contract = json.loads((root / entry["contract"]).read_text(encoding="utf-8"))
    base = contract["base"]
    if (base["upstream_revision"] != strict["upstream_revision"] or
            base["expected_patched_tree"] != strict["expected_patched_tree"] or
            any(base[key] != strict[key] for key in
                ("patch_sha256", "audit_header_sha256", "services_header_sha256", "aac_header_sha256"))):
        raise ValueError("Release variant base differs from the strict research contract")
    expected = {
        "status": "release_variant_engine_built",
        "upstream_revision": base["upstream_revision"],
        "patch_sha256": base["patch_sha256"],
        "audit_header_sha256": base["audit_header_sha256"],
        "services_header_sha256": base["services_header_sha256"],
        "aac_header_sha256": base["aac_header_sha256"],
        "strict_tree": base["expected_patched_tree"],
        "release_variant_patch_sha256": contract["patch_sha256"],
        "release_variant_header_sha256": contract["header_sha256"],
        "patched_tree": contract["expected_tree"],
        "cmake_defines": contract["cmake_defines"],
        "executable_sha256": engine_sha256,
    }
    if any(report.get(key) != value for key, value in expected.items()):
        raise ValueError("Engine does not match the release variant build evidence and locked patch")
    # Same post-build bar as the strict engine: AAC and host-exception suites passed, FDK absent.
    if (report.get("strict_tests_run") is not True or report.get("aac_tests", {}).get("status") != "passed" or
            report.get("host_exception_tests", {}).get("status") != "passed" or
            report.get("aac_backend") != "ffmpeg-aac-lc" or report.get("fdk_linkage_verified_absent") is not True):
        raise ValueError("Release variant build has not passed the strict AAC and host-exception suites")
    if _digest(root / contract["patch_path"]) != contract["patch_sha256"]:
        raise ValueError("Release variant patch checksum mismatch")
    if _digest(root / contract["header_path"]) != contract["header_sha256"]:
        raise ValueError("Release variant header checksum mismatch")
    return contract
