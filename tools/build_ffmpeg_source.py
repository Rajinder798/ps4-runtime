# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Build FFmpeg from the verified source kit and check it against the audited prebuilt.

Decision 0004 requires every binary release to ship the complete corresponding
source of the FFmpeg it links, so the engine cannot keep using the prebuilt
ext-ffmpeg-core archive. This builds the same FFmpeg 7.1.1 from the kit's patched
source with this script as the build recipe:

- the kit is verified first (every input checksum, patches reapplied);
- configure gets exactly the semantic flags the prebuilt libraries report about
  themselves (research/results/2026-10-18-ffmpeg-audit.json), plus the toolchain
  of the wrapper's x64-win-llvm-static-release triplet: clang-cl, llvm-lib,
  lld-link and the static C runtime (/MT);
- the result must pass the same metadata review as the prebuilt: library versions,
  matching headers, "LGPL version 2.1 or later", and identical semantic flags.

Run on Windows from the Visual Studio x64 developer environment with MSYS2 make,
nasm, pkgconf and diffutils installed. Nothing is downloaded. The output is a local
research build; it approves no redistribution.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess

import audit_ffmpeg
import ffmpeg_source_kit

ROOT = Path(__file__).resolve().parents[1]
RECORD = ROOT / "research/results/2026-10-18-ffmpeg-audit.json"
# Toolchain of the wrapper's x64-win-llvm-static-release triplet (not semantic configure flags), with
# one difference: MSVC lib.exe archives the objects. The triplet uses llvm-lib through automake's
# ar-lib wrapper; FFmpeg's configure recognises a lib-style archiver only by "Microsoft" in its output.
TOOLCHAIN = ["--toolchain=msvc", "--target-os=win32", "--arch=x86_64", "--cc=clang-cl", "--cxx=clang-cl",
             "--ld=lld-link", "--ar=lib", "--nm=llvm-nm", "--extra-cflags=-MT", "--extra-cxxflags=-MT"]


def compare_flags(expected, actual):
    """Raise ValueError unless the rebuilt libraries report exactly the prebuilt's semantic flags."""
    if actual != expected:
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        raise ValueError(f"Rebuilt configuration differs from the prebuilt: missing {missing}, extra {extra}")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def msys(bash, command, cwd, log):
    """Run a command in an MSYS2 login shell that inherits the developer environment's PATH."""
    # GIT_DIR points nowhere: the build sits inside this project's checkout, and FFmpeg's version script
    # would otherwise report this project's commit instead of falling back to the RELEASE file (7.1.1).
    environment = dict(os.environ, MSYS2_PATH_TYPE="inherit", CHERE_INVOKING="1", MSYSTEM="MSYS",
                       GIT_DIR="/nonexistent-ps4-runtime-ffmpeg-build")
    with open(log, "ab") as stream:
        stream.write(("\n$ " + command + "\n").encode("utf-8"))
        stream.flush()
        subprocess.run([str(bash), "-lc", command], cwd=cwd, env=environment, check=True,
                       stdout=stream, stderr=subprocess.STDOUT, timeout=3 * 3600)


def posix(path):
    """C:\\x\\y -> /c/x/y for the MSYS2 shell."""
    resolved = str(Path(path).resolve())
    return "/" + resolved[0].lower() + resolved[2:].replace("\\", "/")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--kit", type=Path, required=True, help="assembled source kit directory")
    parser.add_argument("--output", type=Path, required=True, help="new directory under build/")
    parser.add_argument("--msys", type=Path, default=Path("C:/msys64"))
    parser.add_argument("--jobs", type=int, default=8)
    args = parser.parse_args()
    if platform.system() != "Windows":
        parser.error("Requires Windows with the Visual Studio x64 developer environment")
    for tool in ("clang-cl", "lld-link", "lib", "llvm-nm"):
        if not shutil.which(tool):
            parser.error(f"Missing {tool}; use the Visual Studio x64 developer environment")
    bash = args.msys / "usr/bin/bash.exe"
    for tool in ("make", "nasm", "pkgconf", "cmp"):
        if not (args.msys / f"usr/bin/{tool}.exe").is_file():
            parser.error(f"MSYS2 is missing {tool}; install make, nasm, pkgconf and diffutils")
    output = args.output.resolve()
    if not output.is_relative_to((ROOT / "build").resolve()):
        parser.error("--output must be under build/")
    output.mkdir(parents=True, exist_ok=False)
    log = output / "build.log"
    record = json.loads(RECORD.read_text(encoding="utf-8"))
    audit, kit = ffmpeg_source_kit.load_contracts()
    report = dict(schema_version=1, status="failed", ffmpeg_version=audit["source"]["version"],
                  independent_source_build=True, upstream_redistribution_approved=False)
    try:
        report["source_kit"] = ffmpeg_source_kit.verify(ffmpeg_source_kit.read_directory(args.kit), audit, kit)
        source = output / "src"
        shutil.copytree(args.kit / "source/ffmpeg", source)
        flags = record["semantic_configure_flags"]
        configure = ["./configure", f"--prefix={posix(output / 'install')}", *TOOLCHAIN, *flags]
        report.update(configure_semantic_flags=flags, configure_toolchain=TOOLCHAIN,
                      tools={name: subprocess.run([name, "--version"], capture_output=True, text=True).stdout.splitlines()[0]
                             for name in ("clang-cl",)})
        msys(bash, " ".join(f"'{a}'" for a in configure), source, log)
        msys(bash, f"make -j{args.jobs}", source, log)
        msys(bash, "make install", source, log)
        libraries = output / "install/lib"
        include = output / "install/include"
        report["libraries"] = {p.name: digest(p) for p in sorted(libraries.glob("*.lib"))}
        with log.open("ab") as stream:
            subprocess.run(["clang-cl", "/nologo", "/std:c++20", "/EHsc", "/MT", "/W4", "/WX", "/I" + str(include),
                            str(ROOT / "tools/ffmpeg_metadata.cpp"), "/Fe" + str(output / "metadata.exe"),
                            "/Fo" + str(output / "metadata.obj"), "/link",
                            *[str(libraries / v["archive_member"]) for v in audit["libraries"].values()]],
                           check=True, stdout=stream, stderr=subprocess.STDOUT, timeout=300)
        metadata = json.loads(subprocess.check_output([str(output / "metadata.exe")], timeout=30))
        # Same review as the prebuilt: versions, headers and the reported license...
        contract = dict(audit, libraries={name: dict(value, sha256=report["libraries"].get(value["archive_member"]))
                                          for name, value in audit["libraries"].items()})
        reviewed = audit_ffmpeg.review_metadata(metadata, contract)
        # ...and exactly the prebuilt's semantic configure flags.
        compare_flags(flags, reviewed["semantic_configure_flags"])
        report.update(status="ffmpeg_source_build_verified", review=reviewed,
                      prebuilt_compiler="clang 20.1.8 (from the prebuilt objects)", crt="static (/MT, libcmt)")
    except Exception as error:
        report.update(error=str(error))
        raise
    finally:
        (output / "ffmpeg-source-build.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
