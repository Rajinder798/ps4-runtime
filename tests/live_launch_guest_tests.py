# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later

"""Opt-in registered live CLI/Shell/settings checks; only this test host automates input/capture."""
import argparse
import ctypes as c
from ctypes import wintypes as w
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import live_av_evidence as live
import ps4_launch as launcher
import run_homebrew_startup as startup
from process_audio import ProcessCapture
import videoout_capture as windows
from muted_endpoint import MutedEndpoint, validate_report
from live_status import read_status


def qualified_cli():
    """Keep capture a supervisor sibling in this separate test host, never in production."""
    options = json.loads(Path(sys.argv[2]).read_text())
    original = startup.supervise
    def supervise(supervisor, command, work, timeout, on_poll, *, on_started, environment):
        output, owner, capture = work.parent, [], None
        def started(pid):
            owner.append(pid)
            on_started(pid)
        def poll():
            nonlocal capture
            stop = on_poll()
            if (output / "capture.request").exists():
                if capture is None:
                    external = output / "test-qualification"
                    external.mkdir()
                    capture = ProcessCapture(Path(options["capture_helper"]), external, 30)
                if capture.ready(owner[0], Path(options["engine"])):
                    (output / "capture-ready.txt").write_text("ready")
            return stop
        try:
            transport = original(supervisor, command, work, timeout, poll, on_started=started, environment=environment)
            if capture is not None:
                pcm, checksum = capture.decode(transport)
                challenge = list((work / "app/audio.bin").read_bytes()[:4])
                volume = json.loads((work / "user/config.json").read_text())["General"]["volume_slider"]
                analysis = live.analyze_session_volume(pcm, challenge, volume)
                try:
                    live.analyze_session_volume(pcm, challenge, 50 if volume != 50 else 100)
                except ValueError:
                    pass
                else:
                    raise RuntimeError("Actual Windows PCM passed the wrong requested gain")
                (output / "external-audio.json").write_text(json.dumps(dict(analysis=analysis, pcm_sha256=checksum,
                    process_capture=capture.close(), wrong_gain_rejected=True)))
            return transport
        finally:
            if capture is not None:
                capture.close()
    startup.supervise = supervise
    sys.argv = [str(ROOT / "tools/ps4_launch.py"), "--state-dir", options["state"], "launch", "live-av", "--json"]
    return launcher.main()


class ShellChild:
    """Owned handle returned by the same Shell open verb used for a double-click."""
    def __init__(self, link):
        class Info(c.Structure):
            _fields_ = [("cbSize",w.DWORD),("fMask",w.ULONG),("hwnd",w.HWND),("verb",w.LPCWSTR),
                ("file",w.LPCWSTR),("parameters",w.LPCWSTR),("directory",w.LPCWSTR),("show",c.c_int),
                ("instance",w.HINSTANCE),("idlist",c.c_void_p),("kind",w.LPCWSTR),("key",w.HKEY),
                ("hotkey",w.DWORD),("icon",w.HANDLE),("process",w.HANDLE)]
        shell, self.kernel = c.WinDLL("shell32",use_last_error=True), c.WinDLL("kernel32",use_last_error=True)
        shell.ShellExecuteExW.argtypes, shell.ShellExecuteExW.restype = [c.POINTER(Info)], w.BOOL
        self.kernel.WaitForSingleObject.argtypes = [w.HANDLE,w.DWORD]
        self.kernel.WaitForSingleObject.restype = w.DWORD
        self.kernel.GetExitCodeProcess.argtypes = [w.HANDLE,c.POINTER(w.DWORD)]
        self.kernel.TerminateProcess.argtypes = [w.HANDLE,w.UINT]
        self.kernel.CloseHandle.argtypes = [w.HANDLE]
        info = Info(cbSize=c.sizeof(Info), fMask=0x40|0x100|0x400, verb="open", file=str(link), show=1)
        if not shell.ShellExecuteExW(c.byref(info)) or not info.process:
            raise c.WinError(c.get_last_error())
        self.handle = info.process
    def poll(self):
        wait = self.kernel.WaitForSingleObject(self.handle,0)
        if wait == 258:
            return None
        code = w.DWORD()
        if wait != 0 or not self.kernel.GetExitCodeProcess(self.handle,c.byref(code)):
            raise c.WinError(c.get_last_error())
        return code.value
    def wait(self,timeout):
        if self.kernel.WaitForSingleObject(self.handle,round(timeout*1000)) != 0:
            raise subprocess.TimeoutExpired("owned Shell launch",timeout)
        return self.poll()
    def kill(self):
        if not self.kernel.TerminateProcess(self.handle,97):
            raise c.WinError(c.get_last_error())
    def close(self):
        self.kernel.CloseHandle(self.handle)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("engine","engine-report","fixture","supervisor","capture-helper","helper","output"):
        parser.add_argument("--"+name,type=Path,required=True)
    parser.add_argument("--muted-endpoint-observer", type=Path,
                        help="Read-only muted-Windows matrix; replaces PCM-qualified cases with ordinary launches")
    args = parser.parse_args()
    output = args.output.resolve();output.mkdir(parents=True,exist_ok=False)
    if args.muted_endpoint_observer:
        with MutedEndpoint(args.muted_endpoint_observer, output) as observer:
            matrix(args, output, observer)
        summary_path = output / "summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        summary["endpoint_observation"] = validate_report(output / "endpoint.jsonl")
        summary["status"] = "passed"
        summary_path.write_text(json.dumps(summary, indent=2)+"\n", encoding="utf-8")
    else:
        matrix(args, output)


def matrix(args, output, observer=None):
    state, links = output/"state",output/"shortcuts λ with spaces"
    fixture = output/"registered-live.oelf";shutil.copyfile(args.fixture,fixture)
    def call(*arguments,expected=0):
        if observer: observer.check()
        p = subprocess.run([sys.executable,str(ROOT/"tools/ps4_launch.py"),"--state-dir",str(state),
                            *map(str,arguments),"--json"],capture_output=True,text=True,timeout=30)
        if p.returncode != expected or p.stderr:
            raise RuntimeError(p.stdout+p.stderr)
        return json.loads(p.stdout)
    call("register","--engine",args.engine,"--engine-report",args.engine_report,"--supervisor",args.supervisor,"--live-av",fixture)
    config = state/"launch-config.json"; config_hash=startup.digest(config)
    registration = json.loads(config.read_text())
    if registration["schema_version"] != 3 or "capture_helper" in registration:
        raise RuntimeError("Live-only registration incorrectly depends on capture")
    link = Path(call("shortcut","live-av","--directory",links,"--helper",args.helper)["shortcut"])
    link_hash = startup.digest(link)
    cases, retained = [], {}

    def run(name,mode,percent,level,source,long=False):
        if observer:
            observer.check()
            if mode == "qualified-cli":
                mode = "cli"
                name = name.replace("qualified-cli", "muted-cli")
        previous = set((state/"sessions").glob("*"))
        desktop_before = set((state/"desktop-results").glob("*.json"))
        settings_before = (state/"settings.json").read_bytes() if (state/"settings.json").exists() else None
        console = output/(name+"-console.txt")
        with console.open("wb") as log:
            if mode == "shell":
                child = ShellChild(link)
            else:
                command = [sys.executable,str(ROOT/"tools/ps4_launch.py"),"--state-dir",str(state),"launch","live-av","--json"]
                if mode == "qualified-cli":
                    options = output/(name+"-options.json")
                    options.write_text(json.dumps(dict(state=str(state),engine=str(args.engine.resolve()),capture_helper=str(args.capture_helper.resolve()))))
                    command = [sys.executable,str(Path(__file__).resolve()),"qualified-cli",str(options)]
                child = subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,**startup.background_process_options())
            began, ready, session, close = time.monotonic(),None,None,None
            captures, actions, consumed = [],[],set()
            qualified_at = request_at = None
            try:
                while child.poll() is None:
                    if observer: observer.check()
                    now = time.monotonic()
                    if now-began > (165 if long else 40):
                        raise RuntimeError("Registered launch exceeded test budget: "+name)
                    fresh = set((state/"sessions").glob("*"))-previous
                    if len(fresh)>1:
                        raise RuntimeError("Unexpected extra live session")
                    if not fresh:
                        time.sleep(0.02);continue
                    session = next(iter(fresh))
                    try:
                        status = read_status(session/"session-status.json")
                    except (OSError,ValueError):
                        time.sleep(0.02);continue
                    if not status["running_observed"]:
                        time.sleep(0.02);continue
                    ready = ready or now
                    owner = status["supervisor_pid"]
                    if long:
                        if close is None and now-ready>=125:
                            close = windows.request_close(owner,args.engine)
                    else:
                        if mode == "qualified-cli":
                            (session/"capture.request").touch(exist_ok=True)
                            if not (session/"capture-ready.txt").exists():
                                time.sleep(0.02);continue
                        sample = status["samples"][-1];sequence=sample["sequence"]
                        if sequence == len(captures):
                            if request_at is None or now-request_at>=0.4:
                                windows.request_screenshot(owner,args.engine);request_at=now
                            palette=(session/"session/app/palette.bin").read_bytes()
                            for image in sorted(set((session/"session/user/screenshots").glob("*.png"))-consumed):
                                try:
                                    checked=live.verify_image(image,palette,sequence,sample["buttons"])
                                except ValueError:
                                    if image.stat().st_size>4*1024*1024:raise
                                    continue
                                consumed.add(image);captures.append(dict(**checked,path=str(image.relative_to(output))));qualified_at=now
                                break
                        if close is None and sequence==len(captures)-1 and qualified_at is not None and now-qualified_at>=1:
                            if sequence==4:
                                close=windows.request_close(owner,args.engine)
                            elif len(actions)==sequence:
                                actions.append(windows.send_key(owner,args.engine,"cross",sequence%2==0))
                    time.sleep(0.02)
                code=child.wait(timeout=6)
                if code:raise RuntimeError("Registered launch failed: "+name+" "+console.read_text(errors="replace"))
            finally:
                if child.poll() is None:
                    if session is not None:(session/"session/stop.request").touch(exist_ok=True)
                    try:child.wait(timeout=8)
                    except subprocess.TimeoutExpired:child.kill();child.wait(timeout=5)
                if mode=="shell":child.close()
        if mode=="shell":
            fresh=set((state/"desktop-results").glob("*.json"))-desktop_before
            if len(fresh)!=1:raise RuntimeError("Expected one desktop response")
            response=json.loads(next(iter(fresh)).read_text())
        else:
            response=json.loads(console.read_text())
        result=json.loads((session/"session-result.json").read_text()); transport=result["transport"]
        if (response["status"]!="closed" or response["completion"]!="live_session_closed" or
                not all(response[k] for k in ("guest_entry_observed","guest_execution_tested","tree_cleanup","normal_exit_verified")) or
                any(response[k] for k in ("guest_completed","independent_av_qualification_performed","graphics_verified",
                    "input_verified","windows_render_verified","automated_gameplay_input_sent","automated_window_close_sent")) or
                response["effective_settings"]!={"log_level":level,"volume_percent":percent} or
                response["settings_sources"]["volume_percent"]!=source or
                transport["reason"]!="exited" or transport["exit_code"] or transport["forced_termination"] or
                transport["active_before_cleanup"] or not transport.get("owner_watch_verified") or result["audit"]["unresolved"]):
            raise RuntimeError("Live registration/normal-close/settings contract failed: "+name)
        engine_config=json.loads((session/"session/user/config.json").read_text())
        if engine_config["General"]["volume_slider"]!=percent or engine_config["Log"]["filter"]!="*:"+level:
            raise RuntimeError("Saved settings did not reach the engine")
        logpath=session/"session/user/log/shad_log.txt";text=logpath.read_text()
        counts={kind.lower():len(re.findall("<"+kind+">",text)) for kind in ("Debug","Info","Warning")}
        if (level=="warning" and (counts["debug"] or counts["info"])) or (level!="warning" and not counts["info"]):
            raise RuntimeError("Diagnostic preference did not affect engine logs")
        record=dict(name=name,mode=mode,session_id=response["session_id"],response=response,transport=transport,
            result_sha256=startup.digest(session/"session-result.json"),launch_result_sha256=startup.digest(session/"launch-result.json"),
            audit_sha256=result["audit"]["sha256"],engine_config_sha256=startup.digest(session/"session/user/config.json"),
            log_counts=counts,log_sha256=startup.digest(logpath),external_captures=captures,external_input=actions,external_close=close)
        if long:
            if time.monotonic()-ready<125 or len(result["samples"])!=1 or captures or list(session.rglob("*.raw")):
                raise RuntimeError("Long ordinary shortcut required input/capture or stopped early")
        else:
            record["external_input_analysis"]=live.verify_input(session/"session/user/data/live-input.bin",result["samples"],captures)
        if mode=="qualified-cli":
            record["external_audio"]=json.loads((session/"external-audio.json").read_text())
        elif list(session.rglob("*.raw")):
            raise RuntimeError("Ordinary registered launch unexpectedly captured audio")
        if startup.digest(config)!=config_hash or startup.digest(link)!=link_hash:
            raise RuntimeError("Launch/settings changed registration or the existing shortcut")
        after=(state/"settings.json").read_bytes() if (state/"settings.json").exists() else None
        if after!=settings_before:raise RuntimeError("Launch migrated or rewrote preferences")
        for path,checksum in retained.items():
            if startup.digest(path)!=checksum:raise RuntimeError("Earlier session evidence changed")
        for path in (session/"session-result.json",session/"launch-result.json"):retained[path]=startup.digest(path)
        record["expected_outcome_passed"]=True;cases.append(record)
        print(name+" passed",flush=True)

    run("default-cli","cli",100,"info","default")
    call("settings","set","log_level","warning");call("settings","set","volume_percent","50")
    run("global-half-qualified-cli","qualified-cli",50,"warning","global")
    run("global-half-reopened-cli","cli",50,"warning","global")
    def ui_volume(index):
        import tkinter as tk
        import ps4_settings as ui
        root=tk.Tk()
        try:
            window=ui.SettingsWindow(root,state,"live-av");root.update()
            window.level.current(1);window.level.event_generate("<<ComboboxSelected>>")
            window.volume.current(index);window.volume.event_generate("<<ComboboxSelected>>");root.update()
            window.save_button.invoke();root.update()
            if "Saved." not in window.status.get():raise RuntimeError("Actual Settings save failed")
        finally:root.destroy()
    ui_volume(1)
    run("ui-title-mute-shell","shell",0,"debug","title")
    run("title-mute-qualified-cli","qualified-cli",0,"debug","title")
    call("settings","set","volume_percent","100","--title","live-av")
    run("title-full-qualified-cli","qualified-cli",100,"debug","title")
    ui_volume(0)
    run("ui-volume-inherit-shell","shell",50,"debug","global")
    call("settings","reset","--key","volume_percent")
    run("global-volume-reset-qualified-cli","qualified-cli",100,"debug","default")
    call("settings","set","log_level","warning","--title","live-av")
    run("long-no-input-shell","shell",100,"warning","default",long=True)
    before_sessions=set((state/"sessions").glob("*"));settings=state/"settings.json";saved=settings.read_bytes()
    invalid=json.loads(saved);invalid["titles"]["live-av"]["volume_percent"]=25;settings.write_text(json.dumps(invalid))
    rejected=call("launch","live-av",expected=3)
    if rejected["error"]["code"]!="invalid_settings" or rejected["engine_launch_attempted"] or rejected["session_id"] is not None:
        raise RuntimeError("Invalid live settings did not fail before execution")
    settings.write_bytes(saved)
    original=fixture.read_bytes();fixture.write_bytes(b"changed owned test fixture")
    rejected=call("launch","live-av",expected=4);fixture.write_bytes(original)
    if rejected["error"]["code"]!="input_verification_failed" or set((state/"sessions").glob("*"))!=before_sessions:
        raise RuntimeError("Changed fixture was not rejected before a new session")
    summary=dict(schema_version=1,status="endpoint_verification_pending" if observer else "passed",guest_execution_tested=True,cases=cases,
        actual_shell_activations=3,qualified_cli_test_host_sessions=0 if observer else 4,unmodified_cli_sessions=6 if observer else 2,
        muted_endpoint_matrix=observer is not None, pcm_qualification_performed=observer is None,
        registration_sha256=config_hash,existing_shortcut_sha256=link_hash,invalid_settings_and_fixture_rejected_before_execution=True,
        physical_human_input_tested=False,hardware_acoustic_output_tested=False,upstream_redistribution_approved=False)
    (output/"summary.json").write_text(json.dumps(summary,indent=2)+"\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(qualified_cli() if len(sys.argv)>1 and sys.argv[1]=="qualified-cli" else main())
