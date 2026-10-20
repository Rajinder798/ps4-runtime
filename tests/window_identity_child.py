# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
"""Hidden, ordinary Win32 test windows; no guest, controller or audio access."""
import ctypes as c
from ctypes import wintypes as w
import json
import os
from pathlib import Path
import sys
import time


def main():
    directory = Path(sys.argv[1])
    user = c.WinDLL('user32', use_last_error=True)
    kernel = c.WinDLL('kernel32', use_last_error=True)
    callback_type = c.WINFUNCTYPE(c.c_ssize_t, w.HWND, w.UINT, w.WPARAM, w.LPARAM)
    user.DefWindowProcW.restype = c.c_ssize_t
    user.DefWindowProcW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
    user.DestroyWindow.restype, user.DestroyWindow.argtypes = w.BOOL, [w.HWND]
    kernel.GetCurrentThreadId.restype = w.DWORD

    def record(event, window):
        with (directory / 'child.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(dict(event=event, window_handle=window, pid=os.getpid(),
                thread_id=kernel.GetCurrentThreadId(), qpc_seconds=time.perf_counter())) + '\n')

    @callback_type
    def procedure(window, message, a, b):
        if message == 2:
            record('WM_DESTROY', window)
        return user.DefWindowProcW(window, message, a, b)

    class WindowClass(c.Structure):
        _fields_ = [('style', w.UINT), ('procedure', callback_type), ('class_extra', c.c_int),
                    ('window_extra', c.c_int), ('instance', w.HINSTANCE), ('icon', w.HICON),
                    ('cursor', w.HANDLE), ('background', w.HBRUSH), ('menu', w.LPCWSTR), ('name', w.LPCWSTR)]
    kind = WindowClass(procedure=procedure, name='SDLWindowIdentityHostTest')
    user.RegisterClassW.argtypes = [c.POINTER(WindowClass)]
    if not user.RegisterClassW(c.byref(kind)):
        raise c.WinError(c.get_last_error())
    user.CreateWindowExW.restype = w.HWND
    user.CreateWindowExW.argtypes = [w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD, c.c_int, c.c_int,
                                   c.c_int, c.c_int, w.HWND, w.HMENU, w.HINSTANCE, w.LPVOID]
    user.PeekMessageW.argtypes = [c.POINTER(w.MSG), w.HWND, w.UINT, w.UINT, w.UINT]
    user.DispatchMessageW.restype, user.DispatchMessageW.argtypes = c.c_ssize_t, [c.POINTER(w.MSG)]

    def create(name):
        window = user.CreateWindowExW(0, kind.name, name, 0, 0, 0, 100, 100,
                                      None, None, None, None)
        if not window:
            raise c.WinError(c.get_last_error())
        record(name, window)
        temporary = directory / (name + '.tmp')
        temporary.write_text(json.dumps(dict(window=window, pid=os.getpid())), encoding='utf-8')
        temporary.replace(directory / (name + '.json'))
        return window

    window = create('initial')
    message = w.MSG()
    replaced = False
    deadline = time.monotonic() + 20
    while not (directory / 'exit.request').exists():
        if time.monotonic() > deadline:
            raise RuntimeError('Host window fixture exceeded 20-second budget')
        if window and (directory / 'destroy.request').exists() and not replaced:
            if not user.DestroyWindow(window):
                raise c.WinError(c.get_last_error())
            window = None
            (directory / 'destroyed.txt').touch()
        if not window and not replaced and (directory / 'replace.request').exists():
            window = create('replacement')
            replaced = True
        while user.PeekMessageW(c.byref(message), None, 0, 0, 1):
            user.DispatchMessageW(c.byref(message))
        time.sleep(.01)
    if window:
        user.DestroyWindow(window)


if __name__ == '__main__':
    main()
