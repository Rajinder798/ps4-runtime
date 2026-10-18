# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Build the release-pinned OpenOrbis hello_world outside the runtime source tree.

Requires Python 3.12+, Windows x86-64, LLVM with FreeBSD ELF support, and the
runtime CLI for structural inspection. It does not launch the homebrew.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile

from upstream_baseline import ROOT, WORK, LOCK_PATH, command, digest, download


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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--llvm-bin", type=Path, required=True)
    parser.add_argument("--inspector", type=Path, required=True)
    parser.add_argument("--sample", choices=("hello-world", "service-roundtrip"), default="hello-world")
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
    sample = lock if args.sample == "hello-world" else {
        "source": "research/homebrew/service_roundtrip/main.cpp", "license": "GPL-2.0-or-later",
        "toolchain_release": lock["release_tag"], "toolchain_sha256": lock["toolchain_sha256"]}
    report = {"sample": sample, "sdk_inputs": verified, "status": "preparing", "guest_execution_tested": False}
    try:
        report["tools"] = {"compiler": command(compiler, "--version", capture=True),
                           "linker": command(linker, "--version", capture=True)}
        source = (sdk / lock["sample"] / "hello_world" / "main.cpp" if args.sample == "hello-world"
                  else ROOT / "research/homebrew/service_roundtrip/main.cpp")
        basename = "hello_world" if args.sample == "hello-world" else "service_roundtrip"
        report["fixture_profile"] = args.sample
        report["main_cpp_sha256"] = digest(source)
        command(compiler, "--no-default-config", "--target=x86_64-pc-freebsd12-elf", "-fPIC", "-funwind-tables",
                "-nostdinc++", "-isysroot", sdk, "-isystem", sdk / "include",
                "-isystem", sdk / "include/c++/v1", "-c", source, "-o", output / "main.o")
        command(linker, "-m", "elf_x86_64", "-pie", "--script", sdk / "link.x", "--eh-frame-hdr",
                f"-L{sdk / 'lib'}", output / "main.o", sdk / "lib/crt1.o", "-lc", "-lkernel", "-lc++",
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
        rejection = subprocess.run([str(inspector), "probe", str(output / (basename + ".oelf"))],
                                   capture_output=True, text=True, check=False, timeout=10)
        if rejection.returncode != 1 or "error[unsupported_mapping_alignment]" not in rejection.stderr:
            raise RuntimeError("Expected the restricted probe mapper to reject this sample's 16 KiB alignment.")
        report["probe_rejection"] = rejection.stderr.strip()
        report["artifacts"] = {name: {"sha256": digest(output / name), "size": (output / name).stat().st_size}
                               for name in (basename + ".elf", basename + ".oelf", "eboot.bin")}
        if args.sample == "service-roundtrip":
            contract = json.loads((ROOT / "config/service-roundtrip.json").read_text())
            if (report["main_cpp_sha256"] != contract["source_sha256"] or
                    report["artifacts"][basename + ".oelf"]["sha256"] != contract["oelf_sha256"]):
                raise RuntimeError("Second fixture differs from its reviewed source/binary contract")
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
