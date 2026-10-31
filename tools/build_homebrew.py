# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Build release-pinned OpenOrbis hello_world or reviewed original fixtures.

Requires Python 3.12+, Windows x86-64, LLVM with FreeBSD ELF support, and the
runtime CLI for structural inspection. It does not launch the homebrew.
"""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile

from upstream_baseline import ROOT, WORK, LOCK_PATH, command, digest, download
from elf_relocations import read_program_headers, read_relocations
from make_sce_imports import name_to_nid


def sdk_inputs(archive, sdk):
    prefix = "OpenOrbis/PS4Toolchain/"
    required = ("include/", "lib/", "samples/hello_world/hello_world/main.cpp",
                "samples/_common/log.h", "link.x", "bin/windows/create-fself.exe")
    records = []
    with tarfile.open(archive, "r:gz") as bundle:
        for member in bundle:
            name = member.name.removeprefix(prefix)
            if not member.name.startswith(prefix) or not member.isfile() or not name.startswith(required):
                continue
            with bundle.extractfile(member) as stream:
                expected = hashlib.file_digest(stream, "sha256").hexdigest()
            path = sdk / name
            if not path.is_file() or digest(path) != expected:
                raise RuntimeError(f"SDK input differs from the verified archive: {name}")
            records.append((name, expected))
    if not records:
        raise RuntimeError("No SDK inputs found in the expected archive layout.")
    checksum = hashlib.sha256()
    for name, expected in sorted(records):
        checksum.update(f"{name}\0{expected}\n".encode())
    return {"verified_file_count": len(records), "tree_sha256": checksum.hexdigest()}


def import_cross_check(names, inventory):
    """Compare pre-conversion import names with the converted file's declared NIDs."""
    expected = {name_to_nid(name): name for name in names}
    declared = {entry["nid"] for entry in inventory["imports"]}
    result = {"pre_conversion_names": len(names), "declared_imports": len(inventory["imports"]),
              "missing_names": sorted(name for nid, name in expected.items() if nid not in declared),
              "unexpected_nids": sorted(declared - set(expected)),
              "other_undefined": inventory["other_undefined"]}
    # Equal counts also catch duplicated or collapsed NIDs that set comparison alone would hide.
    result["matched"] = (len(names) == len(inventory["imports"]) and
                         not (result["missing_names"] or result["unexpected_nids"] or result["other_undefined"]))
    return result


def relocation_cross_check(entries, inventory):
    """Compare pre-conversion RELA entries with the converted file's declared relocations.

    Symbols are compared by NID: pre-conversion names are hashed, and converted
    names use their NID#library#module prefix (or are hashed if not in that form).
    """
    def nid(symbol):
        parts = symbol.split("#")
        return "" if not symbol else parts[0] if len(parts) == 3 else name_to_nid(symbol)

    expected = Counter((e["table"], e["offset"], e["type_id"], name_to_nid(e["symbol"]) if e["symbol"] else "",
                        e["addend"]) for e in entries)
    declared = Counter((r["table"], r["offset"], r["type_id"], nid(r["symbol"]), r["addend"])
                       for r in inventory["relocations"])
    missing, unexpected = sorted((expected - declared).elements()), sorted((declared - expected).elements())
    return {"pre_conversion_entries": len(entries), "declared_relocations": len(inventory["relocations"]),
            "types": dict(sorted(Counter(r["type"] for r in inventory["relocations"]).items())),
            "missing_count": len(missing), "unexpected_count": len(unexpected),
            "missing": [list(k) for k in missing[:20]], "unexpected": [list(k) for k in unexpected[:20]],
            "matched": not (missing or unexpected)}


def startup_cross_check(headers, entries, startup):
    """Compare the converted file's TLS template, TLS relocations and process-parameter
    location with the pre-conversion ELF's program headers and RELA sections.

    TLS address and sizes must be identical. The converter may only make the TLS
    alignment stricter: a power of two that is a multiple of the original (the
    pinned create-fself raises 8 to 32).
    """
    tls = [h for h in headers if h["type"] == 7]
    params = [h for h in headers if h["type"] == 0x61000001]
    expected_tls = (None if not tls else
                    {k: tls[0][k] for k in ("address", "file_size", "memory_size", "alignment")})
    declared = startup["tls"]
    declared_tls = (None if declared is None else
                    {"address": declared["address"], "file_size": declared["init_size"],
                     "memory_size": declared["memory_size"], "alignment": declared["alignment"]})

    def same_tls():
        if expected_tls is None or declared_tls is None:
            return expected_tls == declared_tls
        before, after = max(expected_tls["alignment"], 1), max(declared_tls["alignment"], 1)
        return (all(expected_tls[k] == declared_tls[k] for k in ("address", "file_size", "memory_size")) and
                after & (after - 1) == 0 and after % before == 0)

    expected_relocations = {name: sum(e["type_id"] == kind for e in entries) for kind, name in
                            ((16, "R_X86_64_DTPMOD64"), (17, "R_X86_64_DTPOFF64"), (18, "R_X86_64_TPOFF64"))}
    param = startup["process_param"]
    result = {"pre_conversion_tls": expected_tls, "declared_tls": declared_tls,
              "pre_conversion_tls_relocations": expected_relocations,
              "declared_tls_relocations": startup["tls_relocations"],
              "pre_conversion_process_param_addresses": [h["address"] for h in params],
              "declared_process_param": param,
              "tls_alignment_raised": bool(expected_tls and declared_tls and
                                           declared_tls["alignment"] != expected_tls["alignment"])}
    result["matched"] = (len(tls) <= 1 and same_tls() and
                         expected_relocations == startup["tls_relocations"] and param is not None and
                         (not params or [h["address"] for h in params] == [param["address"]]))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--llvm-bin", type=Path, required=True)
    parser.add_argument("--inspector", type=Path, required=True)
    parser.add_argument("--sample", choices=("hello-world", "service-roundtrip", "videoout-pattern", "pad-videoout", "audio-pattern", "interactive-av", "live-av", "pad-axes", "pad-hotplug-av", "live-av-v2"), default="hello-world")
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("This validated recipe currently targets Windows x86-64.")
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))["homebrew"]
    archive = WORK / "downloads" / "toolchain-llvm-18.tar.gz"
    download(lock["toolchain_url"], archive, lock["toolchain_sha256"])
    extraction = WORK / "openorbis-release"
    if not extraction.exists():
        extraction.mkdir(parents=True)
        with tarfile.open(archive, "r:gz") as bundle:
            bundle.extractall(extraction, filter="data")
    sdk = extraction / "OpenOrbis" / "PS4Toolchain"
    verified = sdk_inputs(archive, sdk)
    llvm = args.llvm_bin.resolve()
    compiler, linker, readelf = (llvm / name for name in ("clang++.exe", "ld.lld.exe", "llvm-readelf.exe"))
    inspector = args.inspector.resolve()
    output = ROOT / "build" / "homebrew" / args.sample
    output.mkdir(parents=True, exist_ok=True)
    basename = args.sample.replace("-", "_")
    sample = lock if args.sample == "hello-world" else {
        "source": f"research/homebrew/{basename}/main.cpp", "license": "GPL-2.0-or-later",
        "toolchain_release": lock["release_tag"], "toolchain_sha256": lock["toolchain_sha256"]}
    report = {"sample": sample, "sdk_inputs": verified, "status": "preparing", "guest_execution_tested": False}
    try:
        report["tools"] = {"compiler": command(compiler, "--version", capture=True),
                           "linker": command(linker, "--version", capture=True)}
        source = (sdk / lock["sample"] / "hello_world" / "main.cpp" if args.sample == "hello-world"
                  else ROOT / sample["source"])
        report["fixture_profile"] = args.sample
        report["main_cpp_sha256"] = digest(source)
        command(compiler, "--no-default-config", "--target=x86_64-pc-freebsd12-elf", "-fPIC", "-funwind-tables",
                "-nostdinc++", "-isysroot", sdk, "-isystem", sdk / "include",
                "-isystem", sdk / "include/c++/v1", "-c", source, "-o", output / "main.o")
        command(linker, "-m", "elf_x86_64", "-pie", "--script", sdk / "link.x", "--eh-frame-hdr",
                f"-L{sdk / 'lib'}", output / "main.o", sdk / "lib/crt1.o", "-lc", "-lkernel", "-lc++",
                *(["-lSceVideoOut"] if args.sample in ("videoout-pattern", "pad-videoout", "interactive-av", "live-av", "pad-axes", "pad-hotplug-av", "live-av-v2") else []),
                *(["-lScePad", "-lSceUserService"] if args.sample in ("pad-videoout", "interactive-av", "live-av", "pad-axes", "pad-hotplug-av", "live-av-v2") else []),
                *(["-lSceAudioOut", "-lSceUserService"] if args.sample == "audio-pattern" else []),
                *(["-lSceAudioOut"] if args.sample in ("interactive-av", "live-av", "pad-hotplug-av", "live-av-v2") else []),
                "-o", output / (basename + ".elf"))
        # This environment change is process-local, not a machine installation.
        os.environ["OO_PS4_TOOLCHAIN"] = str(sdk)
        # The converter embeds the input filename. Use a canonical basename so
        # different checkout locations do not change its module metadata.
        command(sdk / "bin/windows/create-fself.exe", "-in", basename + ".elf",
                "-out", basename + ".oelf", "--eboot", "eboot.bin", "--paid", "0x3800000000000011", cwd=output)
        inspection = command(inspector, "inspect", output / (basename + ".oelf"), "--json", capture=True)
        report["inspection"] = json.loads(inspection)
        if report["inspection"]["type"] != "ET_SCE_DYNEXEC":
            raise RuntimeError("Homebrew conversion did not produce ET_SCE_DYNEXEC.")
        symbols = command(readelf, "--dyn-syms", output / (basename + ".elf"), capture=True)
        (output / "dynamic-symbols.txt").write_text(symbols + "\n", encoding="utf-8")
        report["undefined_dynamic_symbols"] = sorted(re.findall(r"\bUND[ \t]+(\S+)[ \t]*$", symbols, re.MULTILINE))
        # Read-only declared-import inventory of the converted file; nothing is resolved or executed.
        inventory = json.loads(command(inspector, "imports", output / (basename + ".oelf"), "--json", capture=True))
        (output / "sce-imports.json").write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
        report["sce_import_cross_check"] = import_cross_check(report["undefined_dynamic_symbols"], inventory)
        if not report["sce_import_cross_check"]["matched"]:
            raise RuntimeError("Converted SCE imports differ from the pre-conversion undefined symbols.")
        # Read-only declared-relocation inventory; nothing is applied. The oracle reads the
        # pre-conversion ELF's standard RELA sections independently of the SCE tables.
        relocations = json.loads(command(inspector, "relocations", output / (basename + ".oelf"), "--json",
                                         capture=True))
        (output / "sce-relocations.json").write_text(json.dumps(relocations, indent=2) + "\n", encoding="utf-8")
        report["sce_relocation_cross_check"] = relocation_cross_check(
            read_relocations(output / (basename + ".elf")), relocations)
        if not report["sce_relocation_cross_check"]["matched"]:
            raise RuntimeError("Converted SCE relocations differ from the pre-conversion RELA sections.")
        # Read-only startup metadata: TLS template, TLS relocations and process parameters.
        startup = json.loads(command(inspector, "startup", output / (basename + ".oelf"), "--json", capture=True))
        (output / "sce-startup.json").write_text(json.dumps(startup, indent=2) + "\n", encoding="utf-8")
        report["sce_startup_cross_check"] = startup_cross_check(
            read_program_headers(output / (basename + ".elf")), read_relocations(output / (basename + ".elf")),
            startup)
        if not report["sce_startup_cross_check"]["matched"]:
            raise RuntimeError("Converted SCE startup metadata differs from the pre-conversion ELF.")
        rejection = subprocess.run([str(inspector), "probe", str(output / (basename + ".oelf"))],
                                   capture_output=True, text=True, check=False, timeout=10)
        if rejection.returncode != 1 or "error[unsupported_mapping_alignment]" not in rejection.stderr:
            raise RuntimeError("Expected the restricted probe mapper to reject this sample's 16 KiB alignment.")
        report["probe_rejection"] = rejection.stderr.strip()
        report["artifacts"] = {name: {"sha256": digest(output / name), "size": (output / name).stat().st_size}
                               for name in (basename + ".elf", basename + ".oelf", "eboot.bin")}
        if args.sample != "hello-world":
            contract = json.loads((ROOT / f"config/{args.sample}.json").read_text())
            if (report["main_cpp_sha256"] != contract["source_sha256"] or
                    report["artifacts"][basename + ".oelf"]["sha256"] != contract["oelf_sha256"]):
                raise RuntimeError("Fixture differs from its reviewed source/binary contract")
        report["status"] = "built_and_inspected_not_executed"
    except Exception as error:
        report.update({"status": "failed", "error": str(error)})
        raise
    finally:
        (output / "build-evidence.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "artifacts": report["artifacts"]}, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, subprocess.CalledProcessError) as error:
        sys.exit(f"homebrew build error: {error}")
