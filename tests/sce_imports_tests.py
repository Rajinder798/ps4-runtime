# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Check the read-only SCE import inventory CLI against original generated fixtures."""
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from make_probe import make_probe
from make_sce_imports import IMPORTS, LIBRARIES, MODULES, make_sce_imports, name_to_nid

exe = sys.argv[1]


def run(*args):
    return subprocess.run([exe, *map(str, args)], capture_output=True, text=True, check=False, timeout=10)


def check(condition, label):
    if not condition:
        raise AssertionError(label)


# Independent of the generator: widely published NIDs for two public API names.
check(name_to_nid("printf") == "hcuQgD53UxM", "printf NID derivation")
check(name_to_nid("sceKernelUsleep") == "1jfXLRVzisc", "sceKernelUsleep NID derivation")

payload, layout = make_sce_imports()
tag, string = layout["tag"], layout["string"]
symbol = layout["symbols"]


def patched(*edits):
    changed = bytearray(payload)
    for offset, fmt, value in edits:
        struct.pack_into(fmt, changed, offset, value)
    return bytes(changed)


with tempfile.TemporaryDirectory(prefix="sce-imports-", dir=Path(exe).resolve().parent) as directory:
    path = Path(directory) / "imports λ.elf"
    path.write_bytes(payload)
    result = run("imports", path, "--json")
    check(result.returncode == 0 and not result.stderr, result.stderr)
    report = json.loads(result.stdout)
    check(report["schema_version"] == 1 and report["operation"] == "imports", "schema")
    check(report["type"] == "ET_SCE_DYNEXEC" and report["file_size"] == len(payload), "file metadata")
    check(report["resolution_performed"] is False and report["execution_supported"] is False, "capability flags")
    check(report["needed"] == ["libkernel.prx", "libc.prx"], "DT_NEEDED order")
    check([(m["name"], m["id"], m["encoded_id"], m["version_major"], m["version_minor"])
           for m in report["modules"]] == [("libkernel", 1, "B", 1, 1), ("libc", 2, "C", 1, 1)], "modules")
    check([(l["name"], l["id"], l["encoded_id"], l["version"]) for l in report["libraries"]] ==
          [("libkernel", 1, "B", 1), ("libc", 0x41, "BB", 1), ("libSceLibcInternal", 0x1041, "BBB", 1)],
          "libraries and 1-3 character ID encoding")
    library_names = {i: n for n, i, _, _ in LIBRARIES}
    module_names = {i: n for n, i, _, _ in MODULES}
    expected = [{"nid": name_to_nid(n), "library": library_names[lib], "module": module_names[mod],
                 "type": {1: "object", 2: "function"}[kind], "bind": {1: "global", 2: "weak"}[bind]}
                for n, lib, mod, kind, bind in IMPORTS]
    check(report["imports"] == expected, "imports in table order, excluding the defined export")
    check(report["symbol_entries"] == 7 and report["other_undefined"] == ["plain_undefined"], "symbol accounting")
    text = run("imports", path)
    check(text.returncode == 0 and "Imports: 4 of 7 symbol entries" in text.stdout, "text summary")
    check("hcuQgD53UxM libc libc function\n" in text.stdout and " weak\n" in text.stdout, "text imports")
    check(text.stdout.endswith("nothing was resolved, relocated or executed.\n"), "text status")
    # Existing inspect contract is unchanged for the same file.
    inspected = json.loads(run("inspect", path, "--json").stdout)
    check("imports" not in inspected and inspected["execution_supported"] is False, "inspect unchanged")

    nid_name = string[f"{name_to_nid('printf')}#BB#C"]
    cases = [
        (make_probe(), "missing_dynamic"),
        (patched((layout["dynlib_phdr"], "<I", 0x61000001)), "missing_dynlibdata"),
        (patched((layout["dynlib_phdr"], "<I", 2)), "duplicate_dynamic_segment"),
        (patched((layout["dynamic"] + (layout["dynamic_entries"] - 1) * 16, "<Q", 0x6FFFFFFF)),
         "missing_dynamic_terminator"),
        (patched((tag[0x61000035], "<Q", 0x6FFFFFFF)), "missing_string_table"),
        (patched((tag[0x61000039], "<Q", 0x6FFFFFFF)), "missing_symbol_table"),
        (patched((tag[0x6100003B], "<Q", 0x61000035)), "duplicate_dynamic_tag"),
        (patched((tag[0x61000037] + 8, "<Q", 1 << 40)), "string_table_out_of_bounds"),
        (patched((tag[0x6100003F] + 8, "<Q", 1 << 40)), "symbol_table_out_of_bounds"),
        (patched((tag[0x6100003B] + 8, "<Q", 32)), "bad_symbol_entry_size"),
        (patched((tag[0x6100003F] + 8, "<Q", 7 * 24 - 1)), "bad_symbol_entry_size"),
        (patched((tag[1] + 8, "<Q", 1 << 30)), "string_out_of_bounds"),
        (patched((tag[0x61000037] + 8, "<Q", string["plain_undefined"] - layout["strings"] + 3)),
         "unterminated_string"),
        (patched((string["libc"], "<B", 0x07)), "bad_string"),
        (patched((nid_name, "<B", ord("!"))), "bad_nid"),
        (patched((nid_name + 12, "<B", ord("Z"))), "unknown_library_id"),
        (patched((nid_name + 15, "<B", ord("Z"))), "unknown_module_id"),
        (patched((tag[0x61000015] + 8 + 6, "<H", 0x41)), "duplicate_library_id"),
        (patched((tag[0x6100000F] + 8 + 6, "<H", 2)), "duplicate_module_id"),
        (patched((0, "<I", 0x464C4500)), "bad_magic"),
        # Inspector size limits, with the file extended so the ranges are otherwise valid.
        (patched((layout["dynamic_phdr"] + 32, "<Q", (1 << 20) + 16)).ljust(layout["dynamic"] + (1 << 20) + 16, b"\0"),
         "table_too_large"),
        (patched((layout["dynlib_phdr"] + 32, "<Q", (16 << 20) + 1), (tag[0x61000037] + 8, "<Q", (16 << 20) + 1))
         .ljust(layout["strings"] + (16 << 20) + 1, b"\0"), "table_too_large"),
    ]
    for data, code in cases:
        path.write_bytes(data)
        result = run("imports", path, "--json")
        check(result.returncode == 1 and not result.stdout and f"error[{code}]" in result.stderr,
              f"{code}: {result.returncode} {result.stderr}")
    path.write_bytes(payload)
    for args in [("imports",), ("imports", path, "--bogus"), ("imports", path, "--json", "extra")]:
        check(run(*args).returncode == 2, f"usage exit: {args}")
    check("ps4-runtime imports <file> [--json]" in run("--help").stdout, "help lists imports")
print("SCE import inventory checks passed")
