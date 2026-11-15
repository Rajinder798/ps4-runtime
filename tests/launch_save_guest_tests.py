# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Opt-in Windows acceptance: a registered title keeps its save across real launches.

Registers only save-counter in a new state folder under --output, then launches it
three times through the real CLI, each in a separate process. Every launch must show
real guest entry, confirmed cleanup and a committed save. The counter must go
1, 2, 3, and the host checks it on disk in the session and in the store after
each launch. Finally a damaged store must be refused before any engine start.
"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from run_homebrew_startup import digest
import run_save_counter as counter


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("engine", "engine-report", "supervisor", "save-counter", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    (output / "inputs").mkdir()
    fixture = output / "inputs/save_counter.oelf"
    shutil.copyfile(args.save_counter, fixture)
    state = output / "state"

    def call(*arguments, expected=0):
        process = subprocess.run([sys.executable, str(ROOT / "tools/ps4_launch.py"),
            "--state-dir", str(state), *map(str, arguments), "--json"],
            capture_output=True, text=True, timeout=150)
        if process.returncode != expected or process.stderr:
            raise RuntimeError(f"Unexpected CLI result ({process.returncode}): {process.stdout} {process.stderr}")
        return json.loads(process.stdout)

    setup = call("register", "--engine", args.engine, "--engine-report", args.engine_report,
                 "--supervisor", args.supervisor, "--save-counter", fixture)
    if setup["status"] != "registered":
        raise RuntimeError("Registration failed")
    registration_hash = digest(state / "launch-config.json")
    stored = state / "titles" / counter.TITLE_ID / "1000" / counter.DIRECTORY / "counter.bin"
    cases, retained = [], {}
    for expected in (1, 2, 3):
        report = call("launch", counter.PROFILE)
        if (report["status"] != "completed" or report["engine_launch_attempted"] is not True or
                report["guest_entry_observed"] is not True or report["tree_cleanup"] is not True or
                report["saves_committed"] is not True or report["save_previous_count"] != expected - 1 or
                report["save_count"] != expected):
            raise RuntimeError("Launch did not keep the save: " + json.dumps(report))
        session = Path(report["logs_directory"])
        evidence = json.loads((session / "save-result.json").read_text())
        in_session = session / "session/user/home/1000/savedata" / counter.TITLE_ID / counter.DIRECTORY / "counter.bin"
        # Independent of the runner: decode both copies directly from disk.
        if (evidence["passed"] is not True or counter.decode(in_session.read_bytes()) != expected or
                counter.decode(stored.read_bytes()) != expected or in_session.read_bytes() != stored.read_bytes()):
            raise RuntimeError("Counter on disk differs from the expected value")
        for path, value in retained.items():
            if digest(path) != value:
                raise RuntimeError("Previous launch evidence was changed")
        for name in ("save-result.json", "launch-result.json", "session/startup-audit.jsonl"):
            retained[session / name] = digest(session / name)
        cases.append(dict(session_id=report["session_id"], staged_users=report["saves_staged"]["users"],
                          previous_count=expected - 1, count=expected, guest_line=evidence["expected_marker"],
                          transport=evidence["transport"], trace_sha256=digest(session / "session/startup-audit.jsonl"),
                          counter_sha256=digest(stored)))
    titles = sorted(p.name for p in (state / "titles").iterdir() if not p.name.startswith("."))
    if (len({c["session_id"] for c in cases}) != 3 or digest(state / "launch-config.json") != registration_hash or
            titles != [counter.TITLE_ID]):
        raise RuntimeError("Session uniqueness, registration or store contents check failed")

    # A damaged store must be refused before launch and left exactly as found.
    good = stored.read_bytes()
    stored.write_bytes(good[:-1] + bytes([good[-1] ^ 0xFF]))
    damaged = stored.read_bytes()
    refused = call("launch", counter.PROFILE, expected=4)
    if (refused["error"]["code"] != "save_store_failed" or refused["engine_launch_attempted"] is not False or
            stored.read_bytes() != damaged):
        raise RuntimeError("A damaged store was not refused before launch")
    stored.write_bytes(good)
    summary = dict(schema_version=1, status="passed", guest_execution_tested=True, title_id=counter.TITLE_ID,
                   cases=cases, store_titles=titles, damaged_store_refused=refused["error"]["code"],
                   registration_unchanged=True, previous_evidence_unchanged=True,
                   upstream_redistribution_approved=False)
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
