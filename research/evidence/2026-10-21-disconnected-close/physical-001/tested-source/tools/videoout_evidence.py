# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Bounded decoder for the presenter's RGBA8 PNG and independent pixel oracle."""
import binascii
import hashlib
import struct
import zlib

WIDTH, HEIGHT = 640, 360
MAX_PNG_BYTES = 4 * 1024 * 1024


class CaptureMismatch(ValueError):
    pass


def expected_pixels(challenge, phase):
    if len(challenge) != 4 or len(set(challenge)) != 4 or any(c > 7 for c in challenge) or phase not in (0, 1):
        raise ValueError("Invalid palette/phase")
    colors = [bytes((255 if c & 1 else 0, 255 if c & 2 else 0, 255 if c & 4 else 0, 255)) for c in challenge]
    rows = []
    for row in range(8):
        blocks = [colors[(row + column + phase) % 4] * 80 for column in range(8)]
        rows.append(b"".join(blocks) * 45)
    return b"".join(rows)


def decode_png(data):
    """Accept only the exact bounded, noninterlaced RGBA8 screenshot format."""
    if len(data) > MAX_PNG_BYTES or data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("Invalid PNG signature/size")
    cursor, header, ended, idat_ended = 8, False, False, False
    compressed = bytearray()
    while cursor < len(data):
        if cursor + 12 > len(data):
            raise ValueError("Truncated PNG chunk")
        length, kind = struct.unpack_from(">I4s", data, cursor)
        end = cursor + 12 + length
        if end > len(data):
            raise ValueError("Truncated PNG payload")
        payload = data[cursor + 8:end - 4]
        crc, = struct.unpack_from(">I", data, end - 4)
        if binascii.crc32(kind + payload) != crc:
            raise ValueError("PNG CRC mismatch")
        if not header and kind != b"IHDR":
            raise ValueError("PNG header must be first")
        if kind == b"IHDR":
            if header or payload != struct.pack(">IIBBBBB", WIDTH, HEIGHT, 8, 6, 0, 0, 0):
                raise ValueError("Unexpected PNG dimensions/format")
            header = True
        elif kind == b"IDAT":
            if idat_ended:
                raise ValueError("Noncontiguous PNG image data")
            compressed.extend(payload)
        elif kind == b"IEND":
            if length or not compressed or end != len(data):
                raise ValueError("Invalid PNG end/trailing data")
            ended = True
            break
        elif kind[0] & 32 == 0:
            raise ValueError("Unsupported critical PNG chunk")
        if kind != b"IDAT" and compressed:
            idat_ended = True
        cursor = end
    if not ended:
        raise ValueError("Missing PNG end")
    stride = WIDTH * 4
    size = (stride + 1) * HEIGHT
    decoder = zlib.decompressobj()
    try:
        raw = decoder.decompress(compressed, size + 1)
    except zlib.error as error:
        raise ValueError("Invalid PNG compression") from error
    if len(raw) != size or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        raise ValueError("PNG decompression size/stream mismatch")
    result = bytearray()
    previous = bytearray(stride)
    for row in range(HEIGHT):
        mode = raw[row * (stride + 1)]
        if mode > 4:
            raise ValueError("Invalid PNG filter")
        current = bytearray(raw[row * (stride + 1) + 1:(row + 1) * (stride + 1)])
        for i in range(stride):
            left, above, corner = current[i - 4] if i >= 4 else 0, previous[i], previous[i - 4] if i >= 4 else 0
            if mode == 1:
                predictor = left
            elif mode == 2:
                predictor = above
            elif mode == 3:
                predictor = (left + above) // 2
            elif mode == 4:
                p = left + above - corner
                distances = (abs(p - left), abs(p - above), abs(p - corner))
                predictor = (left, above, corner)[distances.index(min(distances))]
            else:
                predictor = 0
            current[i] = (current[i] + predictor) & 255
        result.extend(current)
        previous = current
    return bytes(result)


def verify_capture(path, challenge, phase):
    if path.stat().st_size > MAX_PNG_BYTES:
        raise ValueError("PNG exceeds size limit")
    data = path.read_bytes()
    pixels = decode_png(data)
    if pixels != expected_pixels(challenge, phase):
        raise CaptureMismatch("Vulkan capture differs from independently calculated pixels")
    return dict(phase=phase, width=WIDTH, height=HEIGHT, pixels_verified=WIDTH * HEIGHT,
                png_sha256=hashlib.sha256(data).hexdigest(), rgba_sha256=hashlib.sha256(pixels).hexdigest())
