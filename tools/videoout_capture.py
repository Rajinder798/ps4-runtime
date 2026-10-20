# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Test-only reviewed key transport to our supervisor's engine SDL window.

No foreground switching or system-wide keyboard injection. F12 requests the
existing Vulkan screenshot; N/B exercise keyboard mapping to Cross/Circle.
WM_CLOSE uses the same ownership checks. Transport alone is not evidence of
guest pad input or successful shutdown.
"""
import ctypes as c
from ctypes import wintypes as w
import os


def _owned_window(supervisor_pid, engine):
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
    return user, windows[0], owners[0]


def send_key(supervisor_pid, engine, key, down):
    if key not in ("capture", "cross", "circle", "cross-g") or type(down) is not bool:
        raise ValueError("Only reviewed test keys and explicit press/release are supported")
    user, window, pid = _owned_window(supervisor_pid, engine)
    def bind(name, result, *arguments):
        function = getattr(user, name)
        function.restype, function.argtypes = result, arguments
        return function
    post = bind("PostMessageW", w.BOOL, w.HWND, w.UINT, w.WPARAM, w.LPARAM)
    map_key = bind("MapVirtualKeyW", w.UINT, w.UINT, w.UINT)
    code = {"capture": 0x7b, "cross": 0x4e, "circle": 0x42, "cross-g": 0x47}[key]  # F12 / N / B / G.
    scan = map_key(code, 0)
    if not post(window, 0x100 if down else 0x101, code, (0 if down else 0xc0000000) | (scan << 16) | 1):
        raise c.WinError(c.get_last_error())
    return dict(root_pid=pid, key=key, down=down, transport="owned SDL window WM_KEYDOWN/UP")


def request_close(supervisor_pid, engine):
    user, window, pid = _owned_window(supervisor_pid, engine)
    post = user.PostMessageW
    post.restype, post.argtypes = w.BOOL, (w.HWND, w.UINT, w.WPARAM, w.LPARAM)
    if not post(window, 0x10, 0, 0):  # WM_CLOSE: same request as the window close button.
        raise c.WinError(c.get_last_error())
    return dict(root_pid=pid, transport="owned SDL window WM_CLOSE")


def request_screenshot(supervisor_pid, engine):
    result = send_key(supervisor_pid, engine, "capture", True)
    send_key(supervisor_pid, engine, "capture", False)
    return dict(root_pid=result["root_pid"], transport="owned SDL window WM_KEYDOWN/UP F12")
