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


def supervision_snapshot(details):
    """Additive schema 1: allowlisted records, <=32 secondaries and <=64 KiB JSON.

    Never copy transport, stderr, observer payloads or arbitrary exception data.
    Shared overflow and projection drops are counted separately and in total.
    This is diagnostic provenance, never a process/guest acceptance oracle.
    """
    if type(details) is not dict:
        raise ValueError("Invalid shared supervision metadata")
    truncated = 0

    def text(value, limit):
        nonlocal truncated
        if type(value) is not str:
            raise ValueError("Invalid supervision diagnostic text")
        truncated += int(len(value) > limit)
        return value[:limit]

    def record(row, *, cause=False):
        if type(row) is not dict:
            raise ValueError("Invalid supervision diagnostic record")
        result = dict(type=text(row['type'], 64), message=text(row['message'], 512))
        if not cause:
            result['phase'] = text(row['phase'], 64)
            for field in ('errno', 'winerror', 'hresult', 'observer_exit_code', 'unix_ns'):
                value = row.get(field)
                if value is not None:
                    if type(value) is not int or not -(2**63) <= value < 2**63:
                        raise ValueError("Invalid supervision diagnostic code")
                    result[field] = value
            stamp = row.get('qpc_seconds')
            if stamp is not None:
                if type(stamp) not in (int, float) or not math.isfinite(stamp):
                    raise ValueError("Invalid supervision diagnostic timestamp")
                result['qpc_seconds'] = stamp
            if row.get('cause') is not None:
                result['cause'] = record(row['cause'], cause=True)
            if 'metadata_error' in row:
                result['metadata_error'] = text(row['metadata_error'], 512)
        return result

    shared_dropped = details.get('secondary_dropped', 0)
    rows = details.get('secondary_failures', [])
    if (type(shared_dropped) is not int or not 0 <= shared_dropped < 2**63 or
            type(rows) is not list):
        raise ValueError("Invalid supervision diagnostic overflow metadata")
    primary = details.get('primary_failure')
    value = dict(schema_version=1, primary_failure=None if primary is None else record(primary),
                 secondary_failures=[record(row) for row in rows[:32]],
                 shared_secondary_dropped=shared_dropped,
                 projection_secondary_dropped=max(0, len(rows) - 32),
                 secondary_dropped=shared_dropped + max(0, len(rows) - 32), fields_truncated=truncated)
    while len(json.dumps(value, allow_nan=False).encode('utf-8')) > 65536:
        if not value['secondary_failures']:
            raise ValueError("Supervision primary metadata exceeds size limit")
        value['secondary_failures'].pop()
        value['projection_secondary_dropped'] += 1
        value['secondary_dropped'] += 1
    return value


def publication_failure_record(error, phase):
    """Last-sink metadata must not invoke the fallible shared record builder."""
    record = dict(type=type(error).__name__[:64], phase=phase[:64])
    try:
        record['message'] = str(error)[:512]
    except Exception:
        record.update(message='Exception text unavailable', metadata_unavailable=True)
    for field in ('errno', 'winerror', 'hresult'):
        try:
            value = getattr(error, field, None)
            if value is not None:
                if type(value) is int and -(2**63) <= value < 2**63:
                    record[field] = value
                else:
                    record['metadata_unavailable'] = True
        except Exception:
            record['metadata_unavailable'] = True
    return record


def capture_failure(fault, error, phase, emit=None):
    """Retain FIRST even if its diagnostic metadata/serialization fails."""
    try:
        fault.capture(error, phase, emit)
    except Exception as metadata_error:
        # FirstFailure latches the object before constructing/emitting its record.
        # Keep that object and classification instead of converting TypeError.
        fault.diagnostic_error = publication_failure_record(metadata_error, 'first_failure_metadata')['message']
        if fault.record is None:
            fault.record = publication_failure_record(fault.error, phase)
            fault.record['metadata_unavailable'] = True


def write_session_result(path, result, fault, emit):
    """One exclusive publication attempt; failure is explicit and never retried.

    If the result cannot persist, append a bounded failure marker to the existing
    journal. If that also fails, expose both failures on the original exception.
    Raising FIRST preserves its object, codes and existing explicit cause.
    """
    fault.update_result(result)
    try:
        raw = json.dumps(result, indent=2, allow_nan=False) + '\n'
        with path.open('x', encoding='utf-8') as stream:
            if stream.write(raw) != len(raw):
                raise OSError("Incomplete v2 session result write")
    # RuntimeError deliberately includes standard JSON RecursionError.
    except (OSError, ValueError, TypeError, OverflowError, RuntimeError) as error:
        capture_failure(fault, error, 'final_result_write', emit)
        fault.update_result(result)
        publication = publication_failure_record(error, 'final_result_write')
        first_phase = fault.record.get('phase') if type(fault.record) is dict else None
        if type(first_phase) is not str:
            first_phase = 'first_failure'
        marker = dict(secondary_persistence_unsuccessful=True,
                      publication_failure=publication,
                      first_failure=publication_failure_record(fault.error, first_phase),
                      supervision_diagnostics=result.get('supervision_diagnostics'),
                      supervision_diagnostics_persistence=result.get('supervision_diagnostics_persistence'))
        fault.error.secondary_persistence_unsuccessful = True
        fault.error.result_publication_failure = publication
        try:
            emit('final_result_write_failure', **marker)
        except (OSError, ValueError, TypeError, RuntimeError) as diagnostic_error:
            fault.error.secondary_publication_failure = publication_failure_record(
                diagnostic_error, 'final_result_failure_journal')
        raise fault.error


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
    supervision_diagnostics = {}
    phase = "preflight"

    def emit(event, **fields):
        if diagnostics is not None:
            diagnostics.emit(event, **fields)

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
                emit("owner_metadata_created", supervisor_pid=pid)
            except (OSError, ValueError) as error:
                capture_failure(fault, error, "immutable_owner_creation", emit)
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
                capture_failure(fault, error, "guest_audit_monitor", emit)
                raise
            return False

        result["engine_launch_attempted"] = True
        command = [engine, "--game", staged, "--ignore-game-patch", "--startup-audit", trace]
        result["command"] = list(map(str, command))
        phase = "supervision"
        result["transport"] = startup.supervise(supervisor, command, work, None, poll,
            on_started=started, environment=render_environment(), diagnostics=supervision_diagnostics)
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
    except (OSError, ValueError, TypeError, RuntimeError, subprocess.SubprocessError) as error:
        if fault.error is not None and error is not fault.error:
            result["supervision_error"] = str(error)
        capture_failure(fault, error, phase, emit)
        fault.update_result(result)
    finally:
        if result["engine_launch_attempted"]:
            try:
                collect_failure_evidence(output, result)
            except (OSError, ValueError, RuntimeError) as error:
                result["postmortem_error"] = str(error)
                capture_failure(fault, error, "postmortem", emit)
                fault.update_result(result)
        try:
            result['supervision_diagnostics'] = supervision_snapshot(supervision_diagnostics)
            result['supervision_diagnostics_persistence'] = dict(status='included')
        except (OSError, ValueError, TypeError, KeyError, OverflowError) as error:
            # Explicit loss marker, never an unbounded/raw fallback or success.
            result['supervision_diagnostics_persistence'] = dict(status='failed',
                type=type(error).__name__, message='Shared diagnostic projection failed')
            capture_failure(fault, error, 'supervision_diagnostics_metadata', emit)
            fault.update_result(result)
        if diagnostics:
            try:
                emit("supervision_outcome", transport=result.get("transport"),
                                 status=result["status"], postmortem_error=result.get("postmortem_error"))
            except (OSError, ValueError, TypeError, RuntimeError) as error:
                result["outcome_diagnostic_error"] = str(error)
                capture_failure(fault, error, "outcome_diagnostics")
                fault.update_result(result)
        write_session_result(output / "session-result.json", result, fault, emit)
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
