# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Opt-in Windows launch CLI acceptance with real verified homebrew execution."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from run_homebrew_startup import digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("engine", "engine-report", "supervisor", "hello-world", "service-roundtrip", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    inputs = output / "inputs"
    inputs.mkdir()
    fixtures = {}
    for title in ("hello-world", "service-roundtrip"):
        fixtures[title] = inputs / (title + ".oelf")
        shutil.copyfile(getattr(args, title.replace("-", "_")), fixtures[title])
    state = output / "state"
    def call(*arguments, expected=0):
        process = subprocess.run([sys.executable, str(ROOT / "tools/ps4_launch.py"),
            "--state-dir", str(state), *map(str, arguments), "--json"],
            capture_output=True, text=True, timeout=150)
        if process.returncode != expected or process.stderr:
            raise RuntimeError(f"Unexpected CLI result ({process.returncode}): {process.stdout} {process.stderr}")
        return json.loads(process.stdout)
    setup = call("register", "--engine", args.engine, "--engine-report", args.engine_report,
                 "--supervisor", args.supervisor, "--hello-world", fixtures["hello-world"],
                 "--service-roundtrip", fixtures["service-roundtrip"])
    if setup["status"] != "registered":
        raise RuntimeError("Registration failed")
    registration_hash = digest(state / "launch-config.json")
    cases, retained = [], {}
    for title in ("hello-world", "service-roundtrip", "hello-world", "service-roundtrip"):
        report = call("launch", title)
        if (report["status"] != "completed" or report["engine_launch_attempted"] is not True or
                report["guest_entry_observed"] is not True or report["tree_cleanup"] is not True):
            raise RuntimeError("Missing real guest/cleanup evidence")
        session = Path(report["logs_directory"])
        evidence = json.loads((session / "startup-result.json").read_text())
        if evidence["g2_passed"] is not True:
            raise RuntimeError("Research observation failed")
        for path, expected_hash in retained.items():
            if digest(path) != expected_hash:
                raise RuntimeError("Previous launch evidence was changed")
        for name in ("startup-result.json", "launch-result.json", "session/startup-audit.jsonl"):
            retained[session / name] = digest(session / name)
        cases.append(dict(title=title, session_id=report["session_id"],
                          guest_entry_observed=True, tree_cleanup=True,
                          marker_interval_us=evidence["marker_interval_us"],
                          service_roundtrip=evidence.get("service_roundtrip"),
                          trace_sha256=digest(session / "session/startup-audit.jsonl")))
    if len({c["session_id"] for c in cases}) != 4 or digest(state / "launch-config.json") != registration_hash:
        raise RuntimeError("Session uniqueness/config persistence failed")
    unknown = call("launch", "unsupported-game", expected=3)
    fixtures["hello-world"].write_bytes(fixtures["hello-world"].read_bytes() + b"tamper rejection test")
    tampered = call("launch", "hello-world", expected=4)
    for report, expected_code in ((unknown, "unsupported_title"), (tampered, "input_verification_failed")):
        if report["error"]["code"] != expected_code or report["engine_launch_attempted"] is not False or report["session_id"] is not None:
            raise RuntimeError("Rejected request attempted execution")
    if len(list((state / "sessions").iterdir())) != 4:
        raise RuntimeError("Rejected requests created unexpected sessions")
    summary = dict(schema_version=1, status="passed", guest_execution_tested=True, cases=cases,
                   rejected_requests=[unknown["error"]["code"], tampered["error"]["code"]],
                   registration_unchanged=True, previous_evidence_unchanged=True,
                   upstream_redistribution_approved=False)
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
