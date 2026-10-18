# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Opt-in registered AV self-test CLI/Shell launches and legacy registration preservation."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from shortcut_guest_tests import activate
import audio_evidence


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("engine", "engine-report", "supervisor", "capture-helper", "fixture", "hello-world", "service-roundtrip",
                 "helper", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve(); output.mkdir(parents=True, exist_ok=False)
    state, inputs, links = output / "state", output / "inputs", output / "shortcuts with spaces \u03bb"
    inputs.mkdir()
    fixture, capture = inputs / "interactive_av.oelf", inputs / "capture.exe"
    shutil.copyfile(args.fixture, fixture); shutil.copyfile(args.capture_helper, capture)

    def call(*arguments, expected=0):
        result = subprocess.run([sys.executable,str(ROOT / "tools/ps4_launch.py"),"--state-dir",str(state),
            *map(str,arguments),"--json"],capture_output=True,text=True,timeout=90)
        if result.returncode != expected or result.stderr:
            raise RuntimeError("Unexpected CLI result: " + result.stdout + result.stderr)
        return json.loads(result.stdout)

    setup = ["register","--engine",args.engine,"--engine-report",args.engine_report,"--supervisor",args.supervisor,
        "--hello-world",args.hello_world,"--service-roundtrip",args.service_roundtrip]
    call(*setup)
    config_path = state / "launch-config.json"
    if json.loads(config_path.read_text())["schema_version"] != 1:
        raise RuntimeError("Legacy registration was upgraded implicitly")
    legacy_link = Path(call("shortcut","hello-world","--directory",links,"--helper",args.helper)["shortcut"])
    legacy_link_hash = digest(legacy_link)
    cases, retained = [], {}

    def verify(report, mode, level="info", source="default"):
        if (report["status"] != "completed" or not report["guest_entry_observed"] or not report["tree_cleanup"] or
                report["effective_settings"] != {"log_level":level} or report["settings_sources"] != {"log_level":source}):
            raise RuntimeError("Missing actual registered guest/settings/cleanup evidence")
        session = Path(report["logs_directory"])
        av = report["title"] == "interactive-av"
        path = session / ("videoout-result.json" if av else "startup-result.json")
        evidence = json.loads(path.read_text())
        if av:
            if (report["completion"] != "fixture_observed_and_window_closed" or
                    report.get("input_source") != "automated_keyboard_sequence" or report.get("hardware_playback_tested") is not False or
                    not all(evidence[k] and report[k] for k in ("combined_verified","graphics_verified","input_verified",
                        "windows_render_verified","window_close_verified")) or len(evidence["captures"]) != 3 or
                    evidence["transport"]["forced_termination"] or evidence["transport"]["active_before_cleanup"] != 0):
                raise RuntimeError("Missing all-surface AV/window-close evidence")
            samples, pcm_hash = audio_evidence.decode_pcm(session / "session/wasapi-capture/wasapi-output.raw")
            analysis = audio_evidence.analyze_interaction(samples,evidence["audio_challenge"])
            if pcm_hash != evidence["audio_analysis"]["pcm_sha256"]:
                raise RuntimeError("Captured PCM checksum changed")
            config = json.loads((session / "session/user/config.json").read_text())
            if config["Log"]["filter"] != "*:" + level:
                raise RuntimeError("Effective preference did not reach the engine")
            log = session / "session/user/log/shad_log.txt"
            text = log.read_text(encoding="utf-8")
            counts = {name.lower():len(re.findall("<"+name+">",text)) for name in ("Debug","Info","Warning")}
            if (not counts["warning"] or (level == "warning" and (counts["debug"] or counts["info"])) or
                    (level in ("debug","info") and not counts["info"]) or
                    (level == "info" and counts["debug"]) or (level == "debug" and not counts["debug"])):
                raise RuntimeError("Saved diagnostic preference did not affect actual engine log levels")
            cases.append(dict(title=report["title"],mode=mode,session_id=report["session_id"],
                effective_settings=report["effective_settings"],settings_sources=report["settings_sources"],
                guest_entry_observed=True,combined_verified=True,windows_render_verified=True,
                window_close_verified=True,transport=evidence["transport"],process_capture=evidence["process_capture"],
                palette=evidence["palette"],audio_challenge=evidence["audio_challenge"],audio_analysis=analysis,
                pcm_sha256=pcm_hash,captures=evidence["captures"],pad_observations=evidence["pad_observations"],
                result_sha256=digest(path),audit_sha256=evidence["audit"]["sha256"],
                log_level_counts=counts,log_sha256=digest(log)))
        else:
            if not evidence["g2_passed"]:
                raise RuntimeError("Legacy strict fixture behavior failed")
            cases.append(dict(title=report["title"],mode=mode,session_id=report["session_id"],guest_entry_observed=True,
                transport=evidence["transport"],result_sha256=digest(path),audit_sha256=digest(session / "session/startup-audit.jsonl")))
        for previous, checksum in retained.items():
            if digest(previous) != checksum:
                raise RuntimeError("Earlier session evidence was modified")
        retained[path] = digest(path)
        retained[session / "launch-result.json"] = digest(session / "launch-result.json")

    def shell(link):
        before = set((state / "desktop-results").glob("*.json"))
        activate(link)
        fresh = set((state / "desktop-results").glob("*.json")) - before
        if len(fresh) != 1:
            raise RuntimeError("Exactly one new desktop result required")
        return json.loads(fresh.pop().read_text())

    verify(call("launch","hello-world"),"legacy-schema1-cli")
    verify(call("launch","service-roundtrip"),"legacy-schema1-cli")
    legacy_config_hash = digest(config_path)
    addition = ["--interactive-av",fixture,"--capture-helper",capture]
    rejected = call(*setup,*addition,expected=3)
    if rejected["error"]["code"] != "already_registered" or digest(config_path) != legacy_config_hash:
        raise RuntimeError("Failed upgrade changed legacy registration")
    call(*setup,*addition,"--replace")
    config_hash = digest(config_path)
    if json.loads(config_path.read_text())["schema_version"] != 2:
        raise RuntimeError("AV registration schema missing")
    av_link = Path(call("shortcut","interactive-av","--directory",links,"--helper",args.helper)["shortcut"])
    av_link_hash = digest(av_link)
    if call("shortcut","interactive-av","--directory",links,"--helper",args.helper,expected=3)["error"]["code"] != "shortcut_exists":
        raise RuntimeError("Duplicate shortcut was not rejected")
    verify(call("launch","interactive-av"),"av-cli-default")
    call("settings","set","log_level","warning")
    verify(call("launch","interactive-av"),"av-cli-global","warning","global")
    # Exercise actual optional Tk controls; routine launches never open Settings.
    import tkinter as tk
    import ps4_settings as ui
    def change_scope(reset=False):
        root = tk.Tk()
        try:
            window = ui.SettingsWindow(root,state,"interactive-av"); root.update()
            if reset:
                window.reset_button.invoke()
            else:
                window.level.current(ui.LEVELS.index("Debug")+1)
                window.level.event_generate("<<ComboboxSelected>>"); root.update()
                window.save_button.invoke()
            root.update()
            if not window.status.get().startswith("Saved."):
                raise RuntimeError(window.status.get())
        finally:
            root.destroy()
    change_scope()
    verify(shell(av_link),"av-shell-title-ui","debug","title")
    change_scope(reset=True)
    verify(shell(av_link),"av-shell-inherit-ui","warning","global")
    call("settings","reset")
    verify(call("launch","interactive-av"),"av-cli-reset")
    verify(shell(legacy_link),"legacy-schema2-existing-shell")
    verify(call("launch","service-roundtrip"),"legacy-schema2-cli")
    session_count = len(list((state / "sessions").iterdir()))
    rejected_requests = []
    for path in (capture,fixture):
        original = path.read_bytes()
        path.write_bytes(original + b"changed registered input")
        result = call("launch","interactive-av",expected=4)
        if (result["error"]["code"] != "input_verification_failed" or result["engine_launch_attempted"] or
                result["session_id"] is not None):
            raise RuntimeError("Tampered AV input was not rejected before execution")
        rejected_requests.append(result["error"]["code"])
        path.write_bytes(original)
    if (len(cases) != 9 or len({c["session_id"] for c in cases}) != 9 or session_count != 9 or
            len(list((state / "sessions").iterdir())) != 9 or digest(config_path) != config_hash or
            digest(av_link) != av_link_hash or digest(legacy_link) != legacy_link_hash):
        raise RuntimeError("Registration/shortcut/evidence persistence failed")
    summary = dict(schema_version=1,status="passed",guest_execution_tested=True,cases=cases,
        registration_unchanged_after_explicit_upgrade=True,earlier_evidence_unchanged=True,
        shortcuts_unchanged=True,windows_shell_activation_tested=True,settings_ui_controls_tested=True,
        rejected_requests=rejected_requests,hardware_acoustic_output_tested=False,upstream_redistribution_approved=False,
        engine_sha256=digest(args.engine),supervisor_sha256=digest(args.supervisor),
        capture_helper_sha256=digest(args.capture_helper),fixture_sha256=digest(args.fixture),
        registration_sha256=config_hash,legacy_shortcut_sha256=legacy_link_hash,av_shortcut_sha256=av_link_hash)
    (output / "summary.json").write_text(json.dumps(summary,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(summary,indent=2))


if __name__ == "__main__":
    main()
