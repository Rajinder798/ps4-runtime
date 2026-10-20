# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later

"""Four bounded real-guest N/G hold versus owned-window-minimize diagnostics.

This deliberately induced focus-loss comparison is separate from ordinary
launch acceptance and cannot identify the cause of an untraced earlier event.
"""
import argparse
import ctypes as c
from ctypes import wintypes as w
import json
from pathlib import Path
import struct
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import live_av_evidence as evidence
import run_homebrew_startup as startup
import videoout_capture as windows
from live_status import read_status
from muted_endpoint import MutedEndpoint, validate_report
from owned_window_trace import OwnedWindowTrace


def verify_trace(events, minimize):
    """Reject unsolicited control release and minimize-before-held-key evidence."""
    actions = [e for e in events if e["event"] == "mapped_letter"]
    observations = [e for e in events if e["event"] == "guest_observation"]
    if ([e["down"] for e in actions] != [True, False] or
            [e["sample"]["sequence"] for e in observations] != [0, 1, 2] or
            [e["sample"]["buttons"] for e in observations] != [0, 0x4000, 0]):
        raise RuntimeError("Incomplete focus diagnostic key/guest sequence")
    press, release = observations[1:]
    if not actions[0]["monotonic"] < press["monotonic"] < release["monotonic"]:
        raise RuntimeError("Guest sequence did not follow the requested press")
    if minimize:
        requests = [e for e in events if e["event"] == "minimize_request"]
        states = [e for e in events if e["event"] == "owned_window_state" and
                  e["minimized"] and not e["thread_focus"] and not e["foreground"]]
        if (len(requests) != 1 or requests[0]["monotonic"] - press["monotonic"] < 2 or
                not any(requests[0]["monotonic"] < s["monotonic"] <= release["monotonic"] for s in states) or
                not requests[0]["monotonic"] < release["monotonic"] < actions[1]["monotonic"]):
            raise RuntimeError("No held-key/minimize/focus-loss/unsolicited-release ordering")
    elif (actions[1]["monotonic"] - press["monotonic"] < 2 or
          release["monotonic"] <= actions[1]["monotonic"]):
        raise RuntimeError("Control released early or did not hold for two seconds")
    return dict(guest_hold_seconds=release["monotonic"] - press["monotonic"],
                release_before_requested_key_up=release["monotonic"] < actions[1]["monotonic"])


def run_case(args, output, observer, key, minimize):
    directory = output / (key + ("-minimize" if minimize else "-control"))
    directory.mkdir()
    state = directory / "state"
    def call(*arguments):
        observer.check()
        child = subprocess.run([sys.executable, str(ROOT / "tools/ps4_launch.py"), "--state-dir", str(state),
                                *map(str, arguments), "--json"], capture_output=True, text=True, timeout=30,
                               **startup.background_process_options())
        if child.returncode or child.stderr:
            raise RuntimeError(child.stdout + child.stderr)
        return json.loads(child.stdout)
    call("register", "--engine", args.engine, "--engine-report", args.engine_report,
         "--supervisor", args.supervisor, "--live-av", args.fixture)
    if key == "g":
        call("settings", "set", "cross_key", key)
    preserved = {p: startup.digest(p) for p in (state / "launch-config.json", state / "settings.json") if p.exists()}
    events, images, consumed = [], [], set()
    def trace(event, **fields):
        record = dict(event=event, monotonic=time.monotonic(), **fields)
        with (directory / "transport.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record) + "\n")
        events.append(record)
        return record["monotonic"]
    key_name = "cross" if key == "n" else "cross-g"
    session = observation = close = None
    last_sequence = None
    pressed = released = minimized = last_capture_request = None
    began = time.monotonic()
    with (directory / "console.txt").open("wb") as log:
        observer.check()
        child = subprocess.Popen([sys.executable, str(ROOT / "tools/ps4_launch.py"), "--state-dir", str(state),
                                  "launch", "live-av", "--json"], stdout=log, stderr=subprocess.STDOUT,
                                 **startup.background_process_options())
        try:
            while child.poll() is None:
                observer.check()
                if time.monotonic() - began > 30:
                    raise RuntimeError("Focus diagnostic exceeded its fixed 30-second budget")
                sessions = list((state / "sessions").glob("*"))
                if not sessions:
                    time.sleep(0.02); continue
                if len(sessions) != 1:
                    raise RuntimeError("Expected exactly one owned session")
                session = sessions[0]
                try:
                    status = read_status(session / "session-status.json")
                except (OSError, ValueError):
                    time.sleep(0.02); continue
                if not status["running_observed"]:
                    time.sleep(0.02); continue
                owner = status["supervisor_pid"]
                if observation is None:
                    observation = OwnedWindowTrace(windows._owned_window(owner, args.engine), trace)
                if close is not None:
                    time.sleep(0.02); continue
                observation.poll()
                sample = status["samples"][-1]
                sequence = sample["sequence"]
                if sequence != last_sequence:
                    trace("guest_observation", sample=sample)
                    last_sequence = sequence
                if sequence > 2 or sample["buttons"] != (0x4000 if sequence == 1 else 0):
                    raise RuntimeError("Unexpected guest input during focus diagnostic")
                if sequence == 2 and not minimize and released is None:
                    raise RuntimeError("Control guest released before requested key-up; retain focus trace")
                if sequence == len(images) and not (minimize and sequence == 2):
                    if last_capture_request is None or time.monotonic() - last_capture_request >= 0.4:
                        windows.request_screenshot(owner, args.engine)
                        last_capture_request = time.monotonic()
                    palette = (session / "session/app/palette.bin").read_bytes()
                    for path in sorted(set((session / "session/user/screenshots").glob("*.png")) - consumed):
                        try:
                            image = evidence.verify_image(path, palette, sequence, sample["buttons"])
                        except ValueError:
                            if path.stat().st_size > 4 * 1024 * 1024: raise
                            continue
                        consumed.add(path)
                        images.append(dict(**image, path=str(path.relative_to(output))))
                        trace("image_verified", sequence=sequence, path=str(path.relative_to(output)))
                        break
                    observation.poll()
                now = time.monotonic()
                if sequence == 0 and len(images) == 1 and pressed is None:
                    pressed = trace("mapped_letter", **windows.send_key(owner, args.engine, key_name, True))
                elif sequence == 1 and len(images) == 2:
                    press_observed = next(e["monotonic"] for e in events if e["event"] == "guest_observation" and e["sample"]["sequence"] == 1)
                    if now - press_observed >= 2:
                        if minimize and minimized is None:
                            user, window, pid = windows._owned_window(owner, args.engine)
                            user.ShowWindowAsync.argtypes, user.ShowWindowAsync.restype = [w.HWND, c.c_int], w.BOOL
                            if not user.ShowWindowAsync(window, 6):  # SW_MINIMIZE: owned window only.
                                raise c.WinError(c.get_last_error())
                            minimized = trace("minimize_request", root_pid=pid)
                        elif not minimize and released is None:
                            released = trace("mapped_letter", **windows.send_key(owner, args.engine, key_name, False))
                elif sequence == 2 and (minimize or len(images) == 3):
                    if minimize and released is None:
                        released = trace("mapped_letter", **windows.send_key(owner, args.engine, key_name, False))
                    close = windows.request_close(owner, args.engine)
                    trace("close_request", **close)
                time.sleep(0.02)
            if child.wait(timeout=5):
                raise RuntimeError("Ordinary focus diagnostic launch failed")
        finally:
            if child.poll() is None:
                if session is not None: (session / "session/stop.request").touch(exist_ok=True)
                try: child.wait(timeout=8)
                except subprocess.TimeoutExpired: child.kill(); child.wait(timeout=5)
    result = json.loads((session / "session-result.json").read_text(encoding="utf-8"))
    response = json.loads((directory / "console.txt").read_text(encoding="utf-8"))
    transport = result["transport"]
    if (response["status"] != "closed" or not response["normal_exit_verified"] or
            response["effective_settings"]["cross_key"] != key or result["audit"]["unresolved"] or
            transport["exit_code"] or transport["forced_termination"] or not transport["tree_cleanup"] or
            not transport["root_exit_verified"] or transport["active_before_cleanup"]):
        raise RuntimeError("Focus diagnostic normal-close/cleanup/settings contract failed")
    raw = (session / "session/user/data/live-input.bin").read_bytes()
    records = list(struct.iter_unpack("<IIQQ", raw))
    if ([r[:2] for r in records] != [(0, 0), (1, 0x4000), (2, 0)] or
            len(result["samples"]) != 3 or any(tuple(r) != (s["sequence"], s["buttons"], s["timestamp"], s["flip"])
                for r, s in zip(records, result["samples"])) or
            not records[0][2] < records[1][2] < records[2][2] or
            not result["samples"][0]["audio_blocks"] < result["samples"][-1]["audio_blocks"]):
        raise RuntimeError("Independent guest pad records or progression mismatch")
    if len(images) != (2 if minimize else 3) or list(directory.rglob("*.raw")):
        raise RuntimeError("Unexpected image count or PCM capture")
    if any(startup.digest(p) != checksum for p, checksum in preserved.items()):
        raise RuntimeError("Diagnostic launch rewrote registration/preferences")
    verified = verify_trace(events, minimize)
    return dict(name=directory.name, expected_outcome_passed=True, input_configuration=result["input_configuration"],
                session_id=response["session_id"], transport=transport, samples=result["samples"], images=images,
                diagnostic=verified, window_observation=observation.summary())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("engine", "engine-report", "fixture", "supervisor", "muted-endpoint-observer", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--case", choices=("n-control", "g-control", "n-minimize", "g-minimize"),
                        help="Explicit isolated diagnostic; never an automatic retry")
    args = parser.parse_args()
    for name in ("engine", "engine_report", "fixture", "supervisor", "muted_endpoint_observer"):
        setattr(args, name, getattr(args, name).resolve(strict=True))
    output = args.output.resolve(); output.mkdir(parents=True, exist_ok=False)
    cases = []
    try:
        with MutedEndpoint(args.muted_endpoint_observer, output) as observer:
            for minimize in (False, True):
                for key in ("n", "g"):
                    name = key + ("-minimize" if minimize else "-control")
                    if args.case and args.case != name: continue
                    case = run_case(args, output, observer, key, minimize)
                    cases.append(case)
                    (output / name / "case-result.json").write_text(json.dumps(case, indent=2) + "\n", encoding="utf-8")
    except BaseException as error:
        (output / "failure.json").write_text(json.dumps(dict(status="failed", error=str(error),
            completed_cases=cases, automatic_retry_performed=False), indent=2) + "\n", encoding="utf-8")
        raise
    summary = dict(schema_version=1, status="passed", cases=cases,
                   endpoint_observation=validate_report(output / "endpoint.jsonl"),
                   input_hashes={str(getattr(args, k).relative_to(ROOT)): startup.digest(getattr(args, k))
                                 for k in ("engine", "engine_report", "fixture", "supervisor", "muted_endpoint_observer")},
                   original_failure_cause_established=False, production_input_fix=False,
                   pcm_qualification_performed=False, system_audio_settings_changed=False)
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(dict(status="passed", cases=len(cases))))


if __name__ == "__main__":
    main()
