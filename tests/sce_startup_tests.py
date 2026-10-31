# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Check the read-only SCE startup metadata CLI against original generated fixtures."""
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from make_probe import make_probe
from make_sce_imports import (PROCESS_PARAM_ADDRESS, PROCESS_PARAM_ENTRIES, PROCESS_PARAM_SIZE, SDK_VERSION,
                              TLS_ADDRESS, TLS_ALIGNMENT, TLS_MEMORY_SIZE, make_sce_imports)

exe = sys.argv[1]


def run(*args):
    return subprocess.run([exe, *map(str, args)], capture_output=True, text=True, check=False, timeout=10)


def check(condition, label):
    if not condition:
        raise AssertionError(label)


payload, layout = make_sce_imports()
tls, param = layout["tls_phdr"], layout["process_param_phdr"]


def patched(*edits):
    changed = bytearray(payload)
    for offset, fmt, value in edits:
        struct.pack_into(fmt, changed, offset, value)
    return bytes(changed)


def tls_phdr(offset, address, file_size, memory_size, alignment):
    return patched((tls + 8, "<Q", offset), (tls + 16, "<Q", address), (tls + 32, "<Q", file_size),
                   (tls + 40, "<Q", memory_size), (tls + 48, "<Q", alignment))


with tempfile.TemporaryDirectory(prefix="sce-startup-", dir=Path(exe).resolve().parent) as directory:
    path = Path(directory) / "startup λ.elf"
    path.write_bytes(payload)
    result = run("startup", path, "--json")
    check(result.returncode == 0 and not result.stderr, result.stderr)
    report = json.loads(result.stdout)
    check(report["schema_version"] == 1 and report["operation"] == "startup", "schema")
    check(report["tls_allocated"] is False and report["execution_supported"] is False, "capability flags")
    check(report["tls"] == {"segment": 4, "address": TLS_ADDRESS, "init_size": 0, "memory_size": TLS_MEMORY_SIZE,
                            "alignment": TLS_ALIGNMENT, "aligned_size": TLS_MEMORY_SIZE, "init_segment": None},
          "TLS template")
    check(report["tls_relocations"] == {"R_X86_64_DTPMOD64": 1, "R_X86_64_DTPOFF64": 0, "R_X86_64_TPOFF64": 0},
          "TLS relocation counts")
    check(report["process_param"] == {"segment": 5, "load_segment": 3, "address": PROCESS_PARAM_ADDRESS,
                                      "size": PROCESS_PARAM_SIZE, "magic": "ORBI",
                                      "entry_count": PROCESS_PARAM_ENTRIES, "sdk_version": SDK_VERSION},
          "process parameters")
    text = run("startup", path)
    check(text.returncode == 0 and "TLS template: segment 4 address=0x40e0 init=0 memory=16 align=16" in text.stdout,
          "text TLS")
    check("SDK=0x4508101" in text.stdout and text.stdout.endswith("nothing was executed.\n"), "text status")

    path.write_bytes(make_probe())
    probe = json.loads(run("startup", path, "--json").stdout)
    check(probe["tls"] is None and probe["process_param"] is None and probe["tls_relocations"] is None,
          "file without TLS, process parameters or SCE dynamic tables")

    accepted = [
        (tls_phdr(TLS_ADDRESS, TLS_ADDRESS, 8, TLS_MEMORY_SIZE, TLS_ALIGNMENT),
         lambda r: r["tls"]["init_segment"] == 3 and r["tls"]["init_size"] == 8, "file-backed init image"),
        (tls_phdr(TLS_ADDRESS, TLS_ADDRESS, 0, TLS_MEMORY_SIZE, 0),
         lambda r: r["tls"]["aligned_size"] == TLS_MEMORY_SIZE, "zero alignment leaves the size unrounded"),
        (tls_phdr(TLS_ADDRESS, TLS_ADDRESS, 0, TLS_MEMORY_SIZE, 32),
         lambda r: r["tls"]["aligned_size"] == 32, "size rounded up to the alignment"),
        (patched((PROCESS_PARAM_ADDRESS, "<Q", 24)), lambda r: r["process_param"]["size"] == 24, "minimum size"),
    ]
    for data, valid, label in accepted:
        path.write_bytes(data)
        result = run("startup", path, "--json")
        check(result.returncode == 0 and valid(json.loads(result.stdout)), f"{label}: {result.stderr}")

    second_param = bytearray(payload)
    second_param[tls:tls + 56] = payload[param:param + 56]
    cases = [
        (bytes(second_param), "duplicate_process_param"),
        (patched((param, "<I", 7)), "duplicate_tls_segment"),
        (tls_phdr(0x10, 0x5000, 8, TLS_MEMORY_SIZE, TLS_ALIGNMENT), "tls_image_out_of_bounds"),
        (tls_phdr(TLS_ADDRESS, 0, 0, (1 << 64) - 8, TLS_ALIGNMENT), "tls_size_overflow"),
        (patched((tls, "<I", 0)), "tls_relocation_without_tls"),
        (patched((param + 32, "<Q", 16)), "process_param_too_small"),
        (patched((param + 8, "<Q", 0x1000)), "process_param_out_of_bounds"),
        (patched((PROCESS_PARAM_ADDRESS, "<Q", PROCESS_PARAM_SIZE + 1)), "bad_process_param_size"),
        (patched((PROCESS_PARAM_ADDRESS, "<Q", 8)), "bad_process_param_size"),
        (patched((PROCESS_PARAM_ADDRESS + 8, "<I", 0x4942524E)), "bad_process_param_magic"),
        (patched((layout["tag"][0x61000033] + 8, "<Q", 32)), "bad_relocation_entry_size"),
        (patched((0, "<I", 0x464C4500)), "bad_magic"),
    ]
    for data, code in cases:
        path.write_bytes(data)
        result = run("startup", path, "--json")
        check(result.returncode == 1 and not result.stdout and f"error[{code}]" in result.stderr,
              f"{code}: {result.returncode} {result.stderr}")
    path.write_bytes(payload)
    for args in [("startup",), ("startup", path, "--bogus")]:
        check(run(*args).returncode == 2, f"usage exit: {args}")
    check("ps4-runtime startup <file> [--json]" in run("--help").stdout, "help lists startup")
print("SCE startup metadata checks passed")
