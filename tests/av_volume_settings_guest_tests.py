# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Opt-in persisted AV volume via real CLI, Settings controls and existing Shell link."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"tools"))
from shortcut_guest_tests import activate
import audio_evidence


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("engine","engine-report","supervisor","capture-helper","helper","fixture","hello-world","service-roundtrip","output"):
        parser.add_argument("--"+name,type=Path,required=True)
    args = parser.parse_args()
    output = args.output.resolve(); output.mkdir(parents=True,exist_ok=False)
    state,links = output/"state",output/"shortcuts with spaces λ"
    def call(*arguments,expected=0):
        process = subprocess.run([sys.executable,str(ROOT/"tools/ps4_launch.py"),"--state-dir",str(state),
                                  *map(str,arguments),"--json"],capture_output=True,text=True,timeout=90)
        if process.returncode!=expected or process.stderr:
            raise RuntimeError(process.stdout+process.stderr)
        return json.loads(process.stdout)
    registration=["register","--engine",args.engine,"--engine-report",args.engine_report,"--supervisor",args.supervisor,
        "--capture-helper",args.capture_helper,"--interactive-av",args.fixture,"--hello-world",args.hello_world,
        "--service-roundtrip",args.service_roundtrip]
    call(*registration)
    config=state/"launch-config.json"; config_hash=digest(config)
    link=Path(call("shortcut","interactive-av","--directory",links,"--helper",args.helper)["shortcut"])
    link_hash=digest(link)
    settings_path=state/"settings.json"
    # A valid previous installation: schema 1, independent diagnostics retained.
    settings_path.write_text(json.dumps({"schema_version":1,"global":{"log_level":"info"},
        "titles":{"hello-world":{"log_level":"warning"},"interactive-av":{"log_level":"debug"}}}))
    legacy_settings=settings_path.read_bytes()
    cases,retained=[],{}
    def verify(report,mode,percent=None,source=None):
        if report["status"]!="completed" or not report["guest_entry_observed"] or not report["tree_cleanup"]:
            raise RuntimeError("Missing actual registered guest completion")
        session=Path(report["logs_directory"])
        av=report["title"]=="interactive-av"
        result_path=session/("videoout-result.json" if av else "startup-result.json")
        result=json.loads(result_path.read_text())
        record=dict(mode=mode,title=report["title"],session_id=report["session_id"],
            effective_settings=report["effective_settings"],settings_sources=report["settings_sources"],
            guest_entry_observed=True,transport=result["transport"],result_sha256=digest(result_path),
            launch_result_sha256=digest(session/"launch-result.json"),audit_sha256=digest(session/"session/startup-audit.jsonl"))
        if av:
            if (report["effective_settings"]!={"log_level":"debug","volume_percent":percent} or
                    report["settings_sources"]!={"log_level":"title","volume_percent":source} or
                    not all(report[k] and result[k] for k in ("graphics_verified","input_verified","combined_verified",
                        "volume_verified","windows_render_verified","window_close_verified")) or
                    report["audio_muted"]!=(percent==0) or report["audio_tone_verified"]!=(percent!=0) or
                    len(result["captures"])!=3 or result["audit"]["unresolved"] or
                    result["transport"]["forced_termination"] or result["transport"]["active_before_cleanup"]!=0):
                raise RuntimeError("Saved volume did not verify every guest/Windows output surface")
            pcm=session/"session/wasapi-capture/wasapi-output.raw"
            samples,checksum=audio_evidence.decode_pcm(pcm)
            analysis=audio_evidence.analyze_volume(samples,result["audio_challenge"],percent)
            if checksum!=result["audio_analysis"]["pcm_sha256"]:
                raise RuntimeError("PCM changed")
            try:
                audio_evidence.analyze_volume(samples,result["audio_challenge"],50 if percent!=50 else 100)
            except ValueError:
                pass
            else:
                raise RuntimeError("Actual captured output passed the wrong requested gain")
            configuration=session/"session/user/config.json"
            config_data=json.loads(configuration.read_text())
            if config_data["General"]["volume_slider"]!=percent or config_data["Log"]["filter"]!="*:debug":
                raise RuntimeError("Volume or diagnostic preference did not reach the actual engine")
            capture=result["process_capture"]
            if not capture["helper_exit_confirmed"] or capture["helper_exit_code"]!=0 or capture["helper_forced_termination"]:
                raise RuntimeError("Capture helper cleanup failed")
            record.update(audio_challenge=result["audio_challenge"],audio_analysis=analysis,pcm_sha256=checksum,
                config_sha256=digest(configuration),process_capture=capture,
                images=[{k:image[k] for k in ("phase","width","height","pixels_verified","png_sha256")} for image in result["captures"]],
                pad_observations_sha256=result["pad_observations"]["sha256"],
                audio_muted=report["audio_muted"],audio_tone_verified=report["audio_tone_verified"])
        elif not result["g2_passed"] or "volume_percent" in report["effective_settings"]:
            raise RuntimeError("Volume leaked into a legacy fixture")
        for path,checksum in retained.items():
            if digest(path)!=checksum:
                raise RuntimeError("Earlier evidence changed")
        retained[result_path]=digest(result_path)
        retained[session/"launch-result.json"]=digest(session/"launch-result.json")
        cases.append(record)
    def shell():
        before=set((state/"desktop-results").glob("*.json"))
        activate(link)
        fresh=set((state/"desktop-results").glob("*.json"))-before
        if len(fresh)!=1:
            raise RuntimeError("Expected exactly one desktop launch result")
        return json.loads(fresh.pop().read_text())
    verify(call("launch","interactive-av"),"schema1-default-cli",100,"default")
    if settings_path.read_bytes()!=legacy_settings:
        raise RuntimeError("Reading schema 1 rewrote preferences")
    call("settings","set","volume_percent","50")
    migrated=json.loads(settings_path.read_text())
    if migrated["schema_version"]!=2 or migrated["titles"]!=json.loads(legacy_settings)["titles"]:
        raise RuntimeError("Explicit volume upgrade lost prior diagnostics")
    verify(call("launch","interactive-av"),"global-half-cli",50,"global")
    verify(call("launch","interactive-av"),"global-half-reopened-cli",50,"global")
    import tkinter as tk
    import ps4_settings as ui
    def select_volume(index):
        root=tk.Tk()
        try:
            window=ui.SettingsWindow(root,state,"interactive-av"); root.update()
            window.volume.current(index); window.volume.event_generate("<<ComboboxSelected>>"); root.update()
            window.save_button.invoke(); root.update()
            if not window.status.get().startswith("Saved."):
                raise RuntimeError(window.status.get())
        finally:
            root.destroy()
    select_volume(1)  # Mute via real Settings controls.
    verify(shell(),"title-mute-ui-existing-shell",0,"title")
    call("settings","set","volume_percent","100","--title","interactive-av")
    verify(shell(),"title-full-cli-existing-shell",100,"title")
    select_volume(0)  # Inherit only volume; keep title Debug.
    verify(shell(),"title-inherit-ui-existing-shell",50,"global")
    call("settings","reset","--key","volume_percent")
    verify(call("launch","interactive-av"),"global-volume-reset-cli",100,"default")
    call("settings","set","volume_percent","50")
    verify(call("launch","hello-world"),"global-audio-legacy-hello")
    verify(call("launch","service-roundtrip"),"global-audio-legacy-service")
    before_settings=settings_path.read_bytes()
    invalid=json.loads(before_settings); invalid["global"]["volume_percent"]=25
    settings_path.write_text(json.dumps(invalid)); invalid_bytes=settings_path.read_bytes()
    before_sessions=set((state/"sessions").iterdir())
    rejected=call("launch","interactive-av",expected=3)
    if rejected["error"]["code"]!="invalid_settings" or rejected["engine_launch_attempted"] or rejected["session_id"] is not None:
        raise RuntimeError("Invalid persisted volume was not rejected before execution")
    if settings_path.read_bytes()!=invalid_bytes or set((state/"sessions").iterdir())!=before_sessions:
        raise RuntimeError("Rejected preferences changed evidence/state")
    settings_path.write_bytes(before_settings)  # Explicit repair by the test owner.
    if digest(config)!=config_hash or digest(link)!=link_hash or len(cases)!=9:
        raise RuntimeError("Registration/shortcut changed")
    summary=dict(schema_version=1,status="passed",guest_execution_tested=True,cases=cases,
        schema1_read_unchanged=True,explicit_schema2_upgrade_preserves_diagnostics=True,
        invalid_volume_rejected_before_session=True,registration_unchanged=True,existing_shortcut_unchanged=True,
        earlier_evidence_unchanged=True,settings_ui_controls_tested=True,windows_shell_activation_tested=True,
        engine_sha256=digest(args.engine),fixture_sha256=digest(args.fixture),supervisor_sha256=digest(args.supervisor),
        capture_helper_sha256=digest(args.capture_helper),registration_sha256=config_hash,shortcut_sha256=link_hash,
        hardware_acoustic_output_tested=False,upstream_redistribution_approved=False)
    (output/"summary.json").write_text(json.dumps(summary,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(summary,indent=2))


if __name__=="__main__":
    main()
