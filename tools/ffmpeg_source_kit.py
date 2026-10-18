# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Assemble/verify pinned FFmpeg source inputs; never approve engine distribution."""
import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
MAX_ARCHIVE = 100 * 1024 * 1024
MAX_FILE = 32 * 1024 * 1024
MAX_EXPANDED = 256 * 1024 * 1024
MAX_MEMBERS = 30000
RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)),
            *(f"lpt{i}" for i in range(1, 10))}


def digest(data, algorithm="sha256"):
    return hashlib.new(algorithm, data).hexdigest()


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode()


def safe_name(name):
    parts = PurePosixPath(name).parts
    if (not parts or PurePosixPath(name).as_posix() != name or name.startswith("/") or
            "\\" in name or any(p in (".", "..") or p.lower() == ".git" or p.endswith((".", " ")) or
            re.search(r'[\x00-\x1f<>:"|?*]', p) or p.split(".")[0].lower() in RESERVED
            for p in parts)):
        raise ValueError("Unsafe or nonportable archive path")
    return name


def inventory(files):
    return [dict(path=name, sha256=digest(data), size=len(data), executable=executable)
            for name, (data, executable) in sorted(files.items())]


def tree_hash(files):
    return digest(encoded(inventory(files)))


def read_tar(data, prefix):
    """Validate the entire archive before any file is written. No links/devices."""
    if len(data) > MAX_ARCHIVE:
        raise ValueError("Archive exceeds size bound")
    files, seen, total = {}, set(), 0
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        for index, member in enumerate(archive):
            if index >= MAX_MEMBERS:
                raise ValueError("Archive exceeds member bound")
            name = safe_name(member.name.rstrip("/"))
            if name != prefix and not name.startswith(prefix + "/"):
                raise ValueError("Archive has unexpected root")
            folded = name.casefold()
            if folded in seen:
                raise ValueError("Duplicate archive path")
            seen.add(folded)
            if member.isdir():
                continue
            if not member.isfile() or member.size < 0 or member.size > MAX_FILE:
                raise ValueError("Unsupported archive member")
            total += member.size
            if total > MAX_EXPANDED or name == prefix:
                raise ValueError("Archive exceeds expanded bound")
            relative = name[len(prefix) + 1:]
            files[relative] = (archive.extractfile(member).read(), bool(member.mode & 0o111))
    if not files:
        raise ValueError("Empty source archive")
    # A file cannot also be the parent of another file, including on Windows.
    check_paths(files)
    return files


def check_paths(files):
    seen, spellings = set(), {}
    for name in files:
        safe_name(name)
        parts = PurePosixPath(name).parts
        for i in range(1, len(parts) + 1):
            prefix = "/".join(parts[:i])
            if spellings.setdefault(prefix.casefold(), prefix) != prefix:
                raise ValueError("Case-colliding directory/file path")
        folded = name.casefold()
        if folded in seen:
            raise ValueError("Duplicate/case-colliding file path")
        seen.add(folded)
    for name in seen:
        if any(p.as_posix() in seen for p in PurePosixPath(name).parents if p.as_posix() != "."):
            raise ValueError("Archive file/directory collision")


def write_files(files, directory):
    check_paths(files)
    for name, (data, executable) in files.items():
        path = directory.joinpath(*PurePosixPath(name).parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        path.chmod(0o755 if executable else 0o644)


def run_git(directory, *args):
    # A fresh repository avoids parent indexes and global CRLF conversion.
    return subprocess.check_output(["git", "-c", "core.autocrlf=false", "-c",
        "core.safecrlf=false", "-c", "core.filemode=false", "-C", str(directory), *args],
        stderr=subprocess.PIPE, timeout=120)


def apply_patches(files, patches):
    with tempfile.TemporaryDirectory(prefix="ps4-ffmpeg-source-") as temporary:
        directory = Path(temporary)
        write_files(files, directory)
        run_git(directory, "init", "-q")
        run_git(directory, "add", "--all")
        for patch in patches:
            subprocess.run(["git", "-c", "core.autocrlf=false", "-C", str(directory),
                "apply", "--whitespace=nowarn", "-"], input=patch, check=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        added = run_git(directory, "ls-files", "--others", "-z").split(b"\0")
        for name in added:
            if name:
                run_git(directory, "add", "--intent-to-add", "--force", "--", name.decode("utf-8"))
        changes = run_git(directory, "diff", "--binary", "--no-ext-diff", "--no-textconv", "--no-color",
                          "--no-renames", "--src-prefix=a/", "--dst-prefix=b/")
        result = {}
        for path in directory.rglob("*"):
            relative = path.relative_to(directory).as_posix()
            if relative == ".git" or relative.startswith(".git/"):
                continue
            if path.is_file():
                result[relative] = (path.read_bytes(), files.get(relative, (b"", False))[1])
        return result, changes


def load_contracts():
    audit = json.loads((ROOT / "config/ffmpeg-audit.json").read_bytes())
    kit = json.loads((ROOT / "config/ffmpeg-source-kit.json").read_bytes())
    if (kit["schema_version"] != 1 or kit["wrapper"]["revision"] != audit["wrapper"]["revision"] or
            kit["vcpkg"]["revision"] != audit["vcpkg"]["revision"] or
            not re.fullmatch("[0-9a-f]{64}", kit["patched_source_tree_sha256"])):
        raise ValueError("Source-kit contract mismatch")
    return audit, kit


def input_specs(audit, kit):
    source = audit["source"]
    return {"ffmpeg": dict(url=source["url"], checksum=source["sha512"], algorithm="sha512",
                           prefix="FFmpeg-" + source["tag"]),
            **{name: dict(url=kit[name]["url"], checksum=kit[name]["sha256"],
                          algorithm="sha256", prefix=kit[name]["prefix"])
               for name in ("vcpkg", "wrapper")}}


def check_inputs(inputs, audit, kit):
    trees = {}
    for name, spec in input_specs(audit, kit).items():
        data = inputs[name]
        if digest(data, spec["algorithm"]) != spec["checksum"]:
            raise ValueError("Source snapshot checksum mismatch")
        trees[name] = read_tar(data, spec["prefix"])
    for name in ("wrapper", "vcpkg"):
        prefix = "ports/ffmpeg/" if name == "vcpkg" else ""
        for value in audit[name]["files"]:
            if digest(trees[name][prefix + value["path"]][0]) != value["sha256"]:
                raise ValueError("Pinned recipe checksum mismatch")
    for value in audit["source"]["notices"]:
        if digest(trees["ffmpeg"][value["path"]][0]) != value["sha256"]:
            raise ValueError("Pinned notice checksum mismatch")
    # Read the ordered list actually used by the port, not a second handwritten list.
    port = trees["vcpkg"]["ports/ffmpeg/portfile.cmake"][0].decode()
    block = re.search(r"\bPATCHES\s+(.*?)\n\)", port, re.S)
    if not block:
        raise ValueError("Missing port patch list")
    order = re.sub(r"#[^\n]*", "", block[1]).split()
    if order != kit["source_patch_order"]:
        raise ValueError("Ordered source patch list mismatch")
    return trees


def reconstruct(inputs, audit, kit):
    trees = check_inputs(inputs, audit, kit)
    source, changes = apply_patches(trees["ffmpeg"],
        [trees["vcpkg"]["ports/ffmpeg/" + name][0] for name in kit["source_patch_order"]])
    if tree_hash(source) != kit["patched_source_tree_sha256"]:
        raise ValueError("Patched source tree mismatch")
    port, _ = apply_patches({"ports/ffmpeg/portfile.cmake":
        trees["vcpkg"]["ports/ffmpeg/portfile.cmake"]}, [trees["wrapper"]["ffmpeg.patch"][0]])
    files = {"inputs/" + name + ".tar.gz": (data, False) for name, data in inputs.items()}
    files.update({"source/ffmpeg/" + name: value for name, value in source.items()})
    files["recipe/ports/ffmpeg/portfile.cmake"] = port["ports/ffmpeg/portfile.cmake"]
    files["changes/ffmpeg.diff"] = (changes, False)
    for value in audit["source"]["notices"]:
        files["notices/ffmpeg/" + value["path"]] = trees["ffmpeg"][value["path"]]
    # Full wrapper/vcpkg snapshots retain their complete source and notices too.
    for name, tree in (("wrapper", trees["wrapper"]), ("vcpkg", trees["vcpkg"])):
        for path, value in tree.items():
            if "/" not in path and path.upper().startswith(("LICENSE", "COPYING", "NOTICE")):
                files["notices/" + name + "/" + path] = value
    for path in ("tools/ffmpeg_source_kit.py", "config/ffmpeg-audit.json",
                 "config/ffmpeg-source-kit.json", "docs/ffmpeg-source-kit.md", "LICENSE"):
        files[path] = ((ROOT / path).read_bytes(), False)
    files["manifest.json"] = (encoded(dict(schema_version=1, files=inventory(files))), False)
    return files


def read_directory(directory):
    if directory.is_symlink() or getattr(directory, "is_junction", lambda: False)():
        raise ValueError("Links are not allowed in the source kit")
    files, total = {}, 0
    for path in directory.rglob("*"):
        if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
            raise ValueError("Links are not allowed in the source kit")
        if path.is_file():
            relative = path.relative_to(directory).as_posix()
            total += path.stat().st_size
            if len(files) >= MAX_MEMBERS or total > MAX_EXPANDED or path.stat().st_size > MAX_ARCHIVE:
                raise ValueError("Kit member exceeds size bound")
            files[relative] = path.read_bytes()
    check_paths(files)
    return files


def read_zip(path):
    if path.stat().st_size > MAX_EXPANDED:
        raise ValueError("Kit archive exceeds size bound")
    files, modes, total = {}, {}, 0
    with zipfile.ZipFile(path) as archive:
        if len(archive.infolist()) > MAX_MEMBERS:
            raise ValueError("Too many kit members")
        for member in archive.infolist():
            safe_name(member.filename)
            mode = member.external_attr >> 16
            if (member.filename in files or member.is_dir() or (mode & 0o170000) != 0o100000 or
                    member.file_size > MAX_ARCHIVE):
                raise ValueError("Invalid kit member")
            total += member.file_size
            if total > MAX_EXPANDED:
                raise ValueError("Kit archive exceeds expanded bound")
            files[member.filename] = archive.read(member)
            modes[member.filename] = mode
    check_paths(files)
    manifest = json.loads(files["manifest.json"])
    expected_modes = {v["path"]: 0o100755 if v["executable"] else 0o100644
                      for v in manifest["files"]}
    expected_modes["manifest.json"] = 0o100644
    if modes != expected_modes:
        raise ValueError("Kit archive permissions mismatch")
    return files


def verify(files, audit, kit):
    # The supplied manifest is not a trust anchor: reconstruct from locked archives.
    expected = reconstruct({name: files["inputs/" + name + ".tar.gz"]
                            for name in input_specs(audit, kit)}, audit, kit)
    if set(files) != set(expected) or any(files[n] != expected[n][0] for n in expected):
        raise ValueError("Kit content differs from independently reconstructed inputs")
    return summary(expected, audit, kit)


def summary(files, audit, kit):
    return dict(schema_version=1, status="source_inputs_verified",
        ffmpeg_version=audit["source"]["version"], source_revision=audit["source"]["revision"],
        vcpkg_revision=kit["vcpkg"]["revision"], wrapper_revision=kit["wrapper"]["revision"],
        source_patches_applied=len(kit["source_patch_order"]),
        patched_source_tree_sha256=kit["patched_source_tree_sha256"],
        source_files=sum(n.startswith("source/ffmpeg/") for n in files),
        full_wrapper_and_vcpkg_snapshots=True, source_notices_verified=True,
        independent_binary_rebuild_verified=False, static_relink_kit_complete=False,
        upstream_redistribution_approved=False)


def pack(files, path):
    with zipfile.ZipFile(path, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, (data, executable) in sorted(files.items()):
            member = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            member.create_system = 3
            member.external_attr = (0o100755 if executable else 0o100644) << 16
            member.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(member, data, compresslevel=9)


def private_path(path):
    path = path.resolve()
    if not path.is_relative_to((ROOT / "build").resolve()):
        raise ValueError("Output/cache must remain under ignored build/")
    return path


def fetch_inputs(cache, audit, kit, offline):
    inputs = {}
    for name, spec in input_specs(audit, kit).items():
        path = cache / (name + ".tar.gz")
        if not path.exists():
            if offline:
                raise ValueError("Missing offline source snapshot")
            with urllib.request.urlopen(spec["url"], timeout=60) as response:
                data = response.read(MAX_ARCHIVE + 1)
            if len(data) > MAX_ARCHIVE or digest(data, spec["algorithm"]) != spec["checksum"]:
                raise ValueError("Downloaded source checksum/size mismatch")
            path.write_bytes(data)
        if path.stat().st_size > MAX_ARCHIVE:
            raise ValueError("Cached source exceeds size bound")
        inputs[name] = path.read_bytes()
        if digest(inputs[name], spec["algorithm"]) != spec["checksum"]:
            raise ValueError("Cached source checksum mismatch")
    return inputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    assemble = sub.add_parser("assemble")
    assemble.add_argument("--output", type=Path, required=True)
    assemble.add_argument("--cache", type=Path, default=ROOT / "build/release-audit/source-kit-cache")
    assemble.add_argument("--offline", action="store_true")
    check = sub.add_parser("verify")
    check.add_argument("--kit", type=Path, required=True, help="Kit directory or generated ZIP")
    args = parser.parse_args()
    audit, kit = load_contracts()
    if args.command == "assemble":
        output, cache = private_path(args.output), private_path(args.cache)
        output.mkdir(parents=True)  # Refuse reuse; never overwrite old evidence.
        cache.mkdir(parents=True, exist_ok=True)
        inputs = fetch_inputs(cache, audit, kit, args.offline)
        files = reconstruct(inputs, audit, kit)
        write_files(files, output / "kit")
        pack(files, output / "ffmpeg-source-kit.zip")
        result = verify(read_zip(output / "ffmpeg-source-kit.zip"), audit, kit)
        result["archive_round_trip_verified"] = True
        (output / "summary.json").write_bytes(encoded(result))
    else:
        result = verify(read_directory(args.kit) if args.kit.is_dir() else read_zip(args.kit), audit, kit)
    print(encoded(result).decode(), end="")


if __name__ == "__main__":
    main()
