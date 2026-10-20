# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
"""Live status snapshots with compatible Windows reader/replacement sharing."""
from contextlib import contextmanager
import json
import os


def publish_status(path, snapshot):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(snapshot), encoding="utf-8")
    if os.name == "nt" and path.exists():
        import ctypes as c
        from ctypes import wintypes as w
        kernel = c.WinDLL("kernel32", use_last_error=True)
        kernel.ReplaceFileW.argtypes = [w.LPCWSTR, w.LPCWSTR, w.LPCWSTR, w.DWORD, c.c_void_p, c.c_void_p]
        kernel.ReplaceFileW.restype = w.BOOL
        # Preserve attributes/ACLs, with no ignored errors, fallback or retry.
        if not kernel.ReplaceFileW(str(path), str(temporary), None, 0, None, None):
            raise c.WinError(c.get_last_error())
    else:
        temporary.replace(path)


@contextmanager
def open_status(path):
    if os.name != "nt":
        with path.open(encoding="utf-8") as stream:
            yield stream
        return
    import ctypes as c
    from ctypes import wintypes as w
    import msvcrt
    kernel = c.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, c.c_void_p, w.DWORD, w.DWORD, w.HANDLE]
    kernel.CreateFileW.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    # GENERIC_READ; FILE_SHARE_READ | WRITE | DELETE; OPEN_EXISTING.
    handle = kernel.CreateFileW(str(path), 0x80000000, 7, None, 3, 0, None)
    if handle == c.c_void_p(-1).value:
        raise c.WinError(c.get_last_error())
    try:
        descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    except BaseException:
        kernel.CloseHandle(handle)
        raise
    try:
        stream = os.fdopen(descriptor, "r", encoding="utf-8")
    except BaseException:
        os.close(descriptor)
        raise
    with stream:
        yield stream


def read_status(path):
    with open_status(path) as stream:
        return json.load(stream)
