#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Opt-in real Windows guest tests for the save fixture; needs the verified engine, build and GPU.

Fault injection only changes staged host files: the challenge input, or a save
directory that already exists before the guest runs. Guest code, import checks,
engine build verification and process containment use the save runner unchanged.
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
import psf
import run_save_roundtrip as runner

# Case name -> expected guest failure prefix (None: the run must pass).
CASES = {"valid-1": None, "valid-2": None, "missing-input": "save-roundtrip: FAIL open challenge",
         "short-input": "save-roundtrip: FAIL read challenge",
         "existing-save": "save-roundtrip: FAIL create mount"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("engine", "engine-report", "fixture", "supervisor", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    original_prepare = runner.prepare
    results = []
    for case, failure in CASES.items():
        def prepare(work, fixture):
            staged, challenge = original_prepare(work, fixture)
            input_path = staged.parent / "challenge.bin"
            if case == "missing-input":
                input_path.unlink()
            elif case == "short-input":
                input_path.write_bytes(challenge[:128])
            elif case == "existing-save":
                # The engine treats a directory with sce_sys/param.sfo as existing save data.
                for home in (work / "user/home").iterdir():
                    sce_sys = home / "savedata" / runner.TITLE_ID / runner.DIRECTORY / "sce_sys"
                    sce_sys.mkdir(parents=True)
                    (sce_sys / "param.sfo").write_bytes(psf.write({
                        "TITLE_ID": runner.TITLE_ID, "SAVEDATA_DIRECTORY": runner.DIRECTORY}))
            return staged, challenge

        output = args.output / case
        arguments = ["run_save_roundtrip.py", "--output", str(output)]
        for name in ("engine", "engine_report", "fixture", "supervisor"):
            arguments += ["--" + name.replace("_", "-"), str(getattr(args, name))]
        with patch.object(sys, "argv", arguments), patch.object(runner, "prepare", prepare):
            with contextlib.redirect_stdout(io.StringIO()):
                code = runner.main()
        report = json.loads((output / "save-result.json").read_text())
        expected_pass = failure is None
        if code != (0 if expected_pass else 1) or report["passed"] is not expected_pass:
            raise RuntimeError(f"Unexpected result for {case}; see {output}")
        if report.get("guest_entry_observed") is not True or report.get("transport", {}).get("tree_cleanup") is not True:
            raise RuntimeError(f"Guest entry/cleanup missing for {case}; see {output}")
        trace = output / "session/startup-audit.jsonl"
        events = runner.startup.read_events(trace, final=True)
        texts = [e.get("text", "") for e in events if e.get("event") == "guest_output"]
        if not expected_pass:
            if not any(text.startswith(failure) for text in texts):
                raise RuntimeError(f"Expected guest failure missing for {case}")
            if runner.MARKERS[1] in texts:
                raise RuntimeError(f"Unexpected completion marker for {case}")
        results.append(dict(case=case, expected_pass=expected_pass, guest_entry_observed=True,
                            tree_cleanup=True, trace_sha256=runner.startup.digest(trace),
                            guest_failure=next((t for t in texts if t.startswith("save-roundtrip: FAIL")), None),
                            save_roundtrip=report.get("save_roundtrip")))
    if results[0]["save_roundtrip"]["challenge_sha256"] == results[1]["save_roundtrip"]["challenge_sha256"]:
        raise RuntimeError("Repeated challenge input")
    summary = dict(schema_version=1, status="passed", guest_execution_tested=True, cases=results,
                   upstream_redistribution_approved=False)
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
