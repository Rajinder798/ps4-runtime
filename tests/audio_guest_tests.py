# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Opt-in real guest AudioOut/SDL sink cases and four earlier guest regressions."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import run_audio_research as audio
import run_homebrew_startup as startup
import run_videoout_research as video


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("engine","engine-report","supervisor","fixture","hello-world","service-roundtrip","videoout-pattern","pad-videoout","output"):
        parser.add_argument("--"+name,type=Path,required=True)
    args = parser.parse_args()
    output = args.output.resolve(); output.mkdir(parents=True,exist_ok=False)
    common = dict(engine=args.engine,engine_report=args.engine_report,supervisor=args.supervisor)
    before, cases = dict(os.environ), []
    for name,audio_case in (("first","normal"),("second","normal"),("silence","silence"),("swapped","swapped")):
        directory = output / name; directory.mkdir()
        code,result = audio.run_attempt(**common,fixture=args.fixture,output=directory,audio_case=audio_case)
        if (not result["guest_entry_observed"] or not result.get("guest_completed") or
                not result.get("transport",{}).get("tree_cleanup") or result["audit"]["unresolved"]):
            raise RuntimeError("Missing real guest completion/import/cleanup evidence: "+result.get("error",""))
        if audio_case == "normal":
            if code or not result["audio_sink_verified"]:
                raise RuntimeError("Guest audio failed: "+result.get("error",""))
        elif code != 1 or result["audio_sink_verified"] or "required ordered stereo tones" not in result.get("error",""):
            raise RuntimeError("Actual silent/swapped guest output was not rejected")
        pcm = directory / "session/sdl-output.raw"
        cases.append(dict(name=name,audio_case=audio_case,audio_sink_verified=result["audio_sink_verified"],
            hardware_playback_tested=False,guest_entry_observed=True,guest_completed=True,tree_cleanup=True,
            challenge=result["challenge"],audio_analysis=result.get("audio_analysis"),pcm_sha256=startup.digest(pcm),
            pcm_bytes=pcm.stat().st_size,audit_sha256=result["audit"]["sha256"],observed_error=result.get("error")))
    if dict(os.environ) != before:
        raise RuntimeError("Audio sink settings leaked into the parent environment")
    regressions = []
    for profile in ("hello-world","service-roundtrip","videoout-pattern","pad-videoout"):
        directory = output / profile; directory.mkdir()
        fixture = getattr(args,profile.replace("-","_"))
        if profile in ("videoout-pattern","pad-videoout"):
            code,result = video.run_attempt(**common,fixture=fixture,output=directory,profile=profile)
            passed = result["graphics_verified"] and (profile != "pad-videoout" or result["input_verified"])
        else:
            code,result = startup.run_attempt(**common,fixture=fixture,output=directory,profile=profile,log_level="info")
            passed = result["g2_passed"]
        if code or not passed or not result["transport"]["tree_cleanup"]:
            raise RuntimeError("Earlier guest regression failed: "+profile)
        if (directory / "session/sdl-output.raw").exists():
            raise RuntimeError("Research disk sink leaked into an earlier fixture")
        regressions.append(dict(profile=profile,passed=True,tree_cleanup=True,
            captures=result.get("captures"),observations=result.get("pad_observations"),
            marker_interval_us=result.get("marker_interval_us"),service_roundtrip=result.get("service_roundtrip")))
    summary = dict(schema_version=1,status="passed",guest_execution_tested=True,cases=cases,regressions=regressions,
                   hardware_playback_tested=False,parent_environment_unchanged=True,upstream_redistribution_approved=False)
    (output / "summary.json").write_text(json.dumps(summary,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(summary,indent=2))


if __name__ == "__main__":
    main()
