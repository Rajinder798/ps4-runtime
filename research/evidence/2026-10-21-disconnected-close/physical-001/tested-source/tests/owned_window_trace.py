# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later

"""Read-only, test-only state of an already ownership-checked SDL window.

No global key logging, focus changes or audio controls. Polling can miss
transitions between samples; record the actual largest gap, including image QA.
Opt-in process-scoped lifecycle diagnostics do not change ownership decisions.
"""
import ctypes as c
from ctypes import wintypes as w
import time


class OwnedWindowTrace:
    def __init__(self, binding, emit, *, lifecycle=False):
        self.user, self.window, self.pid = binding
        self.emit = emit
        self.previous = self.last_at = None
        self.samples, self.max_gap = 0, 0
        self.diagnostics = None

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
        if lifecycle:
            from window_identity_diagnostics import WindowIdentityDiagnostics
            self.diagnostics = WindowIdentityDiagnostics(binding, emit)

    def poll(self):
        if self.diagnostics:
            self.diagnostics.drain()
        pid = w.DWORD()
        # Read last-error immediately, and only treat it as meaningful on failure.
        c.set_last_error(0)
        thread = self.user.GetWindowThreadProcessId(self.window, c.byref(pid))
        query_error = c.get_last_error() if not thread else None
        if not thread or pid.value != self.pid:
            self.emit('owned_window_identity_failure', expected_root_pid=self.pid, observed_pid=pid.value,
                      window_handle=self.window, observed_thread=thread, win32_error=query_error,
                      qpc_seconds=time.perf_counter(), unix_ns=time.time_ns())
            if self.diagnostics:
                try:
                    self.diagnostics.snapshot('identity_failure_secondary_query')
                except (OSError, RuntimeError) as error:
                    self.emit('owned_window_secondary_diagnostic_failure', error=str(error))
            raise RuntimeError("Owned window identity changed during input observation")
        info = self.GuiInfo(size=c.sizeof(self.GuiInfo))
        if not self.user.GetGUIThreadInfo(thread, c.byref(info)):
            error = c.get_last_error()
            self.emit('owned_window_state_query_failure', root_pid=self.pid, window_handle=self.window,
                      thread_id=thread, win32_error=error, qpc_seconds=time.perf_counter(), unix_ns=time.time_ns())
            raise c.WinError(error)
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
            self.emit("owned_window_state", root_pid=self.pid, window_handle=self.window,
                      thread_id=thread, qpc_seconds=time.perf_counter(), **state)
            self.previous = state
        return state

    def summary(self):
        return dict(samples=self.samples, max_sample_gap_seconds=self.max_gap,
                    lifecycle_diagnostics=self.diagnostics is not None,
                    observation="read-only polling; transitions between samples may be missed")

    def close(self):
        if self.diagnostics:
            self.diagnostics.close()
