# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Generate an original synthetic SCE ELF with declared imports; no SDK, keys, or game data.

The file is metadata-only: its single code byte is never executed. Names are
ordinary public PS4 API identifiers; their NIDs are derived here, not copied.
"""
import argparse
import hashlib
from pathlib import Path
import struct

CODES = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+-"
# Public NID derivation salt, as used by the pinned shadPS4 revision's StringToNid.
NID_SALT = bytes.fromhex("518d64a635ded8c1e6b039b1c3e55230")

DT_NEEDED, DT_SCE_NEEDED_MODULE, DT_SCE_IMPORT_LIB = 1, 0x6100000F, 0x61000015
DT_SCE_STRTAB, DT_SCE_STRSZ, DT_SCE_SYMTAB, DT_SCE_SYMENT, DT_SCE_SYMTABSZ = (
    0x61000035, 0x61000037, 0x61000039, 0x6100003B, 0x6100003F)

# (name, id, major, minor) and (name, id, version, module id)
MODULES = [("libkernel", 1, 1, 1), ("libc", 2, 1, 1)]
LIBRARIES = [("libkernel", 1, 1, 1), ("libc", 0x41, 1, 2), ("libSceLibcInternal", 0x1041, 1, 2)]
# (symbol name, library id, module id, type, bind); type 2=function, 1=object; bind 1=global, 2=weak
IMPORTS = [("sceKernelUsleep", 1, 1, 2, 1), ("printf", 0x41, 2, 2, 1),
           ("__stack_chk_guard", 0x1041, 2, 1, 1), ("sceKernelGetProcParam", 1, 1, 2, 2)]


def name_to_nid(name):
    digest = int.from_bytes(hashlib.sha1(name.encode("ascii") + NID_SALT).digest()[:8], "little")
    return "".join(CODES[(digest >> (58 - i * 6)) & 0x3F] for i in range(10)) + CODES[(digest & 0xF) * 4]


def encode_id(value):
    digits = [(value >> 12) & 0x3F] if value >= 0x1000 else []
    digits += [(value >> 6) & 0x3F] if value >= 0x40 else []
    return "".join(CODES[d] for d in digits + [value & 0x3F])


def make_sce_imports():
    """Return the fixture bytes and the file offsets tests use to make invalid variants."""
    strings = bytearray(b"\0")
    offsets = {}

    def string(text):
        if text not in offsets:
            offsets[text] = len(strings)
            strings.extend(text.encode("ascii") + b"\0")
        return offsets[text]

    needed = [string("libkernel.prx"), string("libc.prx")]
    module_values = [string(n) | minor << 32 | major << 40 | i << 48 for n, i, major, minor in MODULES]
    library_values = [string(n) | version << 32 | i << 48 for n, i, version, _ in LIBRARIES]
    # Index 0 is the null symbol; then imports, one defined export and one plain undefined name.
    symbols = [(0, 0, 0)]
    symbols += [(string(f"{name_to_nid(n)}#{encode_id(lib)}#{encode_id(mod)}"), bind << 4 | kind, 0)
                for n, lib, mod, kind, bind in IMPORTS]
    symbols += [(string(f"{name_to_nid('module_start')}#B#B"), 1 << 4 | 2, 0x1000),
                (string("plain_undefined"), 1 << 4 | 2, 0)]

    symbol_table_offset = (len(strings) + 7) & ~7
    dynlib = bytearray(strings) + bytes(symbol_table_offset - len(strings))
    for name, info, value in symbols:
        dynlib += struct.pack("<IBBHQQ", name, info, 0, 0, value, 0)
    tags = [(DT_NEEDED, v) for v in needed] + [(DT_SCE_NEEDED_MODULE, v) for v in module_values]
    tags += [(DT_SCE_IMPORT_LIB, v) for v in library_values]
    tags += [(DT_SCE_STRTAB, 0), (DT_SCE_STRSZ, len(strings)), (DT_SCE_SYMTAB, symbol_table_offset),
             (DT_SCE_SYMENT, 24), (DT_SCE_SYMTABSZ, len(symbols) * 24), (0, 0)]
    dynamic = b"".join(struct.pack("<QQ", tag, value) for tag, value in tags)

    dynamic_offset, dynlib_offset = 0x2000, 0x3000
    image = bytearray(dynlib_offset + len(dynlib))
    ident = b"\x7fELF" + bytes([2, 1, 1, 9, 0]) + bytes(7)
    struct.pack_into("<16sHHIQQQIHHHHHH", image, 0, ident, 0xFE10, 62, 1,
                     0x1000, 64, 0, 0, 64, 56, 3, 0, 0, 0)
    struct.pack_into("<IIQQQQQQ", image, 64, 1, 5, 0x1000, 0x1000, 0, 1, 1, 0x1000)
    struct.pack_into("<IIQQQQQQ", image, 120, 2, 4, dynamic_offset, 0, 0, len(dynamic), len(dynamic), 8)
    struct.pack_into("<IIQQQQQQ", image, 176, 0x61000000, 4, dynlib_offset, 0, 0, len(dynlib), 0, 0x10)
    image[0x1000] = 0xC3
    image[dynamic_offset:dynamic_offset + len(dynamic)] = dynamic
    image[dynlib_offset:] = dynlib
    layout = {
        "dynamic_phdr": 120, "dynlib_phdr": 176, "dynamic": dynamic_offset,
        "tag": {tag: dynamic_offset + i * 16 for i, (tag, _) in reversed(list(enumerate(tags)))},
        "strings": dynlib_offset, "string": {k: dynlib_offset + v for k, v in offsets.items()},
        "symbols": dynlib_offset + symbol_table_offset, "dynamic_entries": len(tags),
    }
    return bytes(image), layout


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    payload, _ = make_sce_imports()
    args.output.write_bytes(payload)
    print(f"Wrote {len(payload)} bytes to {args.output}")
