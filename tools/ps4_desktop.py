# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Console-free shortcut entry point; errors are visible, successful runs have no prompt."""
import argparse
import ctypes
import json
from pathlib import Path
import uuid

import ps4_launch as launcher


def show_error(message):
    # Only this launched application displays an error, never an Explorer handler.
    dialog = ctypes.windll.user32.MessageBoxW
    dialog.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint]
    dialog.restype = ctypes.c_int
    dialog(None, message, "PS4 Runtime launch failed", 0x10)


def run(home, title):
    try:
        code, response = launcher.launch(home, title)
    except Exception:
        code, response = 6, dict(schema_version=1, operation="launch", title=title, status="failed",
                                session_id=None, logs_directory=None, engine_launch_attempted=None,
                                guest_entry_observed=None, guest_execution_tested=None, tree_cleanup=None,
                                upstream_redistribution_approved=False,
                                error=dict(code="session_failed", message="Unexpected launch failure; verify the local runtime installation."))
    try:
        results = home / "desktop-results"
        results.mkdir(parents=True, exist_ok=True)
        path = results / (uuid.uuid4().hex + ".json")
        with path.open("x", encoding="utf-8") as stream:
            json.dump(response, stream, indent=2)
            stream.write("\n")
    except OSError:
        code = 6
        response.update(status="failed", error=dict(code="session_failed", message="Could not persist the desktop launch result."))
    if code:
        message = response["error"]["message"]
        if response.get("logs_directory"):
            message += "\n\nSession logs: " + response["logs_directory"]
        show_error(message)
    return code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--title", choices=launcher.PROFILES, required=True)
    args = parser.parse_args()
    return run(args.state_dir.resolve(), args.title)


if __name__ == "__main__":
    raise SystemExit(main())
