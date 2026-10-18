# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Opt-in owned Windows render capture and unchanged six-fixture disk regressions."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import run_homebrew_startup as startup
import run_videoout_research as video


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("engine", "engine-report", "supervisor", "capture-helper", "fixture", "hello-world", "service-roundtrip",
                 "videoout-pattern", "pad-videoout", "audio-pattern", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve(); output.mkdir(parents=True, exist_ok=False)
    common = dict(engine=args.engine, engine_report=args.engine_report, supervisor=args.supervisor,
        fixture=args.fixture, profile=video.AV_PROFILE, shutdown="window-close", audio_backend="wasapi", capture_helper=args.capture_helper)
    before, cases = dict(os.environ), []
    for name, audio_case, input_case in (("first","normal","press-release"), ("second","normal","press-release"),
            ("silent","silence","press-release"), ("swapped","swapped","press-release"), ("input-abort","normal","absent")):
        directory = output / name; directory.mkdir()
        code, result = video.run_attempt(**common, output=directory, audio_case=audio_case, input_case=input_case, timeout=35)
        capture = result.get("process_capture", {})
        if (not result["guest_entry_observed"] or result.get("audit", {}).get("unresolved") != [] or
                not result.get("transport", {}).get("tree_cleanup") or capture.get("helper_exit_confirmed") is not True or
                capture.get("helper_exit_code") != 0 or capture.get("helper_forced_termination") is not False):
            raise RuntimeError("Missing guest/import/engine/helper cleanup evidence: " + result.get("error", "") + str(capture))
        if name in ("first", "second"):
            if code or not all(result[k] for k in ("combined_verified", "input_verified", "audio_sink_verified",
                                                  "windows_render_verified", "window_close_verified")):
                raise RuntimeError("Windows render signal failed: " + result.get("error", ""))
        elif name == "input-abort":
            trace = startup.read_events(directory / "session/startup-audit.jsonl", final=True)
            if (code != 1 or result["combined_verified"] or result["windows_render_verified"] or
                    not any(e.get("text") == "interactive-av: FAIL input timeout" for e in trace)):
                raise RuntimeError("Missing guest input did not fail and clean the render capture")
        elif (code != 1 or result["combined_verified"] or result["windows_render_verified"] or
                not result["input_verified"] or not result["window_close_verified"] or len(result["captures"]) != 3 or
                "required ordered stereo tones" not in result.get("error", "")):
            raise RuntimeError("Silent/swapped Windows-rendered guest output incorrectly passed")
        if (directory / "session/sdl-output.raw").exists():
            raise RuntimeError("Disk sink was used in a Windows render test")
        pcm = directory / "session/wasapi-capture/wasapi-output.raw"
        cases.append(dict(name=name, audio_case=audio_case, input_case=input_case, expected_outcome_passed=True,
            guest_entry_observed=True, guest_completed=result.get("guest_completed",False), combined_verified=result["combined_verified"],
            windows_render_verified=result["windows_render_verified"], input_verified=result["input_verified"],
            window_close_verified=result["window_close_verified"], transport=result["transport"], process_capture=capture,
            audio_challenge=result["audio_challenge"], captures=result["captures"], pad_observations=result.get("pad_observations"),
            audio_analysis=result.get("audio_analysis"), pcm_sha256=startup.digest(pcm), pcm_bytes=pcm.stat().st_size,
            result_sha256=startup.digest(directory / "videoout-result.json"), audit_sha256=result["audit"]["sha256"],
            error=result.get("error")))
    command = [sys.executable, str(ROOT / "tests/interactive_guest_tests.py")]
    for name in ("engine", "engine-report", "supervisor", "fixture", "hello-world", "service-roundtrip",
                 "videoout-pattern", "pad-videoout", "audio-pattern"):
        command.extend(["--" + name, str(getattr(args,name.replace("-","_")))])
    regression = subprocess.run([*command,"--output",str(output / "disk-regressions")],capture_output=True,timeout=240)
    (output / "disk-regressions-console.txt").write_bytes(regression.stdout + regression.stderr)
    if regression.returncode:
        raise RuntimeError("Earlier six-fixture disk acceptance failed; inspect disk-regressions-console.txt")
    disk = json.loads((output / "disk-regressions/summary.json").read_text())
    if disk["status"] != "passed" or dict(os.environ) != before:
        raise RuntimeError("Disk regressions or parent environment isolation failed")
    summary = dict(schema_version=1,status="passed",guest_execution_tested=True,cases=cases,disk_regressions=disk,
        engine_sha256=startup.digest(args.engine),supervisor_sha256=startup.digest(args.supervisor),
        capture_helper_sha256=startup.digest(args.capture_helper),fixture_sha256=startup.digest(args.fixture),
        parent_environment_unchanged=True,hardware_acoustic_output_tested=False,upstream_redistribution_approved=False)
    (output / "summary.json").write_text(json.dumps(summary,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(summary,indent=2))


if __name__ == "__main__":
    main()
