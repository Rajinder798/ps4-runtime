# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later

"""Run the locked live homebrew until its window closes, without qualification automation."""
import argparse
import json
import math
from pathlib import Path
import platform
import secrets
import shutil
import subprocess
import sys
import time

import live_av_v2_evidence as evidence
import live_av_v2_contract as contract
import run_homebrew_startup as startup
import runtime_settings
from process_audio import render_environment
from live_status import publish_status
from live_v2_diagnostics import Diagnostics, FirstFailure
from live_input import stage_input


def run_session(*, engine, engine_report, fixture, supervisor, output, startup_timeout=30,
                log_level="info", volume_percent=100, cross_key="n"):
    if (type(startup_timeout) not in (int, float) or not math.isfinite(startup_timeout) or
            not 3 <= startup_timeout <= 30 or any(output.iterdir()) or log_level not in runtime_settings.LOG_LEVELS or
            type(volume_percent) is not int or volume_percent not in runtime_settings.VOLUME_LEVELS or
            cross_key not in runtime_settings.CROSS_KEYS):
        raise ValueError("Fresh output, a 3–30 second startup budget and supported log/volume/Cross settings are required")
    result = dict(schema_version=1, profile="live-av-v2", status="failed", guest_entry_observed=False,
                  engine_launch_attempted=False, guest_execution_tested=False, guest_completed=False,
                  running_observed=False, normal_exit_verified=False, startup_timeout_seconds=startup_timeout,
                  lifetime="until_exit", independent_av_qualification_performed=False,
                  graphics_verified=False, input_verified=False, windows_render_verified=False,
                  automated_gameplay_input_sent=False, automated_window_close_sent=False,
                  hardware_acoustic_output_tested=False, upstream_redistribution_approved=False,
                  log_level=log_level, volume_percent=volume_percent, cross_key=cross_key)
    fault = FirstFailure()
    diagnostics = None
    phase = "preflight"
    try:
        diagnostics = Diagnostics(output / "session-diagnostics.jsonl")
        if sys.platform != "win32" or platform.machine().lower() not in ("amd64", "x86_64"):
            raise ValueError("Live sessions require Windows x86-64")
        engine, engine_report, fixture, supervisor = [p.resolve(strict=True) for p in
                                                     (engine, engine_report, fixture, supervisor)]
        result["build"] = contract.verify_inputs(engine, engine_report, fixture, "live-av-v2")
        result.update(engine_sha256=startup.digest(engine), fixture_sha256=startup.digest(fixture),
                      supervisor_sha256=startup.digest(supervisor), host=platform.platform(), cpu=platform.processor())
        work = output / "session"
        startup.prepare_session(work)
        result["input_configuration"] = stage_input(work, cross_key)
        (work / "user/config.json").write_text(json.dumps(dict(Log=dict(filter="*:" + log_level, flush_level="trace"),
                                                             General=dict(volume_slider=volume_percent))))
        result["initial_config_sha256"] = startup.digest(work / "user/config.json")
        app = work / "app"
        app.mkdir()
        staged = app / "live_av_v2.oelf"
        shutil.copyfile(fixture, staged)
        if startup.digest(staged) != result["fixture_sha256"]:
            raise ValueError("Staged live fixture changed")
        palette = secrets.SystemRandom().sample(range(8), 4)
        challenge = secrets.SystemRandom().sample(range(4), 4)
        (app / "palette.bin").write_bytes(bytes(palette))
        (app / "audio.bin").write_bytes(bytes(challenge))
        result.update(palette=palette, audio_challenge=challenge)
        began = time.monotonic()
        trace = work / "startup-audit.jsonl"

        def started(pid):
            try:
                if type(pid) is not int or pid <= 0:
                    raise ValueError("Invalid supervisor ownership identity")
                # Keep the existing complete-before-visible initial publication.
                # Never publish again to an existing ownership file.
                owner_path = output / "session-owner.json"
                if owner_path.exists():
                    raise FileExistsError("Immutable session ownership metadata already exists")
                publish_status(owner_path, dict(schema_version=1, supervisor_pid=pid))
                diagnostics.emit("owner_metadata_created", supervisor_pid=pid)
            except (OSError, ValueError) as error:
                fault.capture(error, "immutable_owner_creation", diagnostics.emit)
                raise

        def poll():
            if fault.error is not None:
                # Shared supervision may poll while containment is pending.
                # Request stop without new observation/publication work.
                return True
            try:
                state = evidence.progress(startup.read_events(trace))
                result.update(state)
                if not state["running_observed"] and time.monotonic() - began > startup_timeout:
                    raise ValueError("Live guest exceeded startup readiness budget")
            except (OSError, ValueError) as error:
                fault.capture(error, "guest_audit_monitor", diagnostics.emit)
                raise
            return False

        result["engine_launch_attempted"] = True
        command = [engine, "--game", staged, "--ignore-game-patch", "--startup-audit", trace]
        result["command"] = list(map(str, command))
        phase = "supervision"
        result["transport"] = startup.supervise(supervisor, command, work, None, poll,
            on_started=started, environment=render_environment())
        if fault.error is not None:
            raise fault.error
        phase = "final_guest_validation"
        state = evidence.progress(startup.read_events(trace, final=True))
        result.update(state)
        result["guest_execution_tested"] = state["guest_entry_observed"]
        transport = result["transport"]
        evidence.verify_transport(transport)
        if (transport["reason"] != "exited" or transport["exit_code"] != 0 or transport["forced_termination"] or
                transport["active_before_cleanup"] != 0 or not transport["tree_cleanup"] or
                transport.get("lifetime") != "until_exit" or transport.get("owner_watch_verified") is not True or
                not state["running_observed"]):
            raise ValueError("Live session did not exit normally after readiness with an independently empty process tree")
        # A normal host exit with an active guest is not guest completion or an
        # independent graphics/input/audio qualification. No cycles are required.
        result["journal"] = evidence.verify_records((work / "user/data/live-av-v2.bin").read_bytes(), state["samples"])
        result.update(status="closed", normal_exit_verified=True)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        if fault.error is not None and error is not fault.error:
            result["supervision_error"] = str(error)
        fault.capture(error, phase, diagnostics.emit if diagnostics else None)
        fault.update_result(result)
    finally:
        if result["engine_launch_attempted"]:
            try:
                collect_failure_evidence(output, result)
            except (OSError, ValueError) as error:
                result["postmortem_error"] = str(error)
                fault.capture(error, "postmortem", diagnostics.emit if diagnostics else None)
                fault.update_result(result)
        if diagnostics:
            try:
                diagnostics.emit("supervision_outcome", transport=result.get("transport"),
                                 status=result["status"], postmortem_error=result.get("postmortem_error"))
            except (OSError, ValueError) as error:
                result["outcome_diagnostic_error"] = str(error)
                fault.capture(error, "outcome_diagnostics")
                fault.update_result(result)
        fault.write_result(output / "session-result.json", result, diagnostics.emit if diagnostics else None)
    return (0 if result["status"] == "closed" else 1), result


def collect_failure_evidence(output, result):
    work = output / "session"
    transport = work / "supervisor.json"
    if transport.exists():
        result["transport"] = json.loads(transport.read_text())
    trace = work / "startup-audit.jsonl"
    if not trace.exists(): return
    result["audit_sha256"] = startup.digest(trace)
    events = startup.read_events(trace, final=True)
    try:
        result["postmortem"] = evidence.progress(events, allow_failure=True)
    except ValueError as error:
        result["validation_error"] = str(error)
    # Only a validated prefix proves entry; retain later failure separately.
    for i, event in enumerate(events):
        if isinstance(event, dict) and event.get("event") == "guest_entry":
            try: valid = evidence.progress(events[:i+1])["guest_entry_observed"]
            except ValueError: valid = False
            result.update(guest_entry_observed=valid, guest_execution_tested=valid)
            break


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("engine", "engine-report", "fixture", "supervisor", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--startup-timeout", type=float, default=30)
    parser.add_argument("--log-level", choices=runtime_settings.LOG_LEVELS, default="info")
    parser.add_argument("--volume-percent", type=int, choices=runtime_settings.VOLUME_LEVELS, default=100)
    parser.add_argument("--cross-key", choices=runtime_settings.CROSS_KEYS, default="n")
    args = parser.parse_args()
    if not math.isfinite(args.startup_timeout) or not 3 <= args.startup_timeout <= 30:
        parser.error("--startup-timeout must be between 3 and 30 seconds")
    args.output = args.output.resolve()
    try:
        args.output.mkdir(parents=True, exist_ok=False)
    except OSError as error:
        parser.error(f"--output must be a new writable directory: {error}")
    print(f"Live homebrew: use {args.cross_key.upper()} for Cross or B for Circle; close its window to end the session.", flush=True)
    code, result = run_session(**vars(args))
    print(json.dumps(result, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
