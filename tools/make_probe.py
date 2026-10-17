# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Generate an original synthetic ELF fixture; no SDK, keys, or game data required."""
import argparse
from pathlib import Path
import struct


def make_probe():
    # ABI-neutral instruction stub: mov eax, 42; ret. This is not a PS4 process entry.
    code = bytes.fromhex("b8 2a 00 00 00 c3")
    image = bytearray(0x2008)
    ident = b"\x7fELF" + bytes([2, 1, 1, 9, 0]) + bytes(7)
    struct.pack_into("<16sHHIQQQIHHHHHH", image, 0, ident, 0xFE10, 62, 1,
                     0x1000, 64, 0, 0, 64, 56, 2, 0, 0, 0)
    struct.pack_into("<IIQQQQQQ", image, 64, 1, 5, 0x1000, 0x1000, 0,
                     len(code), len(code), 0x1000)
    # A data segment with a zero-fill tail exercises a future mapper's BSS handling.
    struct.pack_into("<IIQQQQQQ", image, 120, 1, 6, 0x2000, 0x4000, 0, 8, 0x1000, 0x1000)
    image[0x1000:0x1000 + len(code)] = code
    image[0x2000:0x2008] = b"PS4PROBE"
    return image


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(make_probe())
    print(f"Wrote {len(make_probe())} bytes to {args.output}")
