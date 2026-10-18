# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Measure scoped Windows waitable timers; diagnostic, not game/audio latency."""
import argparse
import ctypes
from ctypes import wintypes
import json
import platform
import statistics
import sys
import time


def measure(iterations, microseconds):
    if sys.platform != "win32" or platform.machine().lower() not in ("amd64", "x86_64"):
        raise ValueError("Requires Windows x86-64")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateWaitableTimerExW.argtypes = [ctypes.c_void_p,wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD]
    kernel.CreateWaitableTimerExW.restype = wintypes.HANDLE
    kernel.SetWaitableTimer.argtypes = [wintypes.HANDLE,ctypes.POINTER(ctypes.c_longlong),wintypes.LONG,
                                       ctypes.c_void_p,ctypes.c_void_p,wintypes.BOOL]
    kernel.SetWaitableTimer.restype = wintypes.BOOL
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE,wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    results = []
    for name, flags in (("legacy",1),("high_resolution",3)):
        timer = kernel.CreateWaitableTimerExW(None,None,flags,0x100002)  # SYNCHRONIZE | TIMER_MODIFY_STATE
        if not timer:
            raise ctypes.WinError(ctypes.get_last_error())
        samples = []
        try:
            for unused in range(iterations):
                due = ctypes.c_longlong(-microseconds * 10)
                start = time.perf_counter_ns()
                if not kernel.SetWaitableTimer(timer,ctypes.byref(due),0,None,None,False):
                    raise ctypes.WinError(ctypes.get_last_error())
                if kernel.WaitForSingleObject(timer,5000) != 0:
                    raise ValueError("Timer wait did not complete within five seconds")
                samples.append((time.perf_counter_ns()-start)/1000)
        finally:
            kernel.CloseHandle(timer)
        results.append(dict(mode=name,create_flags=flags,requested_us=microseconds,iterations=iterations,
            minimum_us=min(samples),median_us=statistics.median(samples),maximum_us=max(samples),
            elapsed_us=samples))
    return dict(schema_version=1,status="measured",host=platform.platform(),python=platform.python_version(),
        modes=results,global_timer_resolution_changed=False,guest_execution_tested=False,
        game_performance_measured=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations",type=int,default=60)
    parser.add_argument("--microseconds",type=int,default=5333)
    args = parser.parse_args()
    if not 1 <= args.iterations <= 200 or not 100 <= args.microseconds <= 50000:
        parser.error("Require 1..200 iterations and 100..50000 microseconds")
    try:
        print(json.dumps(measure(args.iterations,args.microseconds),indent=2))
        return 0
    except (OSError,ValueError) as error:
        print(json.dumps(dict(schema_version=1,status="failed",error=str(error))))
        return 1


if __name__ == "__main__":
    sys.exit(main())
