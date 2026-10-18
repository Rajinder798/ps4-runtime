# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Opt-in combined guest graphics/input/PCM/close acceptance and regressions."""
import argparse
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import run_audio_research as audio
import run_homebrew_startup as startup
import run_videoout_research as video


def pcm_record(path):
    # After forced termination Windows may briefly retain a file share lock.
    # Retry only postmortem metadata collection; never relax signal acceptance.
    deadline = time.monotonic() + 2
    while True:
        try:
            return dict(pcm_sha256=startup.digest(path), pcm_bytes=path.stat().st_size)
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.02)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("engine", "engine-report", "supervisor", "fixture", "hello-world", "service-roundtrip",
                 "videoout-pattern", "pad-videoout", "audio-pattern", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve(); output.mkdir(parents=True, exist_ok=False)
    common = dict(engine=args.engine, engine_report=args.engine_report, supervisor=args.supervisor)
    before, cases = dict(os.environ), []
    for name, input_case, audio_case in (("first", "press-release", "normal"), ("second", "press-release", "normal"),
            ("absent-input", "absent", "normal"), ("wrong-button", "wrong-button", "normal"),
            ("silent", "press-release", "silence"), ("swapped", "press-release", "swapped")):
        directory = output / name; directory.mkdir()
        code, result = video.run_attempt(**common, fixture=args.fixture, output=directory, profile=video.AV_PROFILE,
            input_case=input_case, audio_case=audio_case, shutdown="window-close", timeout=35)
        if (not result["guest_entry_observed"] or result.get("audit", {}).get("unresolved") != [] or
                not result.get("transport", {}).get("tree_cleanup")):
            raise RuntimeError("Missing real strict guest entry/import/cleanup evidence: " + result.get("error", ""))
        if name in ("first", "second"):
            if code or not all(result[k] for k in ("combined_verified", "graphics_verified", "input_verified",
                                                  "audio_sink_verified", "window_close_verified")):
                raise RuntimeError("Combined guest failed: " + result.get("error", ""))
        elif input_case != "press-release":
            trace = startup.read_events(directory / "session/startup-audit.jsonl", final=True)
            if (code != 1 or result["combined_verified"] or result["window_close_verified"] or
                    not any(e.get("text") == "interactive-av: FAIL input timeout" for e in trace) or
                    "input timeout" not in result.get("error", "")):
                raise RuntimeError("Missing/wrong guest Cross input was not rejected")
        elif (code != 1 or result["combined_verified"] or result["audio_sink_verified"] or
                not result["input_verified"] or not result["window_close_verified"] or len(result["captures"]) != 3 or
                "required ordered stereo tones" not in result.get("error", "")):
            raise RuntimeError("Invalid actual guest PCM was not rejected after other behavior completed")
        pcm = directory / "session/sdl-output.raw"
        cases.append(dict(name=name, input_case=input_case, audio_case=audio_case, expected_outcome_passed=True,
            guest_entry_observed=result["guest_entry_observed"], guest_completed=result.get("guest_completed", False),
            combined_verified=result["combined_verified"], input_verified=result["input_verified"],
            audio_sink_verified=result["audio_sink_verified"], window_close_verified=result["window_close_verified"],
            transport=result["transport"], palette=result["palette"], audio_challenge=result["audio_challenge"],
            captures=result["captures"], pad_observations=result.get("pad_observations"), input_events=result["input_events"],
            audio_analysis=result.get("audio_analysis"), audit_sha256=result["audit"]["sha256"],
            result_sha256=startup.digest(directory / "videoout-result.json"),
            **pcm_record(pcm), error=result.get("error")))
    regressions = []
    for profile in ("hello-world", "service-roundtrip", "videoout-pattern", "pad-videoout", "audio-pattern"):
        directory = output / profile; directory.mkdir()
        fixture = getattr(args, profile.replace("-", "_"))
        if profile == "audio-pattern":
            code, result = audio.run_attempt(**common, fixture=fixture, output=directory, shutdown="window-close")
            passed = result["audio_sink_verified"] and result["window_close_verified"]
        elif profile in ("videoout-pattern", "pad-videoout"):
            code, result = video.run_attempt(**common, fixture=fixture, output=directory, profile=profile,
                shutdown="window-close" if profile == "pad-videoout" else "terminate")
            passed = result["graphics_verified"] and (profile != "pad-videoout" or
                        (result["input_verified"] and result["window_close_verified"]))
        else:
            code, result = startup.run_attempt(**common, fixture=fixture, output=directory, profile=profile, log_level="info")
            passed = result["g2_passed"]
        if code or not passed or not result["transport"]["tree_cleanup"]:
            raise RuntimeError("Earlier guest regression failed: " + profile + ": " + result.get("error", ""))
        if profile != "audio-pattern" and (directory / "session/sdl-output.raw").exists():
            raise RuntimeError("Audio sink environment leaked into an earlier fixture")
        regressions.append(dict(profile=profile, passed=True, transport=result["transport"],
            captures=result.get("captures"), pad_observations=result.get("pad_observations"),
            audio_analysis=result.get("audio_analysis"), service_roundtrip=result.get("service_roundtrip"),
            marker_interval_us=result.get("marker_interval_us")))
    if dict(os.environ) != before:
        raise RuntimeError("Research settings changed the parent environment")
    summary = dict(schema_version=1, status="passed", guest_execution_tested=True, cases=cases, regressions=regressions,
        engine_sha256=startup.digest(args.engine), supervisor_sha256=startup.digest(args.supervisor),
        fixture_sha256=startup.digest(args.fixture), hardware_playback_tested=False,
        parent_environment_unchanged=True, upstream_redistribution_approved=False)
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
