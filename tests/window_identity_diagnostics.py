# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
"""Opt-in, read-only diagnostics for an already verified window binding.

WinEvents are scoped to one process, out of context, on a dedicated message-loop
thread. They never establish ownership, select a replacement or inject input.
"""
import ctypes as c
from ctypes import wintypes as w
import queue
import threading
import time


EVENTS = {0x8000: 'create', 0x8001: 'destroy', 0x8002: 'show',
          0x8003: 'hide', 0x800b: 'location_change'}


def lifecycle_record(pid, bound, event, window, object_id, child_id, thread, event_ms):
    # OBJID_WINDOW / CHILDID_SELF only: no accessibility contents or global keys.
    if event not in EVENTS or not window or object_id != 0 or child_id != 0:
        return None
    return dict(event='owned_process_window_event', kind=EVENTS[event],
                scoped_pid=pid, window_handle=window, bound_window=window == bound,
                event_thread_id=thread, event_tick_ms=event_ms,
                received_qpc_seconds=time.perf_counter(), received_unix_ns=time.time_ns())


class WindowIdentityDiagnostics:
    def __init__(self, binding, emit):
        self.user, self.window, self.pid = binding
        if type(self.pid) is not int or self.pid <= 0 or not self.window:
            raise ValueError('Lifecycle diagnostics require a nonzero verified process/window binding')
        self.emit = emit
        self.kernel = c.WinDLL('kernel32', use_last_error=True)
        self.records = queue.SimpleQueue()
        self.stop = threading.Event()
        self.ready = threading.Event()
        self.failure = None
        self.process = None
        self.worker = None
        self.closed = False
        self.event_count = 0
        for library, name, result, arguments in (
            (self.kernel, 'OpenProcess', w.HANDLE, [w.DWORD, w.BOOL, w.DWORD]),
            (self.kernel, 'CloseHandle', w.BOOL, [w.HANDLE]),
            (self.kernel, 'WaitForSingleObject', w.DWORD, [w.HANDLE, w.DWORD]),
            (self.kernel, 'GetProcessTimes', w.BOOL, [w.HANDLE] + [c.POINTER(w.FILETIME)] * 4),
            (self.kernel, 'GetExitCodeProcess', w.BOOL, [w.HANDLE, c.POINTER(w.DWORD)]),
            (self.user, 'IsWindow', w.BOOL, [w.HWND]),
            (self.user, 'GetWindowThreadProcessId', w.DWORD, [w.HWND, c.POINTER(w.DWORD)]),
        ):
            function = getattr(library, name)
            function.restype, function.argtypes = result, arguments
        try:
            # Retain the exact process object across PID reuse; no terminate/write rights.
            self.process = self.kernel.OpenProcess(0x100000 | 0x1000, False, self.pid)
            if not self.process:
                raise c.WinError(c.get_last_error())
            creation, exit_time, kernel_time, user_time = (w.FILETIME() for _ in range(4))
            if not self.kernel.GetProcessTimes(self.process, c.byref(creation), c.byref(exit_time),
                                               c.byref(kernel_time), c.byref(user_time)):
                raise c.WinError(c.get_last_error())
            self.creation_time = (creation.dwHighDateTime << 32) | creation.dwLowDateTime
            self.worker = threading.Thread(target=self._watch, name='owned-window-events', daemon=True)
            self.worker.start()
            if not self.ready.wait(5):
                raise RuntimeError('Window lifecycle diagnostic startup timed out')
            if self.failure:
                raise RuntimeError(self.failure)
            self.emit('owned_window_diagnostics_started', scoped_pid=self.pid, window_handle=self.window,
                      process_creation_filetime=self.creation_time, qpc_seconds=time.perf_counter(),
                      unix_ns=time.time_ns(), mode='process-scoped out-of-context WinEvents; no input capture')
            self.snapshot('bound')
        except BaseException:
            self.close()
            raise

    def _watch(self):
        # Use a separate DLL object so message-loop prototypes cannot affect Tk or callers.
        user = c.WinDLL('user32', use_last_error=True)
        callback_type = c.WINFUNCTYPE(None, w.HANDLE, w.DWORD, w.HWND,
                                     w.LONG, w.LONG, w.DWORD, w.DWORD)
        user.SetWinEventHook.restype = w.HANDLE
        user.SetWinEventHook.argtypes = [w.DWORD, w.DWORD, w.HMODULE, callback_type,
                                        w.DWORD, w.DWORD, w.DWORD]
        user.UnhookWinEvent.restype, user.UnhookWinEvent.argtypes = w.BOOL, [w.HANDLE]
        user.PeekMessageW.restype = w.BOOL
        user.PeekMessageW.argtypes = [c.POINTER(w.MSG), w.HWND, w.UINT, w.UINT, w.UINT]
        hooks = []

        @callback_type
        def receive(hook, event, window, object_id, child_id, thread, event_ms):
            try:
                record = lifecycle_record(self.pid, self.window, event, window,
                                          object_id, child_id, thread, event_ms)
                if record is not None:
                    self.records.put(record)
            except BaseException as error:
                self.failure = f'Window lifecycle callback failed: {error}'

        try:
            for first, last in ((0x8000, 0x8003), (0x800b, 0x800b)):
                # WINEVENT_OUTOFCONTEXT=0: never load code into the target process.
                hook = user.SetWinEventHook(first, last, None, receive, self.pid, 0, 0)
                if not hook:
                    raise RuntimeError(f'SetWinEventHook failed (last-error {c.get_last_error()})')
                hooks.append(hook)
            self.ready.set()
            message = w.MSG()
            while not self.stop.is_set():
                # PeekMessage also dispatches the asynchronous WinEvent callbacks.
                while user.PeekMessageW(c.byref(message), None, 0, 0, 1):
                    pass  # This thread owns no windows and receives no application input.
                self.stop.wait(.01)
        except BaseException as error:
            self.failure = f'Window lifecycle observer failed: {error}'
        finally:
            for hook in reversed(hooks):
                if not user.UnhookWinEvent(hook):
                    self.failure = f'Window lifecycle unhook failed: {c.get_last_error()}'
            self.ready.set()

    def drain(self):
        while True:
            try:
                record = self.records.get_nowait()
            except queue.Empty:
                break
            self.event_count += 1
            event = record.pop('event')
            self.emit(event, **record)
        if self.failure:
            raise RuntimeError(self.failure)

    def snapshot(self, reason):
        self.drain()
        pid = w.DWORD()
        c.set_last_error(0)
        thread = self.user.GetWindowThreadProcessId(self.window, c.byref(pid))
        error = c.get_last_error() if not thread else None
        wait = self.kernel.WaitForSingleObject(self.process, 0)
        wait_error = c.get_last_error() if wait == 0xffffffff else None
        code = w.DWORD()
        got_code = self.kernel.GetExitCodeProcess(self.process, c.byref(code))
        code_error = c.get_last_error() if not got_code else None
        # These are separate, racy observations, never permission to use the HWND.
        self.emit('owned_window_identity_snapshot', reason=reason, window_handle=self.window,
                  expected_root_pid=self.pid, process_creation_filetime=self.creation_time,
                  observed_pid=pid.value, observed_thread=thread, query_error=error,
                  is_window_after_query=bool(self.user.IsWindow(self.window)),
                  process_wait_result=wait, process_wait_error=wait_error,
                  process_exit_code=code.value if got_code else None, process_exit_query_error=code_error,
                  qpc_seconds=time.perf_counter(), unix_ns=time.time_ns())

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.stop.set()
        try:
            if self.worker:
                self.worker.join(5)
                if self.worker.is_alive():
                    raise RuntimeError('Window lifecycle observer did not stop')
            self.drain()
        finally:
            if self.process:
                success = self.kernel.CloseHandle(self.process)
                self.process = None
                if not success:
                    raise c.WinError(c.get_last_error())
            self.emit('owned_window_diagnostics_closed', scoped_pid=self.pid, window_handle=self.window,
                      events=self.event_count, qpc_seconds=time.perf_counter(), unix_ns=time.time_ns())
