#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Opt-in real Windows guest tests; needs the verified engine, SDK build and GPU.

Fault injection only changes the staged input file. Guest code, import checks,
engine build verification and process containment use the normal runner.
"""
import argparse
import contextlib
import io
import json
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import run_homebrew_startup as runner


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("engine", "engine-report", "fixture", "supervisor", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    original_prepare = runner.prepare_service
    results = []
    for case in ("valid-1", "valid-2", "missing-input", "short-input"):
        def prepare(work, fixture):
            staged, challenge = original_prepare(work, fixture)
            input_path = staged.parent / "challenge.bin"
            if case == "missing-input":
                input_path.unlink()
            elif case == "short-input":
                input_path.write_bytes(challenge[:128])
            return staged, challenge

        output = args.output / case
        arguments = ["run_homebrew_startup.py", "--profile", "service-roundtrip", "--output", str(output)]
        for name in ("engine", "engine_report", "fixture", "supervisor"):
            arguments += ["--" + name.replace("_", "-"), str(getattr(args, name))]
        with patch.object(sys, "argv", arguments), patch.object(runner, "prepare_service", prepare):
            with contextlib.redirect_stdout(io.StringIO()):
                code = runner.main()
        report = json.loads((output / "startup-result.json").read_text())
        expected_pass = case.startswith("valid-")
        if code != (0 if expected_pass else 1) or report["g2_passed"] is not expected_pass:
            raise RuntimeError(f"Unexpected result for {case}; see {output}")
        if report.get("guest_entry_observed") is not True or report.get("transport", {}).get("tree_cleanup") is not True:
            raise RuntimeError(f"Guest entry/cleanup missing for {case}; see {output}")
        trace = output / "session/startup-audit.jsonl"
        events = runner.read_events(trace, final=True)
        if not expected_pass:
            expected = "service-roundtrip: FAIL " + ("open challenge" if case == "missing-input" else "read challenge")
            if not any(e.get("event") == "guest_output" and e.get("text") == expected for e in events):
                raise RuntimeError(f"Expected guest failure missing for {case}")
            if any(e.get("text") == runner.SERVICE_MARKERS[1] for e in events):
                raise RuntimeError(f"Unexpected completion marker for {case}")
        results.append(dict(case=case, expected_pass=expected_pass, guest_entry_observed=True,
                            tree_cleanup=True, trace_sha256=runner.digest(trace),
                            service_roundtrip=report.get("service_roundtrip")))
    if results[0]["service_roundtrip"]["challenge_sha256"] == results[1]["service_roundtrip"]["challenge_sha256"]:
        raise RuntimeError("Repeated challenge input")
    summary = dict(schema_version=1, status="passed", guest_execution_tested=True, cases=results,
                   upstream_redistribution_approved=False)
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
