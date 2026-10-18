# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Opt-in real Windows Shell activation of generated homebrew shortcuts."""
import argparse
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def activate(link):
    class ShellExecuteInfo(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("fMask", wintypes.ULONG), ("hwnd", wintypes.HWND),
            ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
            ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE),
            ("lpIDList", ctypes.c_void_p), ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
            ("dwHotKey", wintypes.DWORD), ("hIcon", wintypes.HANDLE), ("hProcess", wintypes.HANDLE)]
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    shell.ShellExecuteExW.argtypes = [ctypes.POINTER(ShellExecuteInfo)]
    shell.ShellExecuteExW.restype = wintypes.BOOL
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    # Shell's normal open verb follows the .lnk just as Explorer activation does.
    info = ShellExecuteInfo(cbSize=ctypes.sizeof(ShellExecuteInfo), fMask=0x40 | 0x100 | 0x400,
                            lpVerb="open", lpFile=str(link), nShow=1)
    if not shell.ShellExecuteExW(ctypes.byref(info)) or not info.hProcess:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if kernel.WaitForSingleObject(info.hProcess, 60000) != 0:
            kernel.TerminateProcess(info.hProcess, 97)
            kernel.WaitForSingleObject(info.hProcess, 5000)
            raise RuntimeError("Shortcut process did not complete in its bounded test budget")
        code = wintypes.DWORD()
        if not kernel.GetExitCodeProcess(info.hProcess, ctypes.byref(code)) or code.value:
            raise RuntimeError("Shortcut process exited unsuccessfully")
    finally:
        kernel.CloseHandle(info.hProcess)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("engine", "engine-report", "supervisor", "hello-world", "service-roundtrip", "helper", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("Windows is required")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    state = output / "state"
    links = output / "shortcuts \u03bb with spaces"
    def call(*arguments, expected=0):
        result = subprocess.run([sys.executable, str(ROOT / "tools/ps4_launch.py"), "--state-dir", str(state),
                                 *map(str, arguments), "--json"], capture_output=True, text=True, timeout=60)
        if result.returncode != expected or result.stderr:
            raise RuntimeError(f"CLI failure: {result.stdout} {result.stderr}")
        return json.loads(result.stdout)
    call("register", "--engine", args.engine, "--engine-report", args.engine_report, "--supervisor", args.supervisor,
         "--hello-world", args.hello_world, "--service-roundtrip", args.service_roundtrip)
    config_before = (state / "launch-config.json").read_bytes()
    shortcut_paths = {}
    for title in ("hello-world", "service-roundtrip"):
        result = call("shortcut", title, "--directory", links, "--helper", args.helper)
        shortcut_paths[title] = Path(result["shortcut"])
        original = shortcut_paths[title].read_bytes()
        duplicate = call("shortcut", title, "--directory", links, "--helper", args.helper, expected=3)
        if duplicate["error"]["code"] != "shortcut_exists" or shortcut_paths[title].read_bytes() != original:
            raise RuntimeError("Existing shortcut was not preserved")
    cases = []
    for title in ("hello-world", "service-roundtrip", "hello-world", "service-roundtrip"):
        before = set((state / "desktop-results").glob("*.json")) if (state / "desktop-results").exists() else set()
        activate(shortcut_paths[title])
        fresh = set((state / "desktop-results").glob("*.json")) - before
        if len(fresh) != 1:
            raise RuntimeError("One fresh desktop result is required per activation")
        result = json.loads(fresh.pop().read_text())
        if (result["status"] != "completed" or result["guest_entry_observed"] is not True or
                result["tree_cleanup"] is not True):
            raise RuntimeError("Missing real guest success/cleanup evidence")
        evidence = json.loads((Path(result["logs_directory"]) / "startup-result.json").read_text())
        if evidence["g2_passed"] is not True:
            raise RuntimeError("Strict guest observation failed")
        cases.append(dict(title=title, session_id=result["session_id"], guest_entry_observed=True,
                          tree_cleanup=True, marker_interval_us=evidence["marker_interval_us"],
                          service_roundtrip=evidence.get("service_roundtrip")))
    if len({case["session_id"] for case in cases}) != 4 or (state / "launch-config.json").read_bytes() != config_before:
        raise RuntimeError("Session uniqueness or unchanged registration failed")
    summary = dict(schema_version=1, status="passed", windows_shell_activation_tested=True,
                   guest_execution_tested=True, cases=cases, registration_unchanged=True,
                   existing_shortcuts_preserved=True, upstream_redistribution_approved=False)
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
