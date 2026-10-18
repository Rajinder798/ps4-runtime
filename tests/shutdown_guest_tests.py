# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Opt-in actual guest behavior followed by owned-window engine shutdown.

The absent-close negative suppresses the host request, not guest services/output.
This is separate from the ordinary Win32 ignored-close and orphan tests.
"""
import argparse
import json
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import run_audio_research as audio
import run_homebrew_startup as startup
import run_videoout_research as video
import window_shutdown


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("engine", "engine-report", "supervisor", "pad-videoout", "audio-pattern", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve(); output.mkdir(parents=True, exist_ok=False)
    common = dict(engine=args.engine, engine_report=args.engine_report, supervisor=args.supervisor, shutdown="window-close")
    cases = []
    for profile in ("pad-videoout", "audio-pattern"):
        for case in ("first", "second", "absent-close"):
            directory = output / (profile + "-" + case); directory.mkdir()
            def run():
                if profile == "pad-videoout":
                    return video.run_attempt(**common, fixture=args.pad_videoout, output=directory,
                                             profile=profile, timeout=12)
                return audio.run_attempt(**common, fixture=args.audio_pattern, output=directory, timeout=12)
            if case == "absent-close":
                # Actual guest still completes; host deliberately sends no close.
                with patch.object(window_shutdown.WindowClose, "poll", return_value=False):
                    code, result = run()
            else:
                code, result = run()
            transport = result.get("transport", {})
            trace = directory / "session/startup-audit.jsonl"
            evidence = startup.evaluate(startup.read_events(trace, final=True), profile)
            if not evidence["guest_entry_observed"] or not evidence["markers_observed"] or not transport.get("tree_cleanup"):
                raise RuntimeError("Guest completion/cleanup missing: " + result.get("error", ""))
            if case == "absent-close":
                if (code != 1 or result["window_close_verified"] or transport.get("reason") != "timeout" or
                        transport.get("forced_termination") is not True or result.get("window_close_request")):
                    raise RuntimeError("Absent host close request was not rejected")
                # Independently check completed output even though the runner
                # correctly rejected the lifecycle before granting overall pass.
                if profile == "audio-pattern":
                    from audio_evidence import verify
                    verify(directory / "session/sdl-output.raw",
                           (directory / "session/stderr.txt").read_text(), result["challenge"])
                else:
                    video.verify_pad_observations(directory / "session/user/data/input-result.bin")
                    if len(result["captures"]) != 3:
                        raise RuntimeError("Absent-close graphics/input sequence missing")
            else:
                if code or not result["window_close_verified"]:
                    raise RuntimeError("Normal window close failed: " + result.get("error", ""))
                if profile == "pad-videoout" and not (result["graphics_verified"] and result["input_verified"]):
                    raise RuntimeError("Graphics/input evidence missing")
                if profile == "audio-pattern" and not result["audio_sink_verified"]:
                    raise RuntimeError("PCM sink evidence missing")
                if (directory / "session/stop.request").exists():
                    raise RuntimeError("Normal close incorrectly requested forced stop")
            cases.append(dict(profile=profile, case=case, expected_outcome_passed=True,
                guest_entry_observed=True, guest_completed=True, window_close_verified=result["window_close_verified"],
                transport=transport, window_close_request=result.get("window_close_request"),
                captures=result.get("captures"), pad_observations=result.get("pad_observations"),
                audio_analysis=result.get("audio_analysis"), audit_sha256=startup.digest(trace),
                error=result.get("error")))
    summary = dict(schema_version=1, status="passed", guest_execution_tested=True, cases=cases,
        engine_sha256=startup.digest(args.engine), supervisor_sha256=startup.digest(args.supervisor),
        fixture_sha256={p:startup.digest(getattr(args, p.replace("-", "_"))) for p in ("pad-videoout", "audio-pattern")},
        hardware_playback_tested=False, combined_graphics_input_audio_tested=False, upstream_redistribution_approved=False)
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
