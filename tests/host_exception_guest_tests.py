# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later

"""Opt-in alternating baseline/fixed minimized guest audio and exception evidence."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import run_homebrew_startup as startup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("engine", "engine-report", "baseline-engine", "baseline-report", "baseline-harness",
                 "supervisor", "fixture", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    environment, cases = dict(os.environ), []
    for index in range(3):
        for mode in ("baseline", "patched"):
            old = mode == "baseline"
            directory = output / (mode + "-" + str(index))
            runner_root = args.baseline_harness.resolve().parents[1] if old else ROOT
            command = [sys.executable, str(ROOT / "tests/small_buffer_window_guest_tests.py"),
                       "worker", "--runner-root", str(runner_root)]
            inputs = dict(engine=args.baseline_engine if old else args.engine,
                          engine_report=args.baseline_report if old else args.engine_report,
                          supervisor=args.supervisor, fixture=args.fixture, output=directory)
            for key, path in inputs.items():
                command.extend(["--" + key.replace("_", "-"), str(path.resolve())])
            process = subprocess.run([*command, "--shutdown", "window-close"], capture_output=True,
                                     timeout=65, env=dict(environment, SDL_TIMER_RESOLUTION="0"),
                                     **startup.background_process_options())
            (output / (directory.name + "-console.txt")).write_bytes(process.stdout + process.stderr)
            result = json.loads((directory / "audio-result.json").read_text())
            window = json.loads((directory / "minimized-diagnostic.json").read_text())
            transport = result["transport"]
            if (process.returncode or result["status"] != "passed" or
                    not all(result.get(key) for key in ("guest_entry_observed", "guest_completed",
                                                       "audio_sink_verified", "window_close_verified")) or
                    result["audit"]["unresolved"] or not window["minimized_observed"] or
                    window["root_pid"] != transport["root_pid"] or transport["reason"] != "exited" or
                    transport["exit_code"] != 0 or transport["forced_termination"] or
                    transport["active_before_cleanup"] != 0 or not transport["tree_cleanup"]):
                raise RuntimeError("Minimized PCM/guest/normal-close regression: " + directory.name)
            logs = sorted((directory / "session").rglob("shad_log.txt"))
            if len(logs) != 1:
                raise RuntimeError("Missing unique engine diagnostic log")
            text = logs[0].read_text(encoding="utf-8", errors="replace")
            critical = re.findall(r"^.*Unhandled Exception code 0xe06d7363.*$", text, re.MULTILINE)
            deferred = re.findall(r"^.*Deferring host C\+\+ exception 0xe06d7363.*$", text, re.MULTILINE)
            if old:
                if not critical or deferred:
                    raise RuntimeError("Baseline exception diagnosis did not reproduce; retain the run")
            elif critical or not deferred or "<Critical>" in text:
                raise RuntimeError("Patched host exception boundary was not observed cleanly")
            cases.append(dict(name=directory.name, mode=mode, challenge=result["challenge"],
                              guest_entry_observed=True, guest_completed=True, audio_sink_verified=True,
                              window_close_verified=True, transport=transport, minimized_window=window,
                              audio_analysis=result["audio_analysis"], critical_cpp_lines=critical,
                              deferred_host_cpp_lines=deferred, engine_log_sha256=startup.digest(logs[0]),
                              pcm_sha256=startup.digest(directory / "session/sdl-output.raw"),
                              result_sha256=startup.digest(directory / "audio-result.json"),
                              audit_sha256=result["audit"]["sha256"]))
    if dict(os.environ) != environment:
        raise RuntimeError("Parent environment changed")
    summary = dict(schema_version=1, status="passed", cases=cases,
                   baseline_engine_sha256=startup.digest(args.baseline_engine),
                   engine_sha256=startup.digest(args.engine), fixture_sha256=startup.digest(args.fixture),
                   guest_execution_tested=True, parent_environment_unchanged=True,
                   guest_fault_execution_tested=False, hardware_acoustic_output_tested=False,
                   upstream_redistribution_approved=False)
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
