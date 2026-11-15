# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Build the release-candidate engine variant: strict research patch plus release-no-libressl.

The variant builds without LibreSSL, which decision 0003 found incompatible with the
GPL release license. P2P payload crypto goes through Windows CNG (a system library),
and libSceHttp HTTPS uses upstream's existing no-SSL fallback.

Uses its own checkout, build and evidence directories; the strict engine, its
checkout and its evidence are never touched. With --seed-from, a missing variant
checkout is created by copying a local checkout of the same pinned upstream
revision and resetting the copy to that revision, so no network fetch is needed.

After the build it runs the strict build's own checks on the variant: the AAC
decoder suite, the host-exception suite and the FDK linkage audit. With
--tests-only it runs just those checks on an existing variant build, after
confirming that the checkout tree and the executable are the recorded ones.
This builds an engine for audit and testing only; it approves no redistribution.
"""
import argparse
import json
import os
from pathlib import Path
import platform
import shutil

import audit_engine_linkage
import research_contract
import test_aac_backend
import test_host_exception_boundary
import upstream_baseline as baseline

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "build/upstream/shadps4-release-variant"
BINARY = ROOT / "build/upstream/windows-x64-release-variant"
EVIDENCE = ROOT / "build/upstream/release-variant-evidence"


def load_contract():
    contract = json.loads((ROOT / "config/release-variant.json").read_text(encoding="utf-8"))
    strict = json.loads((ROOT / "config/startup-research.json").read_text(encoding="utf-8"))
    base = contract["base"]
    if (base["upstream_revision"] != strict["upstream_revision"] or base["patch_sha256"] != strict["patch_sha256"] or
            base["expected_patched_tree"] != strict["expected_patched_tree"] or
            any(base[f"{key}_sha256"] != strict[f"{key}_sha256"] for key, _ in research_contract.HEADERS)):
        raise ValueError("Release variant base differs from the strict research contract")
    for key in ("patch", "header"):
        if baseline.digest(ROOT / contract[f"{key}_path"]) != contract[f"{key}_sha256"]:
            raise ValueError(f"Release variant {key} checksum mismatch")
    if contract["cmake_defines"] != {"PS4RT_WITHOUT_LIBRESSL": "ON"}:
        raise ValueError("Unexpected release variant CMake defines")
    return contract, strict


def seed(origin, revision):
    """Copy a local checkout and reset the copy (never the origin) to the pinned revision."""
    if baseline.command("git", "rev-parse", "HEAD", cwd=origin, capture=True) != revision:
        raise RuntimeError("Seed checkout is not at the pinned upstream revision")
    shutil.copytree(origin, SOURCE, symlinks=True)
    baseline.command("git", "reset", "--quiet", "--hard", revision, cwd=SOURCE)
    baseline.command("git", "clean", "-fdxq", cwd=SOURCE)
    baseline.command("git", "submodule", "foreach", "--quiet", "--recursive",
                     "git reset --quiet --hard && git clean -fdxq", cwd=SOURCE)


def configure(lock, contract):
    query = BINARY / ".cmake/api/v1/query/codemodel-v2"  # needed by the linkage audit
    query.parent.mkdir(parents=True, exist_ok=True)
    query.touch()
    baseline.command("cmake", "-S", SOURCE, "-B", BINARY, "-G", "Ninja",
                     "-DCMAKE_C_COMPILER=clang-cl", "-DCMAKE_CXX_COMPILER=clang-cl",
                     *[f"-D{k}={v}" for k, v in lock["cmake_options"].items()],
                     *[f"-D{k}={v}" for k, v in contract["cmake_defines"].items()])
    cache = (BINARY / "CMakeCache.txt").read_text(encoding="utf-8", errors="replace")
    if "PS4RT_WITHOUT_LIBRESSL:BOOL=ON" not in cache:
        raise RuntimeError("The release variant option is not active in the CMake cache")


def strict_suites(report, tree):
    """The strict build's own post-build checks, run on the variant sources (reviewed tree) and build."""
    report["aac_tests"] = test_aac_backend.run(SOURCE, BINARY, BINARY / "ps4-runtime-aac-tests", tree)
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


def tests_only(lock, contract):
    """Run the strict suites on the existing, recorded variant build without rebuilding it."""
    path = EVIDENCE / "release-variant-build.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    executable = BINARY / "shadPS4.exe"
    if report.get("status") != "release_variant_engine_built" or report.get("patched_tree") != contract["expected_tree"]:
        raise RuntimeError("No recorded release variant build to test")
    if baseline.command("git", "write-tree", cwd=SOURCE, capture=True) != contract["expected_tree"]:
        raise RuntimeError("Variant checkout differs from the contract tree")
    baseline.command("git", "diff", "--exit-code", cwd=SOURCE)
    if baseline.digest(executable) != report["executable_sha256"]:
        raise RuntimeError("Variant executable differs from the recorded build")
    if "strict_tests_error" in report:
        # Keep an earlier stopped attempt as history, not as the current state.
        report.setdefault("previous_strict_tests_attempts", []).append({"error": report.pop("strict_tests_error")})
    try:
        configure(lock, contract)
        strict_suites(report, contract["expected_tree"])
        if baseline.digest(executable) != report["executable_sha256"]:
            raise RuntimeError("Variant executable changed while running the suites")
        report["strict_tests_run_separately"] = True
    except Exception as error:
        report.update(strict_tests_error=str(error), strict_tests_run=False)
        raise
    finally:
        path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--seed-from", type=Path, help="local checkout of the pinned upstream revision to copy")
    parser.add_argument("--tests-only", action="store_true",
                        help="run the strict suites on the existing recorded variant build; no rebuild")
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    if platform.system() != "Windows":
        parser.error("Requires the Windows x64 Visual Studio/clang-cl developer environment")
    for tool in ("cmake", "ninja", "clang-cl", "git"):
        if not shutil.which(tool):
            parser.error(f"Missing {tool}; use the Visual Studio x64 developer environment")
    lock = json.loads((ROOT / "config/upstream-lock.json").read_text())["shadps4"]
    contract, strict = load_contract()
    if strict["upstream_revision"] != lock["revision"]:
        raise RuntimeError("Strict patch is for a different upstream revision")
    baseline.SOURCE = SOURCE
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    if args.tests_only:
        tests_only(lock, contract)
        return
    report = dict(contract["base"], status="preparing", release_variant_patch_sha256=contract["patch_sha256"],
                  release_variant_header_sha256=contract["header_sha256"], cmake_defines=contract["cmake_defines"],
                  strict_tests_run=False, guest_execution_tested=False, upstream_redistribution_approved=False)
    report.pop("expected_patched_tree")
    try:
        if not SOURCE.exists() and args.seed_from:
            seed(args.seed_from.resolve(), lock["revision"])
            report["seeded_from_local_checkout"] = True
        baseline.prepare(lock)
        report["source_inventory"] = baseline.inventory(lock)
        strict_patch = ROOT / strict["patch_path"]
        baseline.command("git", "apply", "--check", strict_patch, cwd=SOURCE)
        baseline.command("git", "apply", "--index", strict_patch, cwd=SOURCE)
        for key, name in research_contract.HEADERS:
            shutil.copyfile(ROOT / strict[f"{key}_path"], SOURCE / "src/core" / name)
            baseline.command("git", "add", f"src/core/{name}", cwd=SOURCE)
        research_contract.verify(SOURCE)
        if baseline.command("git", "write-tree", cwd=SOURCE, capture=True) != strict["expected_patched_tree"]:
            raise RuntimeError("Strict research tree differs before the release layer")
        report["strict_tree"] = strict["expected_patched_tree"]
        patch = ROOT / contract["patch_path"]
        baseline.command("git", "apply", "--check", "--cached", patch, cwd=SOURCE)
        baseline.command("git", "apply", "--index", patch, cwd=SOURCE)
        shutil.copyfile(ROOT / contract["header_path"], SOURCE / contract["header_target"])
        baseline.command("git", "add", contract["header_target"], cwd=SOURCE)
        tree = baseline.command("git", "write-tree", cwd=SOURCE, capture=True)
        report["patched_tree"] = tree
        if tree != contract["expected_tree"]:
            raise RuntimeError(f"Release variant tree {tree} differs from the contract")
        ffmpeg = lock["ffmpeg"]
        archive = BINARY / "externals" / f"ffmpeg-{ffmpeg['release_tag']}.zip"
        cached = ROOT / "build/upstream/windows-x64-strict/externals" / archive.name
        if not archive.exists() and cached.exists():
            archive.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(cached, archive)  # download() still verifies the pinned hash
        baseline.download(ffmpeg["url"], archive, ffmpeg["sha256"])
        report["ffmpeg_archive_sha256"] = ffmpeg["sha256"]
        report["tools"] = {name: baseline.command(name, "--version", capture=True)
                           for name in ("cmake", "ninja", "clang-cl", "git")}
        report["build_environment"] = {name: os.environ.get(name) for name in ("CFLAGS", "CXXFLAGS", "LIB")}
        configure(lock, contract)
        # The changed translation unit first, so integration errors surface before the full build.
        baseline.command("cmake", "--build", BINARY, "--target",
                         "CMakeFiles/shadps4.dir/src/core/net/p2p_crypto.cpp.obj", "--parallel", args.jobs)
        baseline.command("cmake", "--build", BINARY, "--target", "shadps4", "--parallel", args.jobs)
        strict_suites(report, tree)
        executable = BINARY / "shadPS4.exe"
        help_text = baseline.command(executable, "--help", capture=True)
        if "--startup-audit" not in help_text:
            raise RuntimeError("Engine is missing the strict startup option")
        baseline.command("git", "diff", "--exit-code", cwd=SOURCE)
        if baseline.command("git", "write-tree", cwd=SOURCE, capture=True) != tree:
            raise RuntimeError("Staged variant source changed during build")
        if baseline.command("git", "ls-files", "--others", "--exclude-standard", cwd=SOURCE, capture=True):
            raise RuntimeError("Unexpected untracked upstream source files after build")
        report.update(status="release_variant_engine_built", executable_sha256=baseline.digest(executable))
    except Exception as error:
        report.update(status="failed", error=str(error))
        raise
    finally:
        (EVIDENCE / "release-variant-build.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
