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
else:
    time.sleep(60)
