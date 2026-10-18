# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Opt-in keyboard-to-ScePad guest observations, Vulkan effects and regressions."""
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
    for name in ("engine", "engine-report", "supervisor", "fixture", "videoout-pattern", "hello-world", "service-roundtrip", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    common = dict(engine=args.engine, engine_report=args.engine_report, supervisor=args.supervisor)
    cases = []
    for name, input_case in (("first", "press-release"), ("second", "press-release"), ("absent", "absent"), ("wrong-button", "wrong-button")):
        directory = output / name
        directory.mkdir()
        code, result = video.run_attempt(**common, fixture=args.fixture, output=directory,
                                        profile=video.PAD_PROFILE, input_case=input_case)
        if not result.get("guest_entry_observed") or not result.get("transport", {}).get("tree_cleanup"):
            raise RuntimeError("Missing guest entry/cleanup: " + result.get("error", ""))
        if result["audit"]["unresolved"]:
            raise RuntimeError("Unresolved guest import")
        trace = startup.read_events(directory / "session/startup-audit.jsonl", final=True)
        texts = [e.get("text") for e in trace]
        if input_case == "press-release":
            if code or not result["input_verified"] or not result["graphics_verified"] or len(result["captures"]) != 3:
                raise RuntimeError("Guest input success failed: " + result.get("error", ""))
            images = [c["rgba_sha256"] for c in result["captures"]]
            if images[0] != images[2] or images[0] == images[1]:
                raise RuntimeError("Press/release did not change/restore actual pixels")
        else:
            expected_buttons = 0 if input_case == "absent" else 0x2000
            if (code != 1 or result["input_verified"] or result["graphics_verified"] or len(result["captures"]) != 1 or
                    "pad-videoout: FAIL input timeout" not in texts or
                    f"pad-videoout: waiting state=1 buttons={expected_buttons}" not in texts or
                    (directory / "session/user/data/input-result.bin").exists()):
                raise RuntimeError("Input negative case did not fail for expected observed button state")
        if any(e["root_pid"] != result["transport"]["root_pid"] for e in result["input_events"] + result["screenshot_requests"]):
            raise RuntimeError("Transport did not target the owned engine")
        cases.append(dict(name=name, input_case=input_case, input_verified=result["input_verified"],
            graphics_verified=result["graphics_verified"], guest_entry_observed=True, tree_cleanup=True,
            palette=result["palette"], captures=result["captures"], observations=result.get("pad_observations"),
            input_events=[{k:v for k,v in e.items() if k != "root_pid"} for e in result["input_events"]],
            input_config_sha256=result.get("input_config_sha256"), audit_sha256=result["audit"]["sha256"],
            observed_error=result.get("error")))
    regressions = []
    for profile in ("videoout-pattern", "hello-world", "service-roundtrip"):
        directory = output / profile
        directory.mkdir()
        fixture = getattr(args, profile.replace("-", "_"))
        if profile == "videoout-pattern":
            code, result = video.run_attempt(**common, fixture=fixture, output=directory)
            passed = result["graphics_verified"]
        else:
            code, result = startup.run_attempt(**common, fixture=fixture, output=directory, profile=profile, log_level="info")
            passed = result["g2_passed"]
        if code or not passed or not result["transport"]["tree_cleanup"]:
            raise RuntimeError("Earlier fixture regression failed: " + profile)
        regressions.append(dict(profile=profile, passed=True, tree_cleanup=True,
            captures=result.get("captures"), marker_interval_us=result.get("marker_interval_us"),
            service_roundtrip=result.get("service_roundtrip")))
    summary = dict(schema_version=1, status="passed", guest_execution_tested=True, cases=cases,
                   regressions=regressions, physical_controller_tested=False, upstream_redistribution_approved=False)
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
