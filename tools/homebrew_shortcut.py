# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Create a local .lnk for the existing launch interface; no Explorer handler."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def properties(home, title, runtime):
    if title not in runtime.PROFILES:
        raise runtime.LaunchError("unsupported_title", "Only reviewed homebrew IDs are supported.")
    pythonw = Path(sys.executable).resolve().with_name("pythonw.exe")
    if not pythonw.is_file():
        raise runtime.LaunchError("shortcut_prerequisite_failed", "A matching pythonw.exe is required for console-free launch.", 4)
    return dict(schema_version=1, target=str(pythonw),
        arguments=subprocess.list2cmdline([str(ROOT / "tools/ps4_desktop.py"), "--state-dir", str(home), "--title", title]),
        working_directory=str(ROOT), description="PS4 Runtime research homebrew: " + title)


def adapter(helper, *arguments, runtime):
    try:
        process = subprocess.run([str(helper), *map(str, arguments)], capture_output=True,
                                 encoding="utf-8", timeout=15, check=True)
        return json.loads(process.stdout)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise runtime.LaunchError("shortcut_failed", "Windows could not create or verify the shortcut.", 6) from error


def create(home, title, directory, helper, *, runtime):
    if not runtime.supported_host():
        raise runtime.LaunchError("unsupported_host", "Shortcut creation requires Windows x86-64.", 4)
    runtime.check_inputs(runtime.read_config(home), title)
    expected = properties(home, title, runtime)
    directory = directory.resolve()
    helper = helper.resolve(strict=True)
    path = directory / ("PS4 Runtime - " + title + ".lnk")
    try:
        directory.mkdir(parents=True, exist_ok=True)
        if path.exists() or path.is_symlink():
            raise runtime.LaunchError("shortcut_exists", "The destination already exists; choose another directory or remove it explicitly.")
        # Build and inspect a temporary link before publishing it without an
        # overwrite. Hard-link publication also refuses a concurrent creator.
        with tempfile.TemporaryDirectory(prefix=".ps4-shortcut-", dir=directory) as temporary:
            staged = Path(temporary) / "launch.lnk"
            adapter(helper, "create", staged, expected["target"], expected["arguments"],
                    expected["working_directory"], expected["description"], runtime=runtime)
            if adapter(helper, "inspect", staged, runtime=runtime) != expected:
                raise runtime.LaunchError("shortcut_failed", "Stored shortcut properties differ from the intended launch command.", 6)
            os.link(staged, path)
        return dict(schema_version=1, operation="shortcut", status="created", title=title,
                    shortcut=str(path), engine_launch_attempted=False)
    except FileExistsError as error:
        raise runtime.LaunchError("shortcut_exists", "The destination already exists; it was not overwritten.") from error
    except runtime.LaunchError:
        raise
    except OSError as error:
        raise runtime.LaunchError("shortcut_failed", "Could not publish the shortcut in the selected directory.", 6) from error
