# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later

"""Read-only, test-only state of an already ownership-checked SDL window.

No hooks, global key logging, focus changes or audio controls. Polling can miss
transitions between samples; record the actual largest gap, including image QA.
"""
import ctypes as c
from ctypes import wintypes as w
import time


class OwnedWindowTrace:
    def __init__(self, binding, emit):
        self.user, self.window, self.pid = binding
        self.emit = emit
        self.previous = self.last_at = None
        self.samples, self.max_gap = 0, 0

        class GuiInfo(c.Structure):
            _fields_ = [("size", w.DWORD), ("flags", w.DWORD),
                        ("active", w.HWND), ("focus", w.HWND), ("capture", w.HWND),
                        ("menu", w.HWND), ("move", w.HWND), ("caret", w.HWND), ("rect", w.RECT)]
        self.GuiInfo = GuiInfo
        for name, result, arguments in (
            ("GetForegroundWindow", w.HWND, []),
            ("GetWindowThreadProcessId", w.DWORD, [w.HWND, c.POINTER(w.DWORD)]),
            ("GetGUIThreadInfo", w.BOOL, [w.DWORD, c.POINTER(GuiInfo)]),
            ("IsIconic", w.BOOL, [w.HWND]),
        ):
            function = getattr(self.user, name)
            function.restype, function.argtypes = result, arguments

    def poll(self):
        pid = w.DWORD()
        thread = self.user.GetWindowThreadProcessId(self.window, c.byref(pid))
        if not thread or pid.value != self.pid:
            raise RuntimeError("Owned window identity changed during input observation")
        info = self.GuiInfo(size=c.sizeof(self.GuiInfo))
        if not self.user.GetGUIThreadInfo(thread, c.byref(info)):
            raise c.WinError(c.get_last_error())
        state = dict(foreground=self.user.GetForegroundWindow() == self.window,
                     thread_active=info.active == self.window, thread_focus=info.focus == self.window,
                     minimized=bool(self.user.IsIconic(self.window)),
                     menu_mode=bool(info.flags & 0x1c), move_size=bool(info.flags & 2))
        now = time.monotonic()
        if self.last_at is not None:
            self.max_gap = max(self.max_gap, now - self.last_at)
        self.last_at = now
        self.samples += 1
        if state != self.previous:
            self.emit("owned_window_state", root_pid=self.pid, **state)
            self.previous = state
        return state

    def summary(self):
        return dict(samples=self.samples, max_sample_gap_seconds=self.max_gap,
                    observation="read-only polling; transitions between samples may be missed")
