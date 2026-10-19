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

import live_av_evidence as evidence
import run_homebrew_startup as startup
from process_audio import render_environment


def run_session(*, engine, engine_report, fixture, supervisor, output, startup_timeout=30):
    if (type(startup_timeout) not in (int, float) or not math.isfinite(startup_timeout) or
            not 3 <= startup_timeout <= 30 or any(output.iterdir())):
        raise ValueError("Fresh output and a 3–30 second startup budget are required")
    result = dict(schema_version=1, profile="live-av", status="failed", guest_entry_observed=False,
                  engine_launch_attempted=False, guest_execution_tested=False, guest_completed=False,
                  running_observed=False, normal_exit_verified=False, startup_timeout_seconds=startup_timeout,
                  lifetime="until_exit", independent_av_qualification_performed=False,
                  graphics_verified=False, input_verified=False, windows_render_verified=False,
                  automated_gameplay_input_sent=False, automated_window_close_sent=False,
                  hardware_acoustic_output_tested=False, upstream_redistribution_approved=False)
    try:
        if sys.platform != "win32" or platform.machine().lower() not in ("amd64", "x86_64"):
            raise ValueError("Live sessions require Windows x86-64")
        engine, engine_report, fixture, supervisor = [p.resolve(strict=True) for p in
                                                     (engine, engine_report, fixture, supervisor)]
        result["build"] = startup.verify_inputs(engine, engine_report, fixture, "live-av")
        result.update(engine_sha256=startup.digest(engine), fixture_sha256=startup.digest(fixture),
                      supervisor_sha256=startup.digest(supervisor), host=platform.platform(), cpu=platform.processor())
        work = output / "session"
        startup.prepare_session(work)
        (work / "user/config.json").write_text(json.dumps(dict(Log=dict(filter="*:info", flush_level="trace"),
                                                             General=dict(volume_slider=100))))
        app = work / "app"
        app.mkdir()
        staged = app / "live_av.oelf"
        shutil.copyfile(fixture, staged)
        if startup.digest(staged) != result["fixture_sha256"]:
            raise ValueError("Staged live fixture changed")
        palette = secrets.SystemRandom().sample(range(8), 4)
        challenge = secrets.SystemRandom().sample(range(4), 4)
        (app / "palette.bin").write_bytes(bytes(palette))
        (app / "audio.bin").write_bytes(bytes(challenge + [0]))
        result.update(palette=palette, audio_challenge=challenge)
        owner, published = [], None
        began = time.monotonic()
        trace = work / "startup-audit.jsonl"

        def publish(state):
            nonlocal published
            snapshot = dict(schema_version=1, supervisor_pid=owner[0],
                            running_observed=state["running_observed"],
                            guest_entry_observed=state["guest_entry_observed"], samples=state["samples"])
            if snapshot != published:
                temporary = output / "session-status.tmp"
                temporary.write_text(json.dumps(snapshot))
                temporary.replace(output / "session-status.json")
                published = snapshot

        def started(pid):
            owner.append(pid)
            publish(dict(running_observed=False, guest_entry_observed=False, samples=[]))

        def poll():
            state = evidence.progress(startup.read_events(trace))
            result.update(state)
            publish(state)
            if not state["running_observed"] and time.monotonic() - began > startup_timeout:
                raise ValueError("Live guest exceeded startup readiness budget")
            return False

        result["engine_launch_attempted"] = True
        command = [engine, "--game", staged, "--ignore-game-patch", "--startup-audit", trace]
        result["command"] = list(map(str, command))
        result["transport"] = startup.supervise(supervisor, command, work, None, poll,
            on_started=started, environment=render_environment())
        state = evidence.progress(startup.read_events(trace, final=True))
        result.update(state)
        result["guest_execution_tested"] = state["guest_entry_observed"]
        transport = result["transport"]
        if (transport["reason"] != "exited" or transport["exit_code"] != 0 or transport["forced_termination"] or
                transport["active_before_cleanup"] != 0 or not transport["tree_cleanup"] or
                transport.get("lifetime") != "until_exit" or transport.get("owner_watch_verified") is not True or
                not state["running_observed"]):
            raise ValueError("Live session did not exit normally after readiness with an independently empty process tree")
        # A normal host exit with an active guest is not guest completion or an
        # independent graphics/input/audio qualification. No cycles are required.
        result.update(status="closed", normal_exit_verified=True)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        result["error"] = str(error)
    finally:
        if result["engine_launch_attempted"]:
            try:
                startup.collect_failure_evidence(output, result)
            except (OSError, ValueError) as error:
                result["postmortem_error"] = str(error)
        (output / "session-result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return (0 if result["status"] == "closed" else 1), result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("engine", "engine-report", "fixture", "supervisor", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--startup-timeout", type=float, default=30)
    args = parser.parse_args()
    if not math.isfinite(args.startup_timeout) or not 3 <= args.startup_timeout <= 30:
        parser.error("--startup-timeout must be between 3 and 30 seconds")
    args.output = args.output.resolve()
    try:
        args.output.mkdir(parents=True, exist_ok=False)
    except OSError as error:
        parser.error(f"--output must be a new writable directory: {error}")
    print("Live homebrew: use N for Cross or B for Circle; close its window to end the session.", flush=True)
    code, result = run_session(**vars(args))
    print(json.dumps(result, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
