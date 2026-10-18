# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Test-only F12 transport to the SDL window of our supervisor's engine child.

No foreground switching or system-wide keyboard injection. This requests the
engine's existing Vulkan screenshot; it is not evidence of guest pad input.
"""
import ctypes as c
from ctypes import wintypes as w
import os


def request_screenshot(supervisor_pid, engine):
    kernel, user = c.WinDLL("kernel32", use_last_error=True), c.WinDLL("user32", use_last_error=True)
    def bind(lib, name, result, *arguments):
        function = getattr(lib, name)
        function.restype, function.argtypes = result, arguments
        return function
    close = bind(kernel, "CloseHandle", w.BOOL, w.HANDLE)
    snapshot = bind(kernel, "CreateToolhelp32Snapshot", w.HANDLE, w.DWORD, w.DWORD)
    class Process(c.Structure):
        _fields_ = [("size", w.DWORD), ("usage", w.DWORD), ("pid", w.DWORD),
                    ("heap", c.c_size_t), ("module", w.DWORD), ("threads", w.DWORD),
                    ("parent", w.DWORD), ("priority", w.LONG), ("flags", w.DWORD), ("name", w.WCHAR * 260)]
    first = bind(kernel, "Process32FirstW", w.BOOL, w.HANDLE, c.POINTER(Process))
    following = bind(kernel, "Process32NextW", w.BOOL, w.HANDLE, c.POINTER(Process))
    handle = snapshot(2, 0)
    if handle == c.c_void_p(-1).value:
        raise c.WinError(c.get_last_error())
    children = []
    try:
        item = Process()
        item.size = c.sizeof(item)
        success = first(handle, c.byref(item))
        while success:
            if item.parent == supervisor_pid:
                children.append(item.pid)
            success = following(handle, c.byref(item))
    finally:
        close(handle)
    open_process = bind(kernel, "OpenProcess", w.HANDLE, w.DWORD, w.BOOL, w.DWORD)
    query = bind(kernel, "QueryFullProcessImageNameW", w.BOOL, w.HANDLE, w.DWORD, w.LPWSTR, c.POINTER(w.DWORD))
    owners = []
    for pid in children:
        process = open_process(0x1000, False, pid)
        if not process:
            continue
        try:
            path, size = c.create_unicode_buffer(32768), w.DWORD(32768)
            if query(process, 0, path, c.byref(size)) and os.path.normcase(path.value) == os.path.normcase(str(engine.resolve())):
                owners.append(pid)
        finally:
            close(process)
    if len(owners) != 1:
        raise ValueError("Expected exactly one engine child owned by this supervisor")
    callback_type = c.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
    enum = bind(user, "EnumWindows", w.BOOL, callback_type, w.LPARAM)
    get_pid = bind(user, "GetWindowThreadProcessId", w.DWORD, w.HWND, c.POINTER(w.DWORD))
    get_class = bind(user, "GetClassNameW", c.c_int, w.HWND, w.LPWSTR, c.c_int)
    windows = []
    @callback_type
    def visit(window, unused):
        pid, name = w.DWORD(), c.create_unicode_buffer(256)
        get_pid(window, c.byref(pid))
        if pid.value == owners[0] and get_class(window, name, 256) and name.value.startswith("SDL"):
            windows.append(window)
        return True
    if not enum(visit, 0) or len(windows) != 1:
        raise ValueError("Expected one SDL window in the owned engine process")
    post = bind(user, "PostMessageW", w.BOOL, w.HWND, w.UINT, w.WPARAM, w.LPARAM)
    map_key = bind(user, "MapVirtualKeyW", w.UINT, w.UINT, w.UINT)
    scan = map_key(0x7b, 0)  # F12, the pinned default game-only screenshot hotkey.
    for message, flags in ((0x100, 0), (0x101, 0xc0000000)):
        if not post(windows[0], message, 0x7b, flags | (scan << 16) | 1):
            raise c.WinError(c.get_last_error())
    return dict(root_pid=owners[0], transport="owned SDL window WM_KEYDOWN/UP F12")
