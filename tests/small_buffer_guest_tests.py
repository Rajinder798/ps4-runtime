# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Opt-in old/new engine comparison, repeated 256-frame PCM and all guest regressions."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT / "tools"))
import run_audio_research as audio
import run_homebrew_startup as startup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("engine","engine-report","baseline-engine","baseline-report","baseline-harness","supervisor",
                 "capture-helper","helper","fixture","hello-world","service-roundtrip","videoout-pattern",
                 "pad-videoout","interactive-av","output"):
        parser.add_argument("--"+name,type=Path,required=True)
    args = parser.parse_args()
    output = args.output.resolve(); output.mkdir(parents=True,exist_ok=False)
    before, baseline_cases, cases = dict(os.environ), [], []
    for index in range(2):
        directory = output / ("baseline-"+str(index))
        command = [sys.executable,str(args.baseline_harness.resolve()),"--engine",str(args.baseline_engine.resolve()),
            "--engine-report",str(args.baseline_report.resolve()),"--supervisor",str(args.supervisor.resolve()),
            "--fixture",str(args.fixture.resolve()),"--shutdown","window-close","--output",str(directory)]
        process = subprocess.run(command,capture_output=True,timeout=65,**startup.background_process_options())
        (output / (directory.name+"-console.txt")).write_bytes(process.stdout+process.stderr)
        result = json.loads((directory / "audio-result.json").read_text())
        if (not result["guest_entry_observed"] or not result["guest_completed"] or
                result["audit"]["unresolved"] or not result["transport"]["tree_cleanup"] or
                (process.returncode and "required ordered stereo tones" not in result.get("error",""))):
            raise RuntimeError("Baseline failed outside the known PCM regression")
        baseline_cases.append(dict(name=directory.name,audio_sink_verified=result["audio_sink_verified"],
            guest_entry_observed=True,guest_completed=True,transport=result["transport"],error=result.get("error"),
            challenge=result["challenge"],pcm_sha256=startup.digest(directory/"session/sdl-output.raw"),
            pcm_frames=(directory/"session/sdl-output.raw").stat().st_size//8,
            result_sha256=startup.digest(directory/"audio-result.json"),audit_sha256=result["audit"]["sha256"]))
    for index,audio_case in enumerate(("normal",)*5+("silence","swapped")):
        directory = output / ("patched-"+str(index)); directory.mkdir()
        code,result = audio.run_attempt(engine=args.engine,engine_report=args.engine_report,supervisor=args.supervisor,
            fixture=args.fixture,output=directory,audio_case=audio_case,shutdown="window-close")
        transport = result.get("transport",{})
        if (not result["guest_entry_observed"] or not result.get("guest_completed") or result["audit"]["unresolved"] or
                not transport.get("tree_cleanup") or transport.get("reason")!="exited" or transport.get("exit_code")!=0 or
                transport.get("forced_termination") is not False or transport.get("active_before_cleanup")!=0 or
                result.get("window_close_request",{}).get("root_pid")!=transport.get("root_pid")):
            raise RuntimeError("Missing strict guest completion/normal-close evidence: "+result.get("error",""))
        if audio_case=="normal":
            if code or not result["audio_sink_verified"] or not result["window_close_verified"]:
                raise RuntimeError("Patched small-buffer PCM failed: "+result.get("error",""))
        elif code!=1 or result["audio_sink_verified"] or "required ordered stereo tones" not in result.get("error",""):
            raise RuntimeError("Actual silent/swapped guest PCM was not rejected")
        pcm = directory/"session/sdl-output.raw"
        cases.append(dict(name=directory.name,audio_case=audio_case,expected_outcome_passed=True,
            guest_entry_observed=True,guest_completed=True,audio_sink_verified=result["audio_sink_verified"],
            transport=transport,challenge=result["challenge"],audio_analysis=result.get("audio_analysis"),
            error=result.get("error"),pcm_sha256=startup.digest(pcm),pcm_frames=pcm.stat().st_size//8,
            result_sha256=startup.digest(directory/"audio-result.json"),audit_sha256=result["audit"]["sha256"]))
    summaries = {}
    for script, directory in (("audio_volume_guest_tests.py","regressions"),("av_launch_guest_tests.py","registered-launches")):
        command = [sys.executable,str(ROOT/"tests"/script)]
        inputs = dict(engine=args.engine,engine_report=args.engine_report,supervisor=args.supervisor,
            capture_helper=args.capture_helper,fixture=args.interactive_av,hello_world=args.hello_world,
            service_roundtrip=args.service_roundtrip)
        if script.startswith("audio_volume"):
            inputs.update(videoout_pattern=args.videoout_pattern,pad_videoout=args.pad_videoout,audio_pattern=args.fixture)
        else:
            inputs.update(helper=args.helper)
        for name,path in inputs.items():
            command.extend(["--"+name.replace("_","-"),str(path.resolve())])
        process = subprocess.run([*command,"--output",str(output/directory)],capture_output=True,timeout=600,
                                 **startup.background_process_options())
        (output/(directory+"-console.txt")).write_bytes(process.stdout+process.stderr)
        if process.returncode:
            raise RuntimeError("Guest matrix failed; inspect "+directory+"-console.txt")
        summaries[directory] = json.loads((output/directory/"summary.json").read_text())
    if dict(os.environ)!=before:
        raise RuntimeError("Parent environment changed")
    summary = dict(schema_version=1,status="passed",guest_execution_tested=True,baseline_cases=baseline_cases,cases=cases,
        regression_reproduced_on_old_engine=any(not c["audio_sink_verified"] for c in baseline_cases),
        regressions=summaries,patched_expected_outcomes_passed=44,
        baseline_engine_sha256=startup.digest(args.baseline_engine),engine_sha256=startup.digest(args.engine),
        fixture_sha256=startup.digest(args.fixture),interactive_fixture_sha256=startup.digest(args.interactive_av),
        supervisor_sha256=startup.digest(args.supervisor),capture_helper_sha256=startup.digest(args.capture_helper),
        parent_environment_unchanged=True,hardware_acoustic_output_tested=False,upstream_redistribution_approved=False)
    (output/"summary.json").write_text(json.dumps(summary,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(summary,indent=2))


if __name__=="__main__":
    main()
