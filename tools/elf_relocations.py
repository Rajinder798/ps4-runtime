# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Read RELA relocations and program headers from a standard ELF64 file.

This is an independent oracle for the C++ SCE inventories: it reads the
pre-conversion toolchain ELF (standard sections, dynsym and program headers),
not SCE tables.
"""
from pathlib import Path
import struct
import sys

SHT_RELA = 4


def read_program_headers(path):
    data = Path(path).read_bytes()
    if data[:4] != b"\x7fELF" or data[4] != 2 or data[5] != 1:
        raise ValueError("expected a little-endian ELF64 file")
    phoff, = struct.unpack_from("<Q", data, 0x20)
    phentsize, phnum = struct.unpack_from("<HH", data, 0x36)
    if phentsize != 56 or phoff + phnum * 56 > len(data):
        raise ValueError("unexpected program header table")
    keys = ("type", "flags", "offset", "address", "physical", "file_size", "memory_size", "alignment")
    return [dict(zip(keys, struct.unpack_from("<IIQQQQQQ", data, phoff + i * 56))) for i in range(phnum)]


def read_relocations(path):
    data = Path(path).read_bytes()
    if data[:4] != b"\x7fELF" or data[4] != 2 or data[5] != 1:
        raise ValueError("expected a little-endian ELF64 file")
    shoff, = struct.unpack_from("<Q", data, 0x28)
    shentsize, shnum, shstrndx = struct.unpack_from("<HHH", data, 0x3A)
    if shentsize != 64 or shoff + shnum * 64 > len(data):
        raise ValueError("unexpected section header table")
    sections = [struct.unpack_from("<IIQQQQIIQQ", data, shoff + i * 64) for i in range(shnum)]

    def blob(index):
        section = sections[index]
        return data[section[4]:section[4] + section[5]]

    def string(table, offset):
        return table[offset:table.index(b"\0", offset)].decode("ascii")

    names = blob(shstrndx)
    entries = []
    for name, kind, _, _, offset, size, link, _, _, entsize in sections:
        if kind != SHT_RELA:
            continue
        if entsize != 24 or size % 24:
            raise ValueError("unexpected RELA entry size")
        symbols, strings = blob(link), blob(sections[link][6])
        table = "jmprel" if string(names, name) == ".rela.plt" else "rela"
        for at in range(offset, offset + size, 24):
            target, info, addend = struct.unpack_from("<QQq", data, at)
            index = info >> 32
            symbol = string(strings, struct.unpack_from("<I", symbols, index * 24)[0]) if index else ""
            entries.append({"table": table, "offset": target, "type_id": info & 0xFFFFFFFF,
                            "symbol": symbol, "addend": addend})
    return entries


if __name__ == "__main__":
    for entry in read_relocations(sys.argv[1]):
        print(entry)
