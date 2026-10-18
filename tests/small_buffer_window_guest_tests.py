# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Opt-in actual 256-frame audio with the owned SDL window minimized.

The worker wraps only window transport; the archived runner, guest, hash
contracts and PCM oracle remain unchanged. Never controls foreign windows.
"""
import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def worker():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runner-root",type=Path,required=True)
    args,remaining = parser.parse_known_args(sys.argv[2:])
    root = args.runner_root.resolve(strict=True)
    sys.path.insert(0,str(root/"tools"))
    import window_shutdown
    import videoout_capture
    import run_homebrew_startup as startup
    original = window_shutdown.WindowClose.poll
    observation = dict(requested=False,minimized_observed=False,
                       scope="owned supervisor engine SDL window only")

    def poll(self,ready,supervisor_pid,engine):
        # SDL may show/restore its window during initialization. Minimize only
        # after real guest entry, during the fixture's initial silence phase.
        entry = next((e for e in startup.read_events(output/"session/startup-audit.jsonl")
                      if e.get("event")=="guest_entry"),None)
        if self.request is not None or entry is None:
            return original(self,ready,supervisor_pid,engine)
        if not observation["requested"]:
            try:
                user,window,pid = videoout_capture._owned_window(supervisor_pid,engine)
            except ValueError:
                pass  # Startup may not have created the owned window yet.
            else:
                show = user.ShowWindowAsync
                show.argtypes,show.restype = (wintypes.HWND,ctypes.c_int),wintypes.BOOL
                if not show(window,6):  # SW_MINIMIZE, without foreground/key injection.
                    raise ctypes.WinError(ctypes.get_last_error())
                observation.update(requested=True,root_pid=pid,guest_entry_elapsed_us=entry["elapsed_us"])
        elif not observation["minimized_observed"]:
            user,window,pid = videoout_capture._owned_window(supervisor_pid,engine)
            iconic = user.IsIconic
            iconic.argtypes,iconic.restype = (wintypes.HWND,),wintypes.BOOL
            observation["minimized_observed"] = bool(iconic(window))
        return original(self,ready,supervisor_pid,engine)

    window_shutdown.WindowClose.poll = poll
    sys.argv = [str(root/"tools/run_audio_research.py"),*remaining]
    output = Path(remaining[remaining.index("--output")+1])
    try:
        runpy.run_path(sys.argv[0],run_name="__main__")
    finally:
        if output.exists():
            (output/"minimized-diagnostic.json").write_text(json.dumps(observation,indent=2)+"\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("engine","engine-report","baseline-engine","baseline-report","baseline-harness",
                 "supervisor","fixture","output"):
        parser.add_argument("--"+name,type=Path,required=True)
    args = parser.parse_args()
    output = args.output.resolve(); output.mkdir(parents=True,exist_ok=False)
    sys.path.insert(0,str(ROOT/"tools"))
    import audio_evidence
    import run_homebrew_startup as startup
    before,cases = dict(os.environ),[]
    for index in range(3):
        for mode in ("baseline","patched"):
            baseline = mode=="baseline"
            directory = output/(mode+"-"+str(index))
            engine = args.baseline_engine if baseline else args.engine
            report = args.baseline_report if baseline else args.engine_report
            runner_root = args.baseline_harness.resolve().parents[1] if baseline else ROOT
            command = [sys.executable,str(Path(__file__).resolve()),"worker","--runner-root",str(runner_root)]
            for name,path in dict(engine=engine,engine_report=report,supervisor=args.supervisor,
                                  fixture=args.fixture,output=directory).items():
                command.extend(["--"+name.replace("_","-"),str(path.resolve())])
            process = subprocess.run([*command,"--shutdown","window-close"],capture_output=True,timeout=65,
                env=dict(os.environ,SDL_TIMER_RESOLUTION="0"),**startup.background_process_options())
            (output/(directory.name+"-console.txt")).write_bytes(process.stdout+process.stderr)
            result = json.loads((directory/"audio-result.json").read_text())
            window = json.loads((directory/"minimized-diagnostic.json").read_text())
            transport = result["transport"]
            if (not result["guest_entry_observed"] or not result.get("guest_completed") or result["audit"]["unresolved"] or
                    not window["minimized_observed"] or window["root_pid"]!=transport["root_pid"] or
                    transport["reason"]!="exited" or transport["exit_code"]!=0 or
                    transport["forced_termination"] or transport["active_before_cleanup"]!=0 or
                    not transport["tree_cleanup"]):
                raise RuntimeError("Missing actual minimized guest/completion/normal-close evidence: "+directory.name)
            if baseline:
                if process.returncode and (process.returncode!=1 or not any(text in result.get("error","") for text in
                        ("required ordered stereo tones","PCM frame count outside the bounded fixture range"))):
                    raise RuntimeError("Baseline failed outside the known signal/timing regression")
            elif process.returncode or not result["audio_sink_verified"] or not result["window_close_verified"]:
                raise RuntimeError("Patched minimized audio failed: "+result.get("error",""))
            pcm = directory/"session/sdl-output.raw"
            samples,checksum = audio_evidence.decode_capture(pcm,(directory/"session/stderr.txt").read_text())
            cases.append(dict(name=directory.name,mode=mode,guest_entry_observed=True,guest_completed=True,
                minimized_window=window,transport=transport,status=result["status"],error=result.get("error"),
                challenge=result["challenge"],audio_sink_verified=result["audio_sink_verified"],
                audio_analysis=result.get("audio_analysis"),pcm_sha256=checksum,pcm_frames=len(samples)//2,
                nonzero_samples=sum(x!=0 for x in samples),result_sha256=startup.digest(directory/"audio-result.json"),
                audit_sha256=result["audit"]["sha256"],window_record_sha256=startup.digest(directory/"minimized-diagnostic.json")))
    if not any(c["mode"]=="baseline" and not c["audio_sink_verified"] for c in cases):
        raise RuntimeError("Minimized baseline did not reproduce the intermittent audio failure; retain observations")
    if dict(os.environ)!=before:
        raise RuntimeError("Parent environment changed")
    summary = dict(schema_version=1,status="passed",guest_execution_tested=True,cases=cases,
        baseline_engine_sha256=startup.digest(args.baseline_engine),engine_sha256=startup.digest(args.engine),
        fixture_sha256=startup.digest(args.fixture),parent_environment_unchanged=True,
        hardware_acoustic_output_tested=False,upstream_redistribution_approved=False)
    (output/"summary.json").write_text(json.dumps(summary,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(summary,indent=2))


if __name__=="__main__":
    worker() if len(sys.argv)>1 and sys.argv[1]=="worker" else main()
