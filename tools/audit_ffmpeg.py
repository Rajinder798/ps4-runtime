# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Verify the locked Windows FFmpeg libraries and query their own build metadata.

This audits provenance, not legal clearance. Raw compiler/configuration output
stays under ignored build/. The public report deliberately excludes host paths,
compiler versions, process IDs and arbitrary binary configuration strings.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
MAX_INPUT = 100 * 1024 * 1024


def sha(data, algorithm="sha256"):
    return hashlib.new(algorithm, data).hexdigest()


def check_file(path, expected, algorithm="sha256"):
    if path.stat().st_size > MAX_INPUT or sha(path.read_bytes(), algorithm) != expected:
        raise ValueError("Input checksum/size mismatch")


def fetch(url, path, expected, algorithm="sha256"):
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".part")
        with urllib.request.urlopen(url, timeout=60) as response, temporary.open("wb") as stream:
            size = 0
            while block := response.read(1024 * 1024):
                size += len(block)
                if size > MAX_INPUT:
                    raise ValueError("Download exceeds limit")
                stream.write(block)
        check_file(temporary, expected, algorithm)
        temporary.replace(path)
    check_file(path, expected, algorithm)


def git(wrapper, *args):
    return subprocess.check_output(["git", "-C", str(wrapper), *args], timeout=30)


def configuration_flags(configuration):
    if not isinstance(configuration, str) or len(configuration) > 64 * 1024:
        raise ValueError("Invalid library configuration")
    tokens = shlex.split(configuration)
    # Compare top-level switches; a quoted compiler argument is not a switch.
    if any(re.match(r"--enable-(?:gpl|version3|nonfree|libfdk-aac)(?:=|$)", t) for t in tokens):
        raise ValueError("Unexpected license-affecting configure option")
    # Only semantic flags with a bounded alphabet may enter a public report.
    return sorted({t for t in tokens if re.fullmatch(r"--(?:enable|disable)-[a-z0-9_,=+-]+", t)})


def review_metadata(metadata, contract):
    if (not isinstance(metadata, dict) or type(metadata.get("schema_version")) is not int or
            metadata.get("schema_version") != 1 or
            metadata.get("ffmpeg_version") != contract["source"]["version"] or
            not isinstance(metadata.get("libraries"), dict) or
            set(metadata["libraries"]) != set(contract["libraries"])):
        raise ValueError("Unexpected FFmpeg metadata identity")
    libraries = {}
    configurations = set()
    for name, expected in contract["libraries"].items():
        value = metadata["libraries"][name]
        if (not isinstance(value, dict) or type(value.get("binary_version")) is not int or
                type(value.get("header_version")) is not int or
                value["binary_version"] != expected["version"] or
                value["header_version"] != value["binary_version"] or
                value.get("license") != contract["expected_license"]):
            raise ValueError("Library/header/license mismatch")
        flags = configuration_flags(value.get("configuration"))
        configurations.add(value["configuration"])
        libraries[name] = dict(version=value["binary_version"], header_matches_binary=True,
                               reported_license=value["license"], sha256=expected["sha256"])
    if len(configurations) != 1:
        raise ValueError("Library configure inputs disagree")
    return dict(libraries=libraries, semantic_configure_flags=flags,
                license_enabling_options_absent=True)


def private_directory(value):
    path = value.resolve()
    if not path.is_relative_to((ROOT / "build").resolve()):
        raise ValueError("Audit output/cache must stay under ignored build/")
    return path


def audit(wrapper, archive, output, cache, contract, lock):
    if contract["wrapper"]["revision"] != lock["revision"]:
        raise ValueError("Wrapper lock mismatch")
    pin = contract["wrapper"]["revision"]
    if git(wrapper, "rev-parse", "HEAD").decode().strip() != pin:
        raise ValueError("Wrong wrapper checkout")
    if git(wrapper, "rev-parse", pin + ":include").decode().strip() != contract["wrapper"]["header_tree"]:
        raise ValueError("Wrong wrapper header tree")
    for value in contract["wrapper"]["files"]:
        if sha(git(wrapper, "show", pin + ":" + value["path"])) != value["sha256"]:
            raise ValueError("Wrapper recipe checksum mismatch")
    check_file(archive, lock["sha256"])
    libraries = output / "lib"
    libraries.mkdir()
    with zipfile.ZipFile(archive) as package:
        for name, value in contract["libraries"].items():
            member = value["archive_member"]
            if (member != name + ".lib" or package.namelist().count(member) != 1 or
                    package.getinfo(member).file_size > MAX_INPUT):
                raise ValueError("Invalid library archive member")
            data = package.read(member)
            if sha(data) != value["sha256"]:
                raise ValueError("Static library checksum mismatch")
            (libraries / member).write_bytes(data)
    # Read canonical pinned Git bytes, not mutable or CRLF-converted headers.
    header_archive = git(wrapper, "archive", "--format=tar", pin, "include")
    with tarfile.open(fileobj=io.BytesIO(header_archive)) as headers:
        for member in headers:
            parts = PurePosixPath(member.name).parts
            if (not parts or parts[0] != "include" or ".." in parts or
                    member.name.startswith("/") or "\\" in member.name or ":" in member.name):
                raise ValueError("Invalid header archive path")
            if member.isdir():
                continue
            if not member.isfile() or member.size > MAX_INPUT:
                raise ValueError("Unsupported header archive member")
            target = output.joinpath(*parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(headers.extractfile(member).read())
    recipe = output / "recipe/ports/ffmpeg"
    recipe.mkdir(parents=True)
    for value in contract["vcpkg"]["files"]:
        name = value["path"]
        if PurePosixPath(name).name != name or "\\" in name:
            raise ValueError("Invalid recipe input path")
        cached = cache / "vcpkg" / name
        fetch(value["url"], cached, value["sha256"])
        shutil.copyfile(cached, recipe / name)
    # Verify that the wrapper patch applies exactly to this vcpkg recipe.
    patch = output / "ffmpeg.patch"
    patch.write_bytes(git(wrapper, "show", pin + ":ffmpeg.patch"))
    prefix = (output / "recipe").relative_to(ROOT).as_posix()
    subprocess.run(["git", "apply", "--check", "--directory=" + prefix, str(patch)],
                   cwd=ROOT, check=True, timeout=30, capture_output=True)
    subprocess.run(["git", "apply", "--directory=" + prefix, str(patch)],
                   cwd=ROOT, check=True, timeout=30, capture_output=True)
    source = contract["source"]
    port_text = (recipe / "portfile.cmake").read_text(encoding="utf-8")
    port_version = json.loads((recipe / "vcpkg.json").read_text())["version"]
    if (port_version != source["version"] or
            not re.search(r"SHA512\s+" + re.escape(source["sha512"]) + r"\b", port_text)):
        raise ValueError("FFmpeg source and vcpkg recipe disagree")
    package = cache / "FFmpeg-source.tar.gz"
    fetch(source["url"], package, source["sha512"], "sha512")
    with tarfile.open(package) as sources:
        for notice in source["notices"]:
            member = sources.getmember("FFmpeg-" + source["tag"] + "/" + notice["path"])
            if not member.isfile() or member.size > MAX_INPUT:
                raise ValueError("Invalid source notice")
            if sha(sources.extractfile(member).read()) != notice["sha256"]:
                raise ValueError("Source notice checksum mismatch")
    with (output / "compiler.log").open("wb") as log:
        command = ["clang-cl", "/nologo", "/std:c++20", "/EHsc", "/MT", "/W4", "/WX",
                   "/I" + str(output / "include"), str(ROOT / "tools/ffmpeg_metadata.cpp"),
                   "/Fe" + str(output / "metadata.exe"), "/Fo" + str(output / "metadata.obj"),
                   "/link", "/libpath:" + str(libraries),
                   *[v["archive_member"] for v in contract["libraries"].values()]]
        subprocess.run(command, check=True, stdout=log, stderr=subprocess.STDOUT, timeout=120)
    raw = subprocess.check_output([str(output / "metadata.exe")], timeout=10)
    if len(raw) > 1024 * 1024:
        raise ValueError("Metadata exceeds limit")
    reviewed = review_metadata(json.loads(raw), contract)
    label_text = (output / "include/libavutil/ffversion.h").read_text(encoding="utf-8")
    label = re.search(r'^#define FFMPEG_VERSION "([0-9.]+)"$', label_text, re.M)
    if not label:
        raise ValueError("Cannot read wrapper version label")
    return dict(schema_version=1, status="provenance_checks_passed", **reviewed,
                archive_sha256=lock["sha256"], wrapper_revision=pin,
                header_tree=contract["wrapper"]["header_tree"],
                vcpkg_revision=contract["vcpkg"]["revision"],
                recipe_files_verified=len(contract["vcpkg"]["files"]),
                wrapper_patch_applies=True, source_version=source["version"],
                source_revision=source["revision"], source_sha512=source["sha512"],
                source_notices_verified=len(source["notices"]),
                wrapper_version_label=label[1],
                wrapper_version_label_matches_binary=label[1] == source["version"],
                upstream_redistribution_approved=False,
                remaining_holds=["Engine separately links FDK AAC; FFmpeg metadata does not clear that hold.",
                                 "Build reproducibility, full corresponding-source/relink materials and notice bundle remain unverified.",
                                 "Other engine dependencies/resources/toolchain runtime remain outside this audit."])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wrapper", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, default=ROOT / "build/release-audit/cache")
    args = parser.parse_args()
    if platform.system() != "Windows" or not shutil.which("clang-cl"):
        parser.error("Use a Windows x64 clang-cl/MSVC developer environment")
    output = private_directory(args.output)
    cache = private_directory(args.cache)
    output.mkdir(parents=True) # Never reuse a previous run's evidence.
    try:
        contract = json.loads((ROOT / "config/ffmpeg-audit.json").read_text())
        lock = json.loads((ROOT / "config/upstream-lock.json").read_text())["shadps4"]["ffmpeg"]
        result = audit(args.wrapper.resolve(), args.archive.resolve(), output, cache, contract, lock)
    except Exception as error:
        # Full diagnostic stays local; the report never copies arbitrary paths/config.
        (output / "failure.txt").write_text(str(error), encoding="utf-8")
        (output / "audit.json").write_text(json.dumps(dict(schema_version=1, status="failed",
            upstream_redistribution_approved=False, error_type=type(error).__name__), indent=2) + "\n")
        raise
    (output / "audit.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print("FFmpeg provenance checks passed; engine redistribution remains blocked.")


if __name__ == "__main__":
    main()
