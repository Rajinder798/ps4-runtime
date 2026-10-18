# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Ordinary Windows process fixtures; these never constitute guest execution."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

mode, directory = sys.argv[1], Path(sys.argv[2])
if mode == "leaf":
    while True:
        with (directory / "heartbeat.txt").open("a") as stream:
            stream.write("alive\n")
        time.sleep(0.03)
elif mode in ("tree", "orphan"):
    child = subprocess.Popen([sys.executable, __file__, "leaf", str(directory)])
    (directory / "child-pid.txt").write_text(str(child.pid))
    time.sleep(0.5 if mode == "orphan" else 60)
elif mode == "arguments":
    print("ordinary stdout", flush=True)
    print("ordinary stderr", file=sys.stderr, flush=True)
    (directory / "arguments.json").write_text(json.dumps(sys.argv[3:]), encoding="utf-8")
    time.sleep(60)
elif mode == "crash":
    sys.exit(17)
elif mode == "environment":
    (directory / "environment.json").write_text(json.dumps({"driver": os.environ.get("SDL_AUDIO_DRIVER")}))
elif mode == "noise":
    while True:
        print("output " * 1000, flush=True)
elif mode in ("window", "window-ignore", "window-orphan"):
    # An ordinary owned Win32 window, not SDL/PS4 execution evidence.
    import ctypes as c
    from ctypes import wintypes as w
    user = c.WinDLL("user32", use_last_error=True)
    callback = c.WINFUNCTYPE(c.c_ssize_t, w.HWND, w.UINT, w.WPARAM, w.LPARAM)
    user.DefWindowProcW.restype = c.c_ssize_t
    user.DefWindowProcW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
    user.DestroyWindow.argtypes = [w.HWND]
    @callback
    def procedure(window, message, a, b):
        if message == 0x10:
            (directory / "close-observed.txt").write_text("WM_CLOSE")
            if mode != "window-ignore":
                user.DestroyWindow(window)
            return 0
        if message == 2:
            user.PostQuitMessage(0)
            return 0
        return user.DefWindowProcW(window, message, a, b)
    class WindowClass(c.Structure):
        _fields_ = [("style", w.UINT), ("procedure", callback), ("class_extra", c.c_int),
                    ("window_extra", c.c_int), ("instance", w.HINSTANCE), ("icon", w.HICON),
                    ("cursor", w.HANDLE), ("background", w.HBRUSH), ("menu", w.LPCWSTR), ("name", w.LPCWSTR)]
    kind = WindowClass(procedure=procedure, name="SDLRuntimeShutdownTest")
    user.RegisterClassW.argtypes = [c.POINTER(WindowClass)]
    if not user.RegisterClassW(c.byref(kind)):
        raise c.WinError(c.get_last_error())
    user.CreateWindowExW.restype = w.HWND
    user.CreateWindowExW.argtypes = [w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD, c.c_int, c.c_int,
                                   c.c_int, c.c_int, w.HWND, w.HMENU, w.HINSTANCE, w.LPVOID]
    window = user.CreateWindowExW(0, kind.name, "ordinary shutdown test", 0, 0, 0, 100, 100, None, None, None, None)
    if not window:
        raise c.WinError(c.get_last_error())
    if mode == "window-orphan":
        child = subprocess.Popen([sys.executable, __file__, "leaf", str(directory)])
        (directory / "child-pid.txt").write_text(str(child.pid))
    (directory / "window-ready.txt").write_text("ready")
    message = w.MSG()
    user.GetMessageW.argtypes = [c.POINTER(w.MSG), w.HWND, w.UINT, w.UINT]
    user.DispatchMessageW.argtypes = [c.POINTER(w.MSG)]
    user.DispatchMessageW.restype = c.c_ssize_t
    while user.GetMessageW(c.byref(message), None, 0, 0) > 0:
        user.TranslateMessage(c.byref(message))
        user.DispatchMessageW(c.byref(message))
else:
    time.sleep(60)
