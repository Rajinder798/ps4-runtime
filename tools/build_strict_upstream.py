# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Build the pinned research engine with the reviewed strict-startup patch."""
import argparse
import json
from pathlib import Path
import platform
import shutil
import sys

import upstream_baseline as baseline

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", type=int, default=4)
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    if platform.system() != "Windows":
        parser.error("Requires the Windows x64 Visual Studio/clang-cl developer environment")
    for tool in ("cmake", "ninja", "clang-cl", "git"):
        if not shutil.which(tool):
            parser.error(f"Missing {tool}; use the Visual Studio x64 developer environment")
    lock = json.loads((ROOT / "config/upstream-lock.json").read_text())["shadps4"]
    contract = json.loads((ROOT / "config/startup-research.json").read_text())
    if contract["upstream_revision"] != lock["revision"]:
        raise RuntimeError("Strict patch is for a different upstream revision")
    patch, header, services = (ROOT / contract[key] for key in
                               ("patch_path", "audit_header_path", "services_header_path"))
    for file, key in ((patch, "patch_sha256"), (header, "audit_header_sha256"),
                      (services, "services_header_sha256")):
        if baseline.digest(file) != contract[key]:
            raise RuntimeError(f"Research input checksum mismatch: {file}")
    # Separate checkout/output: the unmodified baseline/reference checkout stays untouched.
    baseline.SOURCE = ROOT / "build/upstream/shadps4-strict"
    binary = ROOT / "build/upstream/windows-x64-strict"
    evidence = ROOT / "build/upstream/strict-evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    report = {"status": "preparing", "upstream_revision": lock["revision"],
              "patch_sha256": contract["patch_sha256"], "audit_header_sha256": contract["audit_header_sha256"],
              "services_header_sha256": contract["services_header_sha256"],
              "guest_execution_tested": False, "upstream_redistribution_approved": False}
    try:
        baseline.prepare(lock)
        report["source_inventory"] = baseline.inventory(lock)
        baseline.command("git", "apply", "--check", patch, cwd=baseline.SOURCE)
        baseline.command("git", "apply", "--index", patch, cwd=baseline.SOURCE)
        shutil.copyfile(header, baseline.SOURCE / "src/core/startup_audit.h")
        shutil.copyfile(services, baseline.SOURCE / "src/core/kernel_services.h")
        baseline.command("git", "add", "src/core/startup_audit.h", "src/core/kernel_services.h",
                         cwd=baseline.SOURCE)
        tree = baseline.command("git", "write-tree", cwd=baseline.SOURCE, capture=True)
        report["patched_tree"] = tree
        ffmpeg = lock["ffmpeg"]
        baseline.download(ffmpeg["url"], binary / "externals" / f"ffmpeg-{ffmpeg['release_tag']}.zip", ffmpeg["sha256"])
        report["ffmpeg_archive_sha256"] = ffmpeg["sha256"]
        report["tools"] = {name: baseline.command(name, "--version", capture=True)
                           for name in ("cmake", "ninja", "clang-cl", "git")}
        baseline.command("cmake", "-S", baseline.SOURCE, "-B", binary, "-G", "Ninja",
                         "-DCMAKE_C_COMPILER=clang-cl", "-DCMAKE_CXX_COMPILER=clang-cl",
                         *[f"-D{k}={v}" for k, v in lock["cmake_options"].items()])
        # Compile the patched translation units before the rest of the
        # executable, so integration/type errors surface without a full link wait.
        baseline.command("cmake", "--build", binary, "--target",
                         "CMakeFiles/shadps4.dir/src/main.cpp.obj",
                         "CMakeFiles/shadps4.dir/src/core/linker.cpp.obj",
                         "CMakeFiles/shadps4.dir/src/core/file_sys/devices/logger.cpp.obj",
                         "CMakeFiles/shadps4.dir/src/core/file_sys/fs.cpp.obj",
                         "CMakeFiles/shadps4.dir/src/core/libraries/kernel/file_system.cpp.obj",
                         "CMakeFiles/shadps4.dir/src/core/libraries/kernel/memory.cpp.obj",
                         "--parallel", args.jobs)
        baseline.command("cmake", "--build", binary, "--target", "shadps4", "--parallel", args.jobs)
        executable = binary / "shadPS4.exe"
        help_text = baseline.command(executable, "--help", capture=True)
        if "--startup-audit" not in help_text:
            raise RuntimeError("Engine is missing the strict startup option")
        (evidence / "shadps4-help.txt").write_text(help_text + "\n", encoding="utf-8")
        baseline.command("git", "diff", "--exit-code", cwd=baseline.SOURCE)
        if baseline.command("git", "write-tree", cwd=baseline.SOURCE, capture=True) != tree:
            raise RuntimeError("Staged research source changed during build")
        if baseline.command("git", "ls-files", "--others", "--exclude-standard", cwd=baseline.SOURCE, capture=True):
            raise RuntimeError("Unexpected untracked upstream source files after build")
        report.update(status="strict_engine_built", executable_sha256=baseline.digest(executable))
    except Exception as error:
        report.update(status="failed", error=str(error))
        raise
    finally:
        (evidence / "strict-build.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
