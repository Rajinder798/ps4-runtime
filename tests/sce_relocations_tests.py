# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Check the read-only SCE relocation inventory CLI against original generated fixtures."""
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from make_probe import make_probe
from make_sce_imports import DATA_ADDRESS, DATA_SIZE, RELOCATIONS, make_sce_imports

exe = sys.argv[1]
TYPE_NAMES = {1: "R_X86_64_64", 6: "R_X86_64_GLOB_DAT", 7: "R_X86_64_JUMP_SLOT", 8: "R_X86_64_RELATIVE",
              16: "R_X86_64_DTPMOD64"}


def run(*args):
    return subprocess.run([exe, *map(str, args)], capture_output=True, text=True, check=False, timeout=10)


def check(condition, label):
    if not condition:
        raise AssertionError(label)


payload, layout = make_sce_imports()
tag, rela = layout["tag"], layout["rela"]


def patched(*edits):
    changed = bytearray(payload)
    for offset, fmt, value in edits:
        struct.pack_into(fmt, changed, offset, value)
    return bytes(changed)


def first_rela(target=None, rtype=None, index=None):
    """Rewrite the first rela entry (RELATIVE at the start of the data segment)."""
    old_target, old_info = struct.unpack_from("<QQ", payload, rela)
    target = old_target if target is None else target
    info = ((old_info >> 32) if index is None else index) << 32 | ((old_info & 0xFFFFFFFF) if rtype is None else rtype)
    return patched((rela, "<Q", target), (rela + 8, "<Q", info))


with tempfile.TemporaryDirectory(prefix="sce-relocations-", dir=Path(exe).resolve().parent) as directory:
    path = Path(directory) / "relocations λ.elf"
    path.write_bytes(payload)
    result = run("relocations", path, "--json")
    check(result.returncode == 0 and not result.stderr, result.stderr)
    report = json.loads(result.stdout)
    check(report["schema_version"] == 1 and report["operation"] == "relocations", "schema")
    check(report["relocation_performed"] is False and report["execution_supported"] is False, "capability flags")
    check(report["symbol_entries"] == 7, "symbol count")
    check(report["tables"] == [{"name": "rela", "entries": 5}, {"name": "jmprel", "entries": 2}], "table counts")
    imports = json.loads(run("imports", path, "--json").stdout)
    names = {1 + i: f"{entry['nid']}#" for i, entry in enumerate(imports["imports"])}
    actual = [(r["table"], r["offset"], r["type_id"], r["symbol_index"], r["addend"]) for r in report["relocations"]]
    ordered = [r for r in RELOCATIONS if r[0] == "rela"] + [r for r in RELOCATIONS if r[0] == "jmprel"]
    check(actual == ordered, "entries in table order with signed addends")
    for entry in report["relocations"]:
        check(entry["type"] == TYPE_NAMES[entry["type_id"]] and entry["segment"] == 3, f"type/segment {entry}")
        index = entry["symbol_index"]
        check((entry["symbol"] == "") == (index == 0), "null symbol has no name")
        check(index not in names or entry["symbol"].startswith(names[index]), f"import symbol {entry}")
    check(report["relocations"][2]["symbol"].endswith("#B#B") and report["relocations"][2]["addend"] == 8,
          "defined export referenced by R_X86_64_64")
    text = run("relocations", path)
    check(text.returncode == 0 and "Tables: rela=5 jmprel=2" in text.stdout, "text tables")
    check("  R_X86_64_JUMP_SLOT (7): 2\n" in text.stdout and "Symbol-referencing relocations: 4 of 7" in text.stdout,
          "text summary")
    check(text.stdout.endswith("nothing was applied, resolved or executed.\n"), "text status")

    end = DATA_ADDRESS + DATA_SIZE
    accepted = [
        (first_rela(rtype=0, target=0), lambda r: r["relocations"][0]["segment"] is None, "R_X86_64_NONE has no target"),
        (first_rela(rtype=10, target=end - 4), lambda r: r["relocations"][0]["type"] == "R_X86_64_32",
         "4-byte write ending at the segment end"),
        (first_rela(rtype=99), lambda r: r["relocations"][0]["type"] == "unknown", "unknown type reported"),
        (patched(*[(tag[t], "<Q", 0x6FFFFFFF) for t in (0x6100002F, 0x61000031, 0x61000029, 0x6100002D)]),
         lambda r: r["relocations"] == [], "no relocation tables"),
    ]
    for data, valid, label in accepted:
        path.write_bytes(data)
        result = run("relocations", path, "--json")
        check(result.returncode == 0 and valid(json.loads(result.stdout)), f"{label}: {result.stderr}")

    cases = [
        (make_probe(), "missing_dynamic"),
        (patched((tag[0x6100002B] + 8, "<Q", 17)), "unsupported_plt_relocation_format"),
        (patched((tag[0x6100002F], "<Q", 0x6FFFFFFF)), "missing_relocation_table"),
        (patched((tag[0x6100002D], "<Q", 0x6FFFFFFF)), "missing_plt_relocation_table"),
        (patched((tag[0x61000031] + 8, "<Q", 1 << 40)), "relocation_table_out_of_bounds"),
        (patched((tag[0x6100002D] + 8, "<Q", 1 << 40)), "plt_relocation_table_out_of_bounds"),
        (patched((tag[0x61000033] + 8, "<Q", 32)), "bad_relocation_entry_size"),
        (patched((tag[0x61000031] + 8, "<Q", 5 * 24 - 1)), "bad_relocation_entry_size"),
        (patched((tag[0x61000033], "<Q", 0x6100002F)), "duplicate_dynamic_tag"),
        (first_rela(index=7), "symbol_index_out_of_bounds"),
        (first_rela(target=end - 7), "relocation_target_out_of_bounds"),
        (first_rela(target=0x9000), "relocation_target_out_of_bounds"),
        (first_rela(target=0x1000, rtype=10), "relocation_target_out_of_bounds"),
    ]
    for data, code in cases:
        path.write_bytes(data)
        result = run("relocations", path, "--json")
        check(result.returncode == 1 and not result.stdout and f"error[{code}]" in result.stderr,
              f"{code}: {result.returncode} {result.stderr}")
    path.write_bytes(payload)
    for args in [("relocations",), ("relocations", path, "--bogus")]:
        check(run(*args).returncode == 2, f"usage exit: {args}")
    check("ps4-runtime relocations <file> [--json]" in run("--help").stdout, "help lists relocations")
print("SCE relocation inventory checks passed")
