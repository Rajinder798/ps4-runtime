# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Opt-in actual combined-fixture gain/mute and complete Windows/disk regression matrix."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import audio_evidence as audio
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
                  fixture=args.fixture, profile=video.AV_PROFILE, shutdown="window-close")
    before, cases = dict(os.environ), []
    for backend in ("disk", "wasapi"):
        for name, percent, audio_case in (("full", 100, "normal"), ("half", 50, "normal"),
                ("mute", 0, "normal"), ("restored", 100, "normal"),
                ("silent-negative", 50, "silence"), ("swapped-negative", 50, "swapped")):
            directory = output / (backend + "-" + name); directory.mkdir()
            code, result = video.run_attempt(**common, output=directory, audio_backend=backend,
                capture_helper=args.capture_helper if backend == "wasapi" else None,
                volume_percent=percent, audio_case=audio_case, timeout=35)
            if (not result["guest_entry_observed"] or result.get("audit", {}).get("unresolved") != [] or
                    not result.get("transport", {}).get("tree_cleanup") or not result.get("input_verified") or
                    not result["window_close_verified"] or len(result["captures"]) != 3):
                raise RuntimeError("Missing guest/input/images/close evidence: " + result.get("error", ""))
            if audio_case == "normal":
                if code or not all(result[k] for k in ("combined_verified", "audio_sink_verified", "volume_verified")):
                    raise RuntimeError("Actual volume failed: " + result.get("error", ""))
                if backend == "wasapi" and not result["windows_render_verified"]:
                    raise RuntimeError("Missing Windows-render PCM evidence")
            elif (code != 1 or result["combined_verified"] or result["volume_verified"] or
                    "required ordered stereo tones" not in result.get("error", "")):
                raise RuntimeError("Silent/swapped PCM incorrectly passed half-volume acceptance")
            work = directory / "session"
            config = work / "user/config.json"
            if json.loads(config.read_text())["General"]["volume_slider"] != percent:
                raise RuntimeError("Engine did not retain the requested volume configuration")
            if backend == "wasapi":
                capture = result["process_capture"]
                if (not capture["helper_exit_confirmed"] or capture["helper_exit_code"] != 0 or
                        capture["helper_forced_termination"] or (work / "sdl-output.raw").exists()):
                    raise RuntimeError("Capture cleanup or backend isolation failed")
                pcm = work / "wasapi-capture/wasapi-output.raw"
            else:
                pcm = work / "sdl-output.raw"
            if audio_case == "normal":
                # Actual captured output must also reject the opposite requested
                # gain (including mute), without another engine launch.
                samples, checksum = audio.decode_pcm(pcm)
                try:
                    audio.analyze_volume(samples, result["audio_challenge"], 50 if percent != 50 else 100)
                except ValueError:
                    pass
                else:
                    raise RuntimeError("Actual PCM passed the wrong volume oracle")
            cases.append(dict(name=directory.name, volume_percent=percent, expected_outcome_passed=True,
                guest_entry_observed=True, guest_completed=result["guest_completed"],
                audio_challenge=result["audio_challenge"], audio_analysis=result.get("audio_analysis"),
                combined_verified=result["combined_verified"], volume_verified=result["volume_verified"],
                input_verified=result["input_verified"], windows_render_verified=result["windows_render_verified"],
                window_close_verified=result["window_close_verified"], transport=result["transport"],
                process_capture=result.get("process_capture"), captures=result["captures"],
                pad_observations=result["pad_observations"], initial_config_sha256=result["initial_config_sha256"],
                final_config_sha256=startup.digest(config), audit_sha256=result["audit"]["sha256"],
                result_sha256=startup.digest(directory / "videoout-result.json"), pcm_sha256=startup.digest(pcm),
                pcm_bytes=pcm.stat().st_size, error=result.get("error")))
    command = [sys.executable, str(ROOT / "tests/windows_audio_guest_tests.py")]
    for name in ("engine", "engine-report", "supervisor", "capture-helper", "fixture", "hello-world", "service-roundtrip",
                 "videoout-pattern", "pad-videoout", "audio-pattern"):
        command.extend(["--" + name, str(getattr(args, name.replace("-", "_")))])
    regression = subprocess.run([*command, "--output", str(output / "regressions")], capture_output=True, timeout=300)
    (output / "regressions-console.txt").write_bytes(regression.stdout + regression.stderr)
    if regression.returncode:
        raise RuntimeError("Earlier Windows/disk regressions failed; inspect regressions-console.txt")
    regressions = json.loads((output / "regressions/summary.json").read_text())
    if regressions["status"] != "passed" or dict(os.environ) != before:
        raise RuntimeError("Regression or parent-environment isolation failed")
    summary = dict(schema_version=1, status="passed", guest_execution_tested=True, cases=cases, regressions=regressions,
        engine_sha256=startup.digest(args.engine), supervisor_sha256=startup.digest(args.supervisor),
        capture_helper_sha256=startup.digest(args.capture_helper), fixture_sha256=startup.digest(args.fixture),
        parent_environment_unchanged=True, hardware_acoustic_output_tested=False, upstream_redistribution_approved=False)
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
