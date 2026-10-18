# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Opt-in actual VideoOut runs, guest input failures and two earlier regressions."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import run_homebrew_startup as startup
import run_videoout_research as video


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("engine", "engine-report", "supervisor", "fixture", "hello-world", "service-roundtrip", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    common = dict(engine=args.engine, engine_report=args.engine_report, supervisor=args.supervisor)
    cases = []
    for name, palette_case in (("first", "valid"), ("second", "valid"), ("missing", "missing"), ("truncated", "truncated")):
        directory = output / name
        directory.mkdir()
        code, result = video.run_attempt(**common, fixture=args.fixture, output=directory, palette_case=palette_case)
        expected_error = {"missing": "videoout-pattern: FAIL open palette", "truncated": "videoout-pattern: FAIL read palette"}
        if palette_case == "valid":
            if code or result["status"] != "passed" or result["graphics_verified"] is not True or len(result["captures"]) != 2:
                raise RuntimeError("VideoOut success failed: " + result.get("error", "missing graphics evidence"))
            if result["captures"][0]["rgba_sha256"] == result["captures"][1]["rgba_sha256"]:
                raise RuntimeError("Phase images did not change")
            if any(request["root_pid"] != result["transport"]["root_pid"] for request in result["screenshot_requests"]):
                raise RuntimeError("Screenshot request did not target this owned engine")
        else:
            trace = startup.read_events(directory / "session/startup-audit.jsonl", final=True)
            if (code != 1 or result["graphics_verified"] is not False or result["captures"] or
                    expected_error[palette_case] not in [e.get("text") for e in trace] or
                    result["audit"]["unresolved"]):
                raise RuntimeError("Guest negative case did not fail for its expected palette error")
        if result["guest_entry_observed"] is not True or result["transport"]["tree_cleanup"] is not True:
            raise RuntimeError("Missing actual guest entry or tree cleanup")
        cases.append(dict(name=name, palette_case=palette_case, graphics_verified=result["graphics_verified"],
            guest_entry_observed=True, tree_cleanup=True, palette=result["palette"], captures=result["captures"],
            audit_sha256=result["audit"]["sha256"], unresolved_count=len(result["audit"]["unresolved"]),
            expected_error=expected_error.get(palette_case), observed_error=result.get("error")))
    if cases[0]["palette"] == cases[1]["palette"]:
        raise RuntimeError("Random palettes coincided; rerun with a new output to demonstrate distinct inputs")
    regressions = []
    for profile in ("hello-world", "service-roundtrip"):
        directory = output / profile
        directory.mkdir()
        code, result = startup.run_attempt(**common, fixture=getattr(args, profile.replace("-", "_")),
                                          output=directory, profile=profile, log_level="info")
        if code or result["g2_passed"] is not True or result["transport"]["tree_cleanup"] is not True:
            raise RuntimeError("Earlier fixture regression failed: " + profile)
        regressions.append(dict(profile=profile, g2_passed=True, tree_cleanup=True,
            marker_interval_us=result["marker_interval_us"], service_roundtrip=result.get("service_roundtrip")))
    summary = dict(schema_version=1, status="passed", guest_execution_tested=True, cases=cases,
        regressions=regressions, upstream_redistribution_approved=False)
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
