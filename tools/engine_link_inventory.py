# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Inventory what the strict research engine actually links and loads, and check it.

Reads the engine's linker map (every static library that contributed a symbol),
the executable's PE import tables (every DLL it loads at startup, including
delay-loaded ones) and the compiled-in fonts/resources. Each item must match the
reviewed table in config/engine-link-components.json, whose notice files and assets
are pinned by hash in the pinned upstream checkout (or, for a dependency CMake
downloads at configure time, in the engine build directory, with the download
declaration itself pinned). Anything unmapped, stale, changed or unexpected fails.

This is release-audit evidence (hold 3, "Windows link-graph review"). It records
license facts and the obligations they raise; it does not approve redistribution.
Header-only code compiled into the engine's own objects is not visible in a link
map and is out of scope here.
"""
import argparse
from collections import Counter
import fnmatch
import hashlib
import json
from pathlib import Path
import re
import struct
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/engine-link-components.json"
SYMBOL_LINE = re.compile(r"^\s*[0-9a-fA-F]{4}:[0-9a-fA-F]{8}\s+\S+\s+[0-9a-fA-F]+\s+(?:f\s+)?(?:i\s+)?(\S+)\s*$")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def map_contributions(text):
    """(symbols per static library, symbols from the engine's own objects) from an MSVC-style map."""
    if "Publics by Value" not in text:
        raise ValueError("Not a linker map with a public symbol table")
    libraries, own = Counter(), 0
    for line in text.splitlines():
        match = SYMBOL_LINE.match(line)
        if not match:
            continue
        origin = match.group(1)
        if origin.startswith("<"):
            continue  # <absolute>, <linker-defined>
        if ":" in origin:
            libraries[origin.split(":", 1)[0]] += 1
        else:
            own += 1
    if not libraries or not own:
        raise ValueError("Linker map has no library or object contributions")
    return dict(libraries), own


def pe_imports(blob):
    """DLL names from a PE32+ file's import and delay-import tables: (normal, delayed)."""
    def u16(o): return struct.unpack_from("<H", blob, o)[0]
    def u32(o): return struct.unpack_from("<I", blob, o)[0]
    if blob[:2] != b"MZ":
        raise ValueError("Not a PE file")
    pe = u32(0x3C)
    if blob[pe:pe + 4] != b"PE\0\0":
        raise ValueError("Missing PE signature")
    sections, optional_size = u16(pe + 6), u16(pe + 20)
    optional = pe + 24
    if u16(optional) != 0x20B:
        raise ValueError("Only PE32+ executables are supported")
    count = u32(optional + 108)
    directories = [(u32(optional + 112 + 8 * i), u32(optional + 116 + 8 * i)) for i in range(min(count, 16))]
    table = optional + optional_size
    spans = []
    for i in range(sections):
        entry = table + 40 * i
        virtual_size, address, raw_size, raw = u32(entry + 8), u32(entry + 12), u32(entry + 16), u32(entry + 20)
        spans.append((address, max(virtual_size, raw_size), raw))

    def offset(rva):
        for address, size, raw in spans:
            if address <= rva < address + size:
                return raw + rva - address
        raise ValueError(f"RVA {rva:#x} is outside every section")

    def name(rva):
        start = offset(rva)
        end = blob.index(b"\0", start)
        return blob[start:end].decode("ascii")

    def walk(index, size, name_field):
        names = []
        if len(directories) <= index or not directories[index][0]:
            return names
        position = offset(directories[index][0])
        while True:
            entry = blob[position:position + size]
            if len(entry) < size:
                raise ValueError("Truncated import table")
            if not any(entry):
                return names
            names.append(name(struct.unpack_from("<I", entry, name_field)[0]))
            position += size

    return walk(1, 20, 12), walk(13, 32, 4)


def reuse_declarations(path):
    """path -> SPDX-License-Identifier from a REUSE.toml's annotations."""
    declared = {}
    for annotation in tomllib.loads(Path(path).read_text(encoding="utf-8")).get("annotations", []):
        paths = annotation["path"] if isinstance(annotation["path"], list) else [annotation["path"]]
        for item in paths:
            declared[item] = annotation.get("SPDX-License-Identifier")
    return declared


def resolve(path, source, build):
    """Notice paths are relative to the upstream checkout, or to the engine build directory with a `build:` prefix."""
    if path.startswith("build:"):
        if build is None:
            raise ValueError("A build-directory notice needs the engine build directory")
        return build / path[len("build:"):]
    return source / path


def inventory(*, libraries, own_symbols, dlls, delayed, config, source, build=None):
    """Check contributions against the reviewed table; return the report (status passed/failed)."""
    errors, components = [], {}
    owners = {}
    for library in sorted(libraries):
        matches = [cid for cid, c in config["components"].items()
                   if any(fnmatch.fnmatchcase(library, pattern) for pattern in c["libraries"])]
        if len(matches) != 1:
            errors.append(f"Linked library {library} matches {len(matches)} reviewed components")
            continue
        owners[library] = matches[0]
    for cid, component in config["components"].items():
        linked = {lib: libraries[lib] for lib, owner in owners.items() if owner == cid}
        if not linked:
            errors.append(f"Reviewed component {cid} is not linked (stale entry)")
        unknown_flags = set(component["flags"]) - set(config["flags"])
        if unknown_flags:
            errors.append(f"Component {cid} uses undefined flags {sorted(unknown_flags)}")
        notices = ([dict(path=component["notice"], sha256=component["notice_sha256"])] if component["notice"] else [])
        notices += component.get("extra_notices", [])
        if component["kind"] in ("upstream-static", "prebuilt-static", "fetched-static") and not component["notice"]:
            errors.append(f"Component {cid} has no notice file")
        if component["kind"] == "fetched-static":
            fetch = component.get("fetch") or {}
            declaration = source / fetch.get("declared_by", "")
            if not fetch.get("declared_by") or not declaration.is_file() or digest(declaration) != fetch.get("declared_by_sha256"):
                errors.append(f"Download declaration missing or changed for {cid}")
            else:
                text = declaration.read_text(encoding="utf-8", errors="replace")
                if fetch["url"] not in text or fetch["sha256"].lower() not in text.lower():
                    errors.append(f"Download declaration for {cid} does not name the recorded URL and hash")
        for notice in notices:
            try:
                path = resolve(notice["path"], source, build)
            except ValueError as error:
                errors.append(f"{error}: {cid}")
                continue
            if not path.is_file():
                errors.append(f"Notice missing for {cid}: {notice['path']}")
            elif digest(path) != notice["sha256"]:
                errors.append(f"Notice changed for {cid}: {notice['path']}")
        components[cid] = dict(kind=component["kind"], license=component["license"], flags=component["flags"],
                               notice=component["notice"], libraries=linked, symbols=sum(linked.values()),
                               **({"fetch": component["fetch"]} if "fetch" in component else {}))
    declared = reuse_declarations(source / "REUSE.toml")
    assets = []
    for asset in config["assets"]:
        path = source / asset["path"]
        if not path.is_file() or digest(path) != asset["sha256"]:
            errors.append(f"Compiled-in asset missing or changed: {asset['path']}")
        if declared.get(asset["path"]) != asset["declared_license"]:
            errors.append(f"Upstream REUSE.toml does not declare {asset['declared_license']} for {asset['path']}")
        assets.append(dict(path=asset["path"], license=asset["declared_license"]))
    loaded = {}
    for dll in sorted({d.lower() for d in dlls} | {d.lower() for d in delayed}):
        categories = [category for category, patterns in config["allowed_dlls"].items()
                      if any(fnmatch.fnmatchcase(dll, pattern.lower()) for pattern in patterns)]
        if not categories:
            errors.append(f"Unexpected DLL import: {dll}")
            continue
        loaded.setdefault(categories[0], []).append(dll)
    flagged = {flag: sorted(cid for cid, c in components.items() if flag in c["flags"]) for flag in config["flags"]}
    return dict(schema_version=1, status="failed" if errors else "passed", errors=errors,
                upstream_revision=config["upstream_revision"], components=components,
                own_object_symbols=own_symbols, library_count=len(libraries),
                dll_imports=loaded, delay_loaded=sorted(d.lower() for d in delayed),
                third_party_dlls_imported=[d for c, names in loaded.items() if c not in ("windows-system", "msvc-runtime") for d in names],
                assets=assets, obligations={flag: dict(meaning=config["flags"][flag], components=ids)
                                            for flag, ids in flagged.items() if ids},
                out_of_scope=["Header-only code compiled into the engine's own objects",
                              "Runtime-loaded libraries (for example the Vulkan loader and drivers)",
                              "Transitive notices inside each component beyond those listed"],
                upstream_redistribution_approved=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for name in ("map", "engine", "engine-report", "source", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--build", type=Path, help="engine build directory for build: notices (default: the engine's folder)")
    parser.add_argument("--config", type=Path, default=CONFIG)
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    report = json.loads(args.engine_report.read_text(encoding="utf-8"))
    engine_sha = digest(args.engine)
    libraries, own = map_contributions(args.map.read_text(encoding="utf-8", errors="replace"))
    dlls, delayed = pe_imports(args.engine.read_bytes())
    result = inventory(libraries=libraries, own_symbols=own, dlls=dlls, delayed=delayed, config=config,
                       source=args.source.resolve(), build=(args.build or args.engine.parent).resolve())
    if report.get("executable_sha256") != engine_sha:
        result["errors"].append("Engine does not match the strict build report")
    if report.get("upstream_revision") != config["upstream_revision"]:
        result["errors"].append("Strict build report names a different upstream revision")
    result.update(status="failed" if result["errors"] else "passed", engine_sha256=engine_sha,
                  map_sha256=digest(args.map), patched_tree=report.get("patched_tree"),
                  config_sha256=digest(args.config))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("status", "errors", "library_count", "third_party_dlls_imported")}, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
