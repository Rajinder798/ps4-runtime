# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Build the release-candidate engine: release-no-libressl plus FFmpeg built from its pinned source.

Layers, each checked against its pinned tree: the strict research patch and
headers, the release-no-libressl patch and CNG header, then
release-ffmpeg-source.patch. That last patch adds PS4RT_FFMPEG_PREFIX. The script
copies a verified FFmpeg source build (tools/build_ffmpeg_source.py) into the
engine build directory and points that option at it. The copy holds the build's
include/ and lib/, whose library hashes must equal the source-build record, plus
FFmpeg's own license notices from the source kit. Then it builds the engine and
runs the strict post-build suites against those same libraries.

Uses its own checkout, build and evidence directories; the strict engine, the
release-no-libressl variant and their evidence are never touched. It approves no
redistribution.
"""
import argparse
import json
import os
from pathlib import Path
import platform
import shutil

import audit_engine_linkage
import build_release_variant as variant
import research_contract
import test_aac_backend
import test_host_exception_boundary
import upstream_baseline as baseline

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "build/upstream/shadps4-release-candidate"
BINARY = ROOT / "build/upstream/windows-x64-release-candidate"
EVIDENCE = ROOT / "build/upstream/release-candidate-evidence"
LIBRARIES = ("avcodec", "avdevice", "avfilter", "avformat", "avutil", "swresample", "swscale")


def load_contract():
    contract = json.loads((ROOT / "config/release-candidate.json").read_text(encoding="utf-8"))
    if contract["parent"] != "config/release-variant.json":
        raise ValueError("Unexpected release candidate parent")
    parent, strict = variant.load_contract()
    if baseline.digest(ROOT / contract["patch_path"]) != contract["patch_sha256"]:
        raise ValueError("Release candidate patch checksum mismatch")
    if contract["cmake_defines"] != parent["cmake_defines"]:
        raise ValueError("Release candidate CMake defines differ from its parent")
    return contract, parent, strict


def stage_ffmpeg(contract, build, kit):
    """Copy the verified FFmpeg source build and FFmpeg's notices into the engine build directory."""
    record = json.loads((ROOT / contract["ffmpeg_source_build"]).read_text(encoding="utf-8"))
    report = json.loads((build / "ffmpeg-source-build.json").read_text(encoding="utf-8"))
    expected = record["result"]["built_library_sha256"]
    if record["status"] != "passed" or report.get("status") != "ffmpeg_source_build_verified":
        raise RuntimeError("FFmpeg source build is not a verified, recorded build")
    prefix = BINARY / contract["ffmpeg_prefix_in_build"]
    if prefix.exists():
        shutil.rmtree(prefix)
    shutil.copytree(build / "install/include", prefix / "include")
    (prefix / "lib").mkdir(parents=True)
    for name in LIBRARIES:
        shutil.copyfile(build / "install/lib" / f"{name}.lib", prefix / "lib" / f"{name}.lib")
    actual = {f"{name}.lib": baseline.digest(prefix / "lib" / f"{name}.lib") for name in LIBRARIES}
    if actual != expected:
        raise RuntimeError("Staged FFmpeg libraries differ from the recorded source build")
    audit = json.loads((ROOT / "config/ffmpeg-audit.json").read_text(encoding="utf-8"))
    (prefix / "notices").mkdir()
    for notice in audit["source"]["notices"]:
        target = prefix / "notices" / notice["path"]
        shutil.copyfile(kit / "notices/ffmpeg" / notice["path"], target)
        if baseline.digest(target) != notice["sha256"]:
            raise RuntimeError(f"FFmpeg notice checksum mismatch: {notice['path']}")
    return prefix, actual


def strict_suites(report, tree, prefix, libraries):
    ffmpeg = {"lib": prefix / "lib", "include": prefix / "include",
              "sha256": {name: libraries[f"{name}.lib"] for name in ("avcodec", "avutil", "swresample")}}
    report["aac_tests"] = test_aac_backend.run(SOURCE, BINARY, BINARY / "ps4-runtime-aac-tests", tree, ffmpeg=ffmpeg)
    host_tests = BINARY / "ps4-runtime-host-exception-tests"
    try:
        report["host_exception_tests"] = test_host_exception_boundary.run(SOURCE, host_tests, tree)
    finally:
        if (host_tests / "compiler.log").exists():
            shutil.copyfile(host_tests / "compiler.log", EVIDENCE / "host-exceptions-compiler.log")
    linkage = audit_engine_linkage.audit(BINARY)
    for name, data in (("aac-tests.json", report["aac_tests"]), ("host-exceptions.json", report["host_exception_tests"]),
                       ("aac-linkage.json", linkage)):
        (EVIDENCE / name).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    report.update(aac_backend="ffmpeg-aac-lc", fdk_linkage_verified_absent=True, strict_tests_run=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ffmpeg-build", type=Path, required=True, help="verified build from tools/build_ffmpeg_source.py")
    parser.add_argument("--kit", type=Path, required=True, help="the FFmpeg source kit that build used")
    parser.add_argument("--seed-from", type=Path, help="local checkout of the pinned upstream revision to copy")
    parser.add_argument("--jobs", type=int, default=4)
    args = parser.parse_args()
    if platform.system() != "Windows":
        parser.error("Requires the Windows x64 Visual Studio/clang-cl developer environment")
    for tool in ("cmake", "ninja", "clang-cl", "git"):
        if not shutil.which(tool):
            parser.error(f"Missing {tool}; use the Visual Studio x64 developer environment")
    lock = json.loads((ROOT / "config/upstream-lock.json").read_text())["shadps4"]
    contract, parent, strict = load_contract()
    baseline.SOURCE = SOURCE
    variant.SOURCE = SOURCE  # seed() copies into the module's SOURCE
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    report = dict(parent["base"], status="preparing", release_variant_patch_sha256=parent["patch_sha256"],
                  release_variant_header_sha256=parent["header_sha256"],
                  release_candidate_patch_sha256=contract["patch_sha256"], cmake_defines=contract["cmake_defines"],
                  strict_tests_run=False, guest_execution_tested=False, upstream_redistribution_approved=False)
    report.pop("expected_patched_tree")
    try:
        if not SOURCE.exists() and args.seed_from:
            variant.seed(args.seed_from.resolve(), lock["revision"])
            report["seeded_from_local_checkout"] = True
        baseline.prepare(lock)
        report["source_inventory"] = baseline.inventory(lock)
        baseline.command("git", "apply", "--index", ROOT / strict["patch_path"], cwd=SOURCE)
        for key, name in research_contract.HEADERS:
            shutil.copyfile(ROOT / strict[f"{key}_path"], SOURCE / "src/core" / name)
            baseline.command("git", "add", f"src/core/{name}", cwd=SOURCE)
        research_contract.verify(SOURCE)
        report["strict_tree"] = strict["expected_patched_tree"]
        baseline.command("git", "apply", "--index", ROOT / parent["patch_path"], cwd=SOURCE)
        shutil.copyfile(ROOT / parent["header_path"], SOURCE / parent["header_target"])
        baseline.command("git", "add", parent["header_target"], cwd=SOURCE)
        if baseline.command("git", "write-tree", cwd=SOURCE, capture=True) != parent["expected_tree"]:
            raise RuntimeError("release-no-libressl tree differs before the candidate layer")
        report["release_variant_tree"] = parent["expected_tree"]
        baseline.command("git", "apply", "--index", ROOT / contract["patch_path"], cwd=SOURCE)
        tree = baseline.command("git", "write-tree", cwd=SOURCE, capture=True)
        report["patched_tree"] = tree
        if tree != contract["expected_tree"]:
            raise RuntimeError(f"Release candidate tree {tree} differs from the contract")
        prefix, libraries = stage_ffmpeg(contract, args.ffmpeg_build.resolve(), args.kit.resolve())
        report["ffmpeg_source_build"] = dict(record=contract["ffmpeg_source_build"], libraries_sha256=libraries,
                                             prefix_in_build=contract["ffmpeg_prefix_in_build"])
        report["tools"] = {name: baseline.command(name, "--version", capture=True) for name in ("cmake", "ninja", "clang-cl", "git")}
        report["build_environment"] = {name: os.environ.get(name) for name in ("CFLAGS", "CXXFLAGS", "LIB")}
        query = BINARY / ".cmake/api/v1/query/codemodel-v2"  # needed by the linkage audit
        query.parent.mkdir(parents=True, exist_ok=True)
        query.touch()
        baseline.command("cmake", "-S", SOURCE, "-B", BINARY, "-G", "Ninja",
                         "-DCMAKE_C_COMPILER=clang-cl", "-DCMAKE_CXX_COMPILER=clang-cl",
                         *[f"-D{k}={v}" for k, v in lock["cmake_options"].items()],
                         *[f"-D{k}={v}" for k, v in contract["cmake_defines"].items()],
                         f"-DPS4RT_FFMPEG_PREFIX={prefix.as_posix()}")
        cache = (BINARY / "CMakeCache.txt").read_text(encoding="utf-8", errors="replace")
        if "PS4RT_WITHOUT_LIBRESSL:BOOL=ON" not in cache or f"PS4RT_FFMPEG_PREFIX:PATH={prefix.as_posix()}" not in cache:
            raise RuntimeError("Release candidate options are not active in the CMake cache")
        if (BINARY / "externals/ffmpeg-94dde08").exists():
            raise RuntimeError("The prebuilt FFmpeg archive was unpacked; the source build is not in use")
        baseline.command("cmake", "--build", BINARY, "--target", "shadps4", "--parallel", args.jobs)
        strict_suites(report, tree, prefix, libraries)
        executable = BINARY / "shadPS4.exe"
        if "--startup-audit" not in baseline.command(executable, "--help", capture=True):
            raise RuntimeError("Engine is missing the strict startup option")
        baseline.command("git", "diff", "--exit-code", cwd=SOURCE)
        if baseline.command("git", "write-tree", cwd=SOURCE, capture=True) != tree:
            raise RuntimeError("Staged candidate source changed during build")
        if baseline.command("git", "ls-files", "--others", "--exclude-standard", cwd=SOURCE, capture=True):
            raise RuntimeError("Unexpected untracked upstream source files after build")
        report.update(status="release_candidate_engine_built", executable_sha256=baseline.digest(executable))
    except Exception as error:
        report.update(status="failed", error=str(error))
        raise
    finally:
        (EVIDENCE / "release-candidate-build.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
