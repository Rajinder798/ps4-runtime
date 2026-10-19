# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later

"""Opt-in real live guest checks; only this test driver sends gameplay keys/close."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import run_homebrew_startup as startup
import run_live_av as live
import videoout_capture as transport


def worker():
    options = json.loads(Path(sys.argv[2]).read_text())
    for key in ("engine", "engine_report", "fixture", "supervisor", "capture_helper", "output"):
        options[key] = Path(options[key])
    options["output"].mkdir()
    code, result = live.run_attempt(**options)
    print(json.dumps(result, indent=2))
    return code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("engine", "engine-report", "fixture", "supervisor", "capture-helper", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--case", choices=("neutral-close", "pressed-close", "silent", "swapped",
                        "wrong-button", "no-input", "deadline", "bad-challenge"))
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    cases = []
    for name in ((args.case,) if args.case else ("neutral-close", "pressed-close", "silent", "swapped",
                 "wrong-button", "no-input", "deadline", "bad-challenge")):
        directory = output / name
        options = {k: str(getattr(args, k).resolve()) for k in
                   ("engine", "engine_report", "fixture", "supervisor", "capture_helper")}
        options.update(output=str(directory), timeout=8 if name == "deadline" else 25,
                       audio_case={"silent": "silence", "swapped": "swapped"}.get(name, "normal"),
                       palette_case="missing" if name == "bad-challenge" else "valid")
        settings = output / (name + "-options.json")
        settings.write_text(json.dumps(options))
        actions, seen_at, next_action, close = [], {}, 0, None
        with (output / (name + "-console.txt")).open("wb") as log:
            process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "worker", str(settings)],
                                       stdout=log, stderr=subprocess.STDOUT, **startup.background_process_options())
            began = time.monotonic()
            try:
                while process.poll() is None:
                    if time.monotonic() - began > 45:
                        raise RuntimeError("Live worker exceeded its bounded cleanup budget")
                    status_path = directory / "live-status.json"
                    try:
                        status = json.loads(status_path.read_text())
                    except (OSError, ValueError):
                        time.sleep(0.02)
                        continue
                    captures = status["captures"]
                    if captures:
                        sequence = captures[-1]["sequence"]
                        seen_at.setdefault(sequence, time.monotonic())
                        held = time.monotonic() - seen_at[sequence]
                        if close is None and held >= 1.0 and sequence == next_action:
                            owner = status["supervisor_pid"]
                            if name == "deadline":
                                pass
                            elif name == "no-input" or next_action == (5 if name == "pressed-close" else 4):
                                close = transport.request_close(owner, args.engine)
                            elif name != "bad-challenge":
                                key = "circle" if name == "wrong-button" else "cross"
                                actions.append(dict(after_sequence=sequence, **transport.send_key(owner, args.engine,
                                                    key, next_action % 2 == 0)))
                                next_action += 1
                    time.sleep(0.02)
                process.wait(timeout=5)
            finally:
                if process.poll() is None:
                    stop = directory / "session/stop.request"
                    if stop.parent.exists():
                        stop.touch(exist_ok=True)
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
        result = json.loads((directory / "live-result.json").read_text())
        lifetime = result["transport"]
        if not result["guest_entry_observed"] or result["audit"]["unresolved"] or not lifetime["tree_cleanup"]:
            raise RuntimeError("Missing strict actual guest/cleanup evidence: " + name)
        if any(a["root_pid"] != lifetime["root_pid"] for a in actions) or (close and close["root_pid"] != lifetime["root_pid"]):
            raise RuntimeError("Live test input/close ownership mismatch")
        expected_success = name in ("neutral-close", "pressed-close")
        if expected_success:
            if (process.returncode or result["status"] != "passed" or result["guest_completed"] or
                    not all(result[k] for k in ("running_observed", "graphics_verified", "input_verified",
                                                "windows_render_verified", "active_guest_close_verified")) or
                    result["input_analysis"]["pressed_at_close"] != (name == "pressed-close")):
                raise RuntimeError("Live guest qualification failed: " + name + ": " + result.get("error", ""))
        elif process.returncode != 1 or result["status"] != "failed":
            raise RuntimeError("Live negative did not fail: " + name)
        if name not in ("deadline", "bad-challenge") and (not close or lifetime["reason"] != "exited" or
                lifetime["exit_code"] != 0 or lifetime["forced_termination"] or lifetime["active_before_cleanup"] != 0):
            raise RuntimeError("Live active-guest window close did not complete normally")
        if result["automated_gameplay_input_sent"] is not False or result["input_source"] != "external_keyboard":
            raise RuntimeError("Live runner substituted scripted gameplay input")
        helper = result.get("process_capture", {})
        if name != "bad-challenge" and (not helper.get("helper_exit_confirmed") or
                helper.get("helper_forced_termination") or helper.get("helper_exit_code") != 0):
            raise RuntimeError("Live capture helper did not exit cleanly")
        expected_error = {"silent": "required ordered stereo tones", "swapped": "required ordered stereo tones",
                          "wrong-button": "two independent Cross cycles", "no-input": "live guest input records",
                          "deadline": "did not close normally", "bad-challenge": "Invalid/failing live guest output"}
        if not expected_success and expected_error[name] not in result.get("error", ""):
            raise RuntimeError("Live negative failed for an unexpected reason: " + result.get("error", ""))
        record = dict(name=name, expected_outcome_passed=True, expected_success=expected_success,
                      result=result, input_transport=actions, close_transport=close,
                      result_sha256=startup.digest(directory / "live-result.json"))
        cases.append(record)
        print(name + " passed its expected outcome", flush=True)
    summary = dict(schema_version=1, status="passed", guest_execution_tested=True, cases=cases,
                   test_input_source="automated owned-window transport external to live runner",
                   physical_human_input_tested=False, hardware_acoustic_output_tested=False,
                   upstream_redistribution_approved=False)
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")


if __name__ == "__main__":
    sys.exit(worker() if len(sys.argv) > 1 and sys.argv[1] == "worker" else main())
