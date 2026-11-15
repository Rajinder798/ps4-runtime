# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Write and read minimal PSF (param.sfo) files for research fixtures.

Layout, as parsed by the pinned engine's PSF::Open: a 20-byte header (magic
`\\0PSF`, then little-endian version 1.1, key-table offset, data-table offset and
entry count), 16-byte index entries (key offset, format, length, maximum length,
data offset), a NUL-terminated key table and a data table. Keys are sorted.
"""
import struct

MAGIC, VERSION = b"\0PSF", 0x101
BINARY, TEXT, INTEGER = 0x0004, 0x0204, 0x0404


def write(entries):
    """Encode {key: str | int | bytes}. Text is UTF-8 and NUL-terminated."""
    keys, data, index = bytearray(), bytearray(), bytearray()
    for key in sorted(entries):
        value = entries[key]
        if isinstance(value, str):
            kind, payload = TEXT, value.encode("utf-8") + b"\0"
        elif isinstance(value, bool) or not isinstance(value, (int, bytes)):
            raise ValueError(f"Unsupported PSF value for {key}")
        elif isinstance(value, int):
            kind, payload = INTEGER, struct.pack("<i", value)
        else:
            kind, payload = BINARY, value
        maximum = (len(payload) + 3) & ~3
        index += struct.pack("<HHIII", len(keys), kind, len(payload), maximum, len(data))
        keys += key.encode("ascii") + b"\0"
        data += payload.ljust(maximum, b"\0")
    keys = keys.ljust((len(keys) + 3) & ~3, b"\0")
    key_table = 20 + len(index)
    header = MAGIC + struct.pack("<IIII", VERSION, key_table, key_table + len(keys), len(entries))
    return bytes(header + index + keys + data)


def read(blob):
    """Decode a PSF file, rejecting anything outside its own bounds."""
    if len(blob) < 20 or blob[:4] != MAGIC:
        raise ValueError("Not a PSF file")
    version, key_table, data_table, count = struct.unpack_from("<IIII", blob, 4)
    if version not in (0x100, 0x101) or 20 + count * 16 > key_table or not key_table <= data_table <= len(blob):
        raise ValueError("Invalid PSF header")
    result = {}
    for i in range(count):
        key_offset, kind, length, maximum, data_offset = struct.unpack_from("<HHIII", blob, 20 + i * 16)
        end = blob.find(b"\0", key_table + key_offset, data_table)
        start = data_table + data_offset
        if end < 0 or length > maximum or start + length > len(blob):
            raise ValueError("PSF entry out of bounds")
        key = blob[key_table + key_offset:end].decode("ascii")
        value = blob[start:start + length]
        if kind == TEXT:
            result[key] = value.split(b"\0", 1)[0].decode("utf-8")
        elif kind == INTEGER and length == 4:
            result[key] = struct.unpack("<i", value)[0]
        elif kind == BINARY:
            result[key] = bytes(value)
        else:
            raise ValueError(f"Unsupported PSF entry {key}")
    return result
