# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Build the diagnostic HLE call audit engine: strict research patch plus a layered patch.

Uses its own checkout, build and evidence directories; the strict engine, its
checkout and its evidence are never touched. This variant is for local research
only and is not covered by the strict build's AAC/host-exception tests.
"""
import argparse
import json
import os
from pathlib import Path
import platform
import shutil

import upstream_baseline as baseline
import research_contract
import run_hle_call_audit

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--define", action="append", default=[], metavar="NAME=VALUE",
                        help="extra CMake cache preset for a local toolchain difference; recorded in the report")
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    if any("=" not in define or define.startswith("=") for define in args.define):
        parser.error("--define must be NAME=VALUE")
    if platform.system() != "Windows":
        parser.error("Requires the Windows x64 Visual Studio/clang-cl developer environment")
    for tool in ("cmake", "ninja", "clang-cl", "git"):
        if not shutil.which(tool):
            parser.error(f"Missing {tool}; use the Visual Studio x64 developer environment")
    lock = json.loads((ROOT / "config/upstream-lock.json").read_text())["shadps4"]
    strict = json.loads((ROOT / "config/startup-research.json").read_text())
    contract = run_hle_call_audit.load_contract()
    if strict["upstream_revision"] != lock["revision"]:
        raise RuntimeError("Strict patch is for a different upstream revision")
    baseline.SOURCE = ROOT / "build/upstream/shadps4-hle-call-audit"
    binary = ROOT / "build/upstream/windows-x64-hle-call-audit"
    evidence = ROOT / "build/upstream/hle-call-audit-evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    report = dict(contract["base"], status="preparing",
                  hle_call_audit_patch_sha256=contract["patch_sha256"],
                  hle_call_audit_header_sha256=contract["header_sha256"],
                  strict_tests_run=False, guest_execution_tested=False, upstream_redistribution_approved=False)
    report.pop("expected_patched_tree")
    try:
        baseline.prepare(lock)
        report["source_inventory"] = baseline.inventory(lock)
        strict_patch = ROOT / strict["patch_path"]
        baseline.command("git", "apply", "--check", strict_patch, cwd=baseline.SOURCE)
        baseline.command("git", "apply", "--index", strict_patch, cwd=baseline.SOURCE)
        for key, name in research_contract.HEADERS:
            shutil.copyfile(ROOT / strict[f"{key}_path"], baseline.SOURCE / "src/core" / name)
            baseline.command("git", "add", f"src/core/{name}", cwd=baseline.SOURCE)
        research_contract.verify(baseline.SOURCE)
        report["strict_tree"] = strict["expected_patched_tree"]
        patch = ROOT / contract["patch_path"]
        baseline.command("git", "apply", "--check", "--cached", patch, cwd=baseline.SOURCE)
        baseline.command("git", "apply", "--index", patch, cwd=baseline.SOURCE)
        shutil.copyfile(ROOT / contract["header_path"], baseline.SOURCE / "src/core/hle_call_audit.h")
        baseline.command("git", "add", "src/core/hle_call_audit.h", cwd=baseline.SOURCE)
        tree = baseline.command("git", "write-tree", cwd=baseline.SOURCE, capture=True)
        report["patched_tree"] = tree
        if tree != contract["expected_tree"]:
            raise RuntimeError(f"HLE call audit tree {tree} differs from the contract")
        ffmpeg = lock["ffmpeg"]
        baseline.download(ffmpeg["url"], binary / "externals" / f"ffmpeg-{ffmpeg['release_tag']}.zip", ffmpeg["sha256"])
        report["ffmpeg_archive_sha256"] = ffmpeg["sha256"]
        report["tools"] = {name: baseline.command(name, "--version", capture=True)
                           for name in ("cmake", "ninja", "clang-cl", "git")}
        # CMake seeds initial compiler flags from CFLAGS/CXXFLAGS (for example a clang -resource-dir);
        # LIB supplies link inputs named only by file, such as clang_rt.builtins-x86_64.lib.
        report["build_environment"] = {name: os.environ.get(name) for name in ("CFLAGS", "CXXFLAGS", "LIB")}
        report["extra_cmake_defines"] = args.define
        baseline.command("cmake", "-S", baseline.SOURCE, "-B", binary, "-G", "Ninja",
                         "-DCMAKE_C_COMPILER=clang-cl", "-DCMAKE_CXX_COMPILER=clang-cl",
                         *[f"-D{k}={v}" for k, v in lock["cmake_options"].items()],
                         *[f"-D{define}" for define in args.define])
        # The changed translation unit first, so integration errors surface before the full build.
        baseline.command("cmake", "--build", binary, "--target",
                         "CMakeFiles/shadps4.dir/src/core/libraries/libs.cpp.obj", "--parallel", args.jobs)
        baseline.command("cmake", "--build", binary, "--target", "shadps4", "--parallel", args.jobs)
        executable = binary / "shadPS4.exe"
        help_text = baseline.command(executable, "--help", capture=True)
        if "--startup-audit" not in help_text:
            raise RuntimeError("Engine is missing the strict startup option")
        baseline.command("git", "diff", "--exit-code", cwd=baseline.SOURCE)
        if baseline.command("git", "write-tree", cwd=baseline.SOURCE, capture=True) != tree:
            raise RuntimeError("Staged research source changed during build")
        if baseline.command("git", "ls-files", "--others", "--exclude-standard", cwd=baseline.SOURCE, capture=True):
            raise RuntimeError("Unexpected untracked upstream source files after build")
        report.update(status="hle_call_audit_engine_built", executable_sha256=baseline.digest(executable))
    except Exception as error:
        report.update(status="failed", error=str(error))
        raise
    finally:
        (evidence / "hle-call-audit-build.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
