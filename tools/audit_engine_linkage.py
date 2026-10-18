# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Check active CMake targets/sources/link inputs and the actual Windows link map."""
import argparse
import json
from pathlib import Path
import re


def forbidden(value):
    value = value.lower().replace("\\", "/")
    return "fdk-aac" in value or "/aacdec/" in value


def inspect(targets, link_map):
    if not targets or len(link_map) < 4096:
        raise ValueError("Incomplete build/link evidence")
    engine = None
    for target in targets:
        if forbidden(target["name"]):
            raise ValueError("FDK target remains configured")
        for source in target.get("sources", []):
            if forbidden(source["path"]):
                raise ValueError("FDK source remains active")
        for group in target.get("compileGroups", []):
            if any(forbidden(include["path"]) for include in group.get("includes", [])):
                raise ValueError("FDK include path remains active")
        for item in target.get("link", {}).get("commandFragments", []):
            if forbidden(item["fragment"]):
                raise ValueError("FDK link input remains active")
        if target["name"] == "shadps4":
            engine = target
    if not engine:
        raise ValueError("Engine target missing")
    if forbidden(link_map) or re.search(r"\baacDecoder_[A-Za-z0-9_]+|\bCAacDecoder_Init\b", link_map):
        raise ValueError("FDK objects/symbols remain linked")
    if "ff_aac_decoder" not in link_map or "AjmAacDecoder" not in link_map:
        raise ValueError("Native AAC/adapter symbols missing")
    return dict(schema_version=1, status="passed", configured_targets_checked=len(targets),
                fdk_target_absent=True, fdk_sources_absent=True, fdk_includes_absent=True,
                fdk_link_inputs_absent=True, fdk_symbols_absent=True, native_aac_and_ajm_linked=True,
                upstream_redistribution_approved=False)


def audit(binary):
    reply = binary / ".cmake/api/v1/reply"
    # CMake removes obsolete index files when writing a new reply.
    indices = list(reply.glob("index-*.json"))
    if len(indices) != 1:
        raise ValueError("Ambiguous/missing CMake file-API index")
    index = json.loads(indices[0].read_text())
    model = json.loads((reply / index["reply"]["codemodel-v2"]["jsonFile"]).read_text())
    configurations = model["configurations"]
    if len(configurations) != 1:
        raise ValueError("Expected the single-config research build")
    targets = [json.loads((reply / entry["jsonFile"]).read_text())
               for entry in configurations[0]["targets"]]
    link_map = (binary / "ps4-runtime-research.map").read_text(encoding="utf-8", errors="strict")
    return inspect(targets, link_map)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.build.resolve())
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))
