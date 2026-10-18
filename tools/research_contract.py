# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Shared checks for the exact patched research source, never a reset operation."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
HEADERS = (("audit_header", "startup_audit.h"), ("services_header", "kernel_services.h"),
           ("aac_header", "aac_decoder.h"))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify(source):
    contract = json.loads((ROOT / "config/startup-research.json").read_text())
    def git(*args):
        return subprocess.check_output(["git", "-C", str(source), *args], timeout=30).decode().strip()
    if (git("rev-parse", "HEAD") != contract["upstream_revision"] or
            git("write-tree") != contract["expected_patched_tree"]):
        raise ValueError("Research source revision/tree mismatch")
    if git("diff", "--name-only") or git("ls-files", "--others", "--exclude-standard"):
        raise ValueError("Unreviewed research source changes")
    if digest(ROOT / contract["patch_path"]) != contract["patch_sha256"]:
        raise ValueError("Research patch checksum mismatch")
    for key, target in HEADERS:
        if (digest(ROOT / contract[key + "_path"]) != contract[key + "_sha256"] or
                digest(source / "src/core" / target) != contract[key + "_sha256"]):
            raise ValueError("Research header checksum mismatch")
    return contract
