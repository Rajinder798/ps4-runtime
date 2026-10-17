# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Build an isolated pinned upstream baseline; never import it into our CMake build."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "build" / "upstream"
SOURCE = WORK / "shadps4"
BINARY = WORK / "windows-x64"
EVIDENCE = WORK / "evidence"
LOCK_PATH = ROOT / "config" / "upstream-lock.json"


def command(*args, cwd=ROOT, capture=False):
    print("+ " + subprocess.list2cmdline(list(map(str, args))), flush=True)
    result = subprocess.run(list(map(str, args)), cwd=cwd, check=True,
                            stdout=subprocess.PIPE if capture else None,
                            encoding="utf-8", errors="replace")
    return result.stdout.strip() if capture else None


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def download(url, destination, expected_hash):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        partial = destination.with_suffix(destination.suffix + ".part")
        print(f"Downloading {url}", flush=True)
        with urllib.request.urlopen(url, timeout=120) as response, partial.open("wb") as target:
            shutil.copyfileobj(response, target)
        if digest(partial) != expected_hash:
            raise RuntimeError(f"SHA-256 mismatch: {partial}")
        partial.replace(destination)
    if digest(destination) != expected_hash:
        raise RuntimeError(f"SHA-256 mismatch: {destination}")


def verify_source(lock):
    revision = command("git", "rev-parse", "HEAD", cwd=SOURCE, capture=True)
    if revision != lock["revision"]:
        raise RuntimeError(f"Expected {lock['revision']}, found {revision}; no checkout was reset.")
    if command("git", "status", "--porcelain", "--untracked-files=normal", cwd=SOURCE, capture=True):
        raise RuntimeError("Upstream checkout has local changes; refusing to overwrite them.")


def prepare(lock):
    WORK.mkdir(parents=True, exist_ok=True)
    if not SOURCE.exists():
        command("git", "init", SOURCE)
        command("git", "remote", "add", "origin", lock["repository"], cwd=SOURCE)
        command("git", "fetch", "--depth=1", "origin", lock["revision"], cwd=SOURCE)
        command("git", "checkout", "--detach", "FETCH_HEAD", cwd=SOURCE)
    verify_source(lock)
    command("git", "submodule", "update", "--init", "--recursive", "--depth=1", "--jobs=4", cwd=SOURCE)
    verify_source(lock)


def inventory(lock):
    verify_source(lock)
    status = command("git", "submodule", "status", "--recursive", cwd=SOURCE, capture=True)
    # capture() strips leading whitespace from the first line; restore status
    # interpretation by checking only the explicit invalid status prefixes.
    modules = []
    for line in status.splitlines():
        if line[0] in "-+U":
            raise RuntimeError(f"Submodule is missing or differs from its gitlink: {line}")
        fields = line.split()
        modules.append({"path": fields[1], "revision": fields[0]})
    licenses = []
    for directory in [SOURCE, *(SOURCE / item["path"] for item in modules)]:
        candidates = []
        for path in sorted(directory.iterdir()):
            if path.is_file() and path.name.lower().startswith(("license", "copying", "notice", "copyright")):
                candidates.append({"path": str(path.relative_to(SOURCE)).replace("\\", "/"),
                                   "sha256": digest(path)})
        licenses.append({"component": str(directory.relative_to(SOURCE)).replace("\\", "/"),
                         "root_notice_files": candidates,
                         "review_status": "unreviewed; discovery is not a license audit"})
    return {"repository": lock["repository"], "revision": lock["revision"],
            "submodules": modules, "notice_inventory": licenses}


def build(lock, jobs):
    if platform.system() != "Windows" or platform.machine().lower() not in ("amd64", "x86_64"):
        raise RuntimeError("This recipe requires Windows x86-64 with the VS C++ development environment.")
    for tool in ("cmake", "ninja", "clang-cl", "git"):
        if not shutil.which(tool):
            raise RuntimeError(f"Missing {tool}; use a VS x64 developer shell with Clang and Ninja.")
    report = inventory(lock)
    report.update({"host": platform.platform(), "runner_image": os.environ.get("ImageVersion"),
                   "runner_os": os.environ.get("ImageOS"), "cmake_options": lock["cmake_options"],
                   "status": "preparing"})
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    report_file = EVIDENCE / "upstream-build.json"
    report_file.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    try:
        report["tools"] = {tool: command(tool, "--version", capture=True)
                           for tool in ("cmake", "ninja", "clang-cl", "git")}
        ffmpeg = lock["ffmpeg"]
        ffmpeg_source = SOURCE / "externals" / "ffmpeg-core"
        if command("git", "rev-parse", "HEAD", cwd=ffmpeg_source, capture=True) != ffmpeg["revision"]:
            raise RuntimeError("FFmpeg gitlink does not match the binary dependency lock.")
        # Upstream derives the archive filename from git --short HEAD.
        short = command("git", "rev-parse", "--short", "HEAD", cwd=ffmpeg_source, capture=True)
        if short != ffmpeg["release_tag"]:
            raise RuntimeError("FFmpeg short revision differs from the locked release tag.")
        archive = BINARY / "externals" / f"ffmpeg-{short}.zip"
        download(ffmpeg["url"], archive, ffmpeg["sha256"])
        report["ffmpeg_archive_sha256"] = digest(archive)
        options = [f"-D{key}={value}" for key, value in lock["cmake_options"].items()]
        command("cmake", "-S", SOURCE, "-B", BINARY, "-G", "Ninja",
                "-DCMAKE_C_COMPILER=clang-cl", "-DCMAKE_CXX_COMPILER=clang-cl", *options)
        report["status"] = "configured"
        command("cmake", "--build", BINARY, "--target", "shadps4", "--parallel", jobs)
        executable = BINARY / "shadPS4.exe"
        help_text = command(executable, "--help", capture=True)
        if "shadPS4 Emulator CLI" not in help_text:
            raise RuntimeError("Built executable did not report the expected CLI help.")
        (EVIDENCE / "shadps4-help.txt").write_text(help_text + "\n", encoding="utf-8")
        report.update({"status": "built_and_help_smoke_passed", "executable_sha256": digest(executable),
                       "guest_execution_tested": False})
        verify_source(lock)
    except Exception as error:
        report.update({"status": "failed", "error": str(error)})
        raise
    finally:
        report_file.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["prepare", "build", "inventory"])
    parser.add_argument("--jobs", type=int, default=4)
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))["shadps4"]
    if args.operation == "prepare":
        prepare(lock)
    elif args.operation == "build":
        build(lock, args.jobs)
    else:
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        (EVIDENCE / "source-inventory.json").write_text(json.dumps(inventory(lock), indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, subprocess.CalledProcessError) as error:
        sys.exit(f"baseline error: {error}")
