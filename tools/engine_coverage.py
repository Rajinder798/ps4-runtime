# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Statically compare declared SCE imports with the research engine's registered HLE symbols.

The pinned shadPS4 linker resolves an import when an HLE registration has the same
NID, library name and module name (versions and symbol type are ignored). This tool
reads `LIB_FUNCTION`/`LIB_OBJ` registrations as source text and reports each import
with no registration. It is a prediction, not a run: registrations behind runtime
settings or conditional compilation are counted wherever they appear, firmware
(LLE) modules are not modelled, and a registered symbol may still be a stub.

  prepare --destination DIR [--unpatched]   fetch the pinned source (git, network)
  report --source DIR --imports FILE [--json]
"""
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

import research_contract

ROOT = Path(__file__).resolve().parents[1]
REGISTRATION = re.compile(r'\bLIB_(FUNCTION|OBJ)\(\s*"([^"]*)"\s*,\s*"([^"]*)"\s*,\s*(\d+)\s*,\s*"([^"]*)"\s*,')
MACRO_USE = re.compile(r'\bLIB_(?:FUNCTION|OBJ)\(')
STUB = re.compile(r'^STUB\("([^"]+)",\s*([^)\s]+)\)', re.MULTILINE)


def registrations(source):
    """Map (nid, library, module) to its registration sites under source/src."""
    found = {}
    for path in sorted((Path(source) / "src").rglob("*")):
        if path.suffix not in (".cpp", ".h", ".inc") or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        matches = list(REGISTRATION.finditer(text))
        uses = len(MACRO_USE.findall(text)) - text.count("#define LIB_")
        if len(matches) != uses:
            raise ValueError(f"{path}: {uses} registration macros but {len(matches)} parsed")
        for match in matches:
            kind, nid, library, _, module = match.groups()
            line = text.count("\n", 0, match.start()) + 1
            found.setdefault((nid, library, module), []).append(
                {"kind": kind.lower(), "site": f"{path.relative_to(source).as_posix()}:{line}"})
    if not found:
        raise ValueError("No LIB_FUNCTION/LIB_OBJ registrations found; is this the engine source root?")
    return found


def nid_names(source):
    table = Path(source) / "src/core/aerolib/aerolib.inl"
    return dict(STUB.findall(table.read_text(encoding="utf-8", errors="replace"))) if table.exists() else {}


def coverage(inventory, found, names):
    if inventory.get("operation") != "imports" or inventory.get("schema_version") != 1:
        raise ValueError("Expected `ps4-runtime imports --json` output (schema 1)")
    missing = [{"nid": entry["nid"], "name": names.get(entry["nid"]), "library": entry["library"],
                "module": entry["module"], "type": entry["type"]}
               for entry in inventory["imports"]
               if (entry["nid"], entry["library"], entry["module"]) not in found]
    return {"schema_version": 1, "operation": "engine_import_coverage",
            "registrations": sum(len(sites) for sites in found.values()), "registered_symbols": len(found),
            "imports": len(inventory["imports"]), "registered_imports": len(inventory["imports"]) - len(missing),
            "missing_count": len(missing), "missing": missing, "static_prediction_only": True,
            "execution_performed": False}


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
                          timeout=600).stdout.strip()


def prepare(destination, patched):
    """Fetch the pinned revision; with patched=True, apply the reviewed research patch and
    require the exact tree recorded in config/startup-research.json."""
    destination = Path(destination)
    if destination.exists() and any(destination.iterdir()):
        raise ValueError(f"{destination} is not empty; refusing to reuse or overwrite it")
    lock = json.loads((ROOT / "config/upstream-lock.json").read_text(encoding="utf-8"))["shadps4"]
    contract = json.loads((ROOT / "config/startup-research.json").read_text(encoding="utf-8"))
    if contract["upstream_revision"] != lock["revision"]:
        raise ValueError("Research patch targets a different upstream revision")
    destination.mkdir(parents=True, exist_ok=True)
    git("init", "-q", cwd=destination)
    git("remote", "add", "origin", lock["repository"], cwd=destination)
    git("fetch", "-q", "--depth=1", "origin", lock["revision"], cwd=destination)
    git("checkout", "-q", "--detach", "FETCH_HEAD", cwd=destination)
    if git("rev-parse", "HEAD", cwd=destination) != lock["revision"]:
        raise ValueError("Fetched revision differs from the lock")
    if not patched:
        return git("write-tree", cwd=destination)
    patch = ROOT / contract["patch_path"]
    git("apply", "--check", str(patch), cwd=destination)
    git("apply", "--index", str(patch), cwd=destination)
    for key, name in research_contract.HEADERS:
        shutil.copyfile(ROOT / contract[f"{key}_path"], destination / "src/core" / name)
        git("add", f"src/core/{name}", cwd=destination)
    research_contract.verify(destination)
    return git("write-tree", cwd=destination)


def to_text(report):
    lines = [f"Engine import coverage (static prediction): {report['registered_imports']} of "
             f"{report['imports']} imports have an HLE registration"]
    lines += [f"  missing {m['nid']} {m['name'] or '(unknown name)'} {m['library']} {m['module']} {m['type']}"
              for m in report["missing"]]
    lines.append("Source text only; nothing was built, resolved or executed.")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    fetch = commands.add_parser("prepare")
    fetch.add_argument("--destination", type=Path, required=True)
    fetch.add_argument("--unpatched", action="store_true")
    show = commands.add_parser("report")
    show.add_argument("--source", type=Path, required=True)
    show.add_argument("--imports", type=Path, required=True)
    show.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.command == "prepare":
        print(json.dumps({"source": str(args.destination), "patched": not args.unpatched,
                          "tree": prepare(args.destination, not args.unpatched)}))
        return
    report = coverage(json.loads(args.imports.read_text(encoding="utf-8")),
                      registrations(args.source), nid_names(args.source))
    sys.stdout.write(json.dumps(report, indent=2) + "\n" if args.json else to_text(report))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError, subprocess.CalledProcessError) as error:
        sys.exit(f"engine coverage error: {error}")
