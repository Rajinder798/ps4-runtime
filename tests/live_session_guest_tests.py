# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later

"""Opt-in real guest session lifetime checks. Automation belongs only to this driver."""
import argparse
import ctypes as c
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import live_av_evidence as evidence
import run_homebrew_startup as startup
import run_live_session as session
from process_audio import ProcessCapture
import videoout_capture as windows


def worker():
    """Add capture in the test host, preserving the helper's sibling-parent gate."""
    options = json.loads(Path(sys.argv[2]).read_text())
    helper = Path(options.pop("capture_helper"))
    options = {key: Path(value) for key, value in options.items()}
    output = options["output"]
    output.mkdir()
    original = startup.supervise

    def with_test_capture(supervisor, command, work, timeout, on_poll, *, on_started, environment):
        capture, owner = None, []

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
                    capture = ProcessCapture(helper, external, 30)
                if capture.ready(owner[0], options["engine"]):
                    (output / "capture-ready.txt").write_text("ready")
            return stop

        try:
            transport = original(supervisor, command, work, timeout, poll, on_started=started, environment=environment)
            if capture is not None:
                pcm, checksum = capture.decode(transport)
                challenge = list((work / "app/audio.bin").read_bytes()[:4])
                analysis = dict(**evidence.analyze_audio(pcm, challenge, False), pcm_sha256=checksum)
                (output / "external-audio.json").write_text(json.dumps(dict(analysis=analysis, process_capture=capture.close())))
            return transport
        finally:
            if capture is not None:
                capture.close()

    startup.supervise = with_test_capture
    code, result = session.run_session(**options)
    print(json.dumps(result, indent=2))
    return code


def wait_dead(pid):
    kernel = c.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [c.c_uint32, c.c_int, c.c_uint32]
    kernel.OpenProcess.restype = c.c_void_p
    kernel.WaitForSingleObject.argtypes = [c.c_void_p, c.c_uint32]
    kernel.WaitForSingleObject.restype = c.c_uint32
    kernel.CloseHandle.argtypes = [c.c_void_p]
    handle = kernel.OpenProcess(0x100000, False, pid)
    if handle:
        try:
            if kernel.WaitForSingleObject(handle, 6000) != 0:
                raise RuntimeError("Owned process did not exit")
        finally:
            kernel.CloseHandle(handle)
    elif c.get_last_error() != 87:
        raise c.WinError(c.get_last_error())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("engine", "engine-report", "fixture", "supervisor", "capture-helper", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--case", choices=("no-input-close", "long-session", "launcher-death", "requested-stop"))
    args = parser.parse_args()
    args.engine = args.engine.resolve(strict=True)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    records = []
    for name in ((args.case,) if args.case else ("no-input-close", "long-session", "launcher-death", "requested-stop")):
        directory = output / name
        options = {key: str(getattr(args, key).resolve()) for key in
                   ("engine", "engine_report", "fixture", "supervisor", "capture_helper")}
        options["output"] = str(directory)
        settings = output / (name + "-options.json")
        settings.write_text(json.dumps(options))
        command = [sys.executable, str(Path(__file__).resolve()), "worker", str(settings)]
        actions, captures, consumed = [], [], set()
        close = owner = root_pid = None
        began = time.monotonic()
        ready_at = qualified_at = last_request = None
        with (output / (name + "-console.txt")).open("wb") as log:
            process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                       **startup.background_process_options())
            try:
                while process.poll() is None:
                    now = time.monotonic()
                    if now - began > (185 if name == "long-session" else 45):
                        raise RuntimeError("Acceptance driver exceeded its cleanup budget")
                    try:
                        status = json.loads((directory / "session-status.json").read_text())
                    except (OSError, ValueError):
                        time.sleep(0.02)
                        continue
                    owner = status["supervisor_pid"]
                    if not status["running_observed"]:
                        time.sleep(0.02)
                        continue
                    if ready_at is None:
                        root_pid = windows._owned_window(owner, args.engine)[2]
                        ready_at = now
                    if name == "launcher-death":
                        process.kill()
                        break
                    if name == "requested-stop":
                        (directory / "session/stop.request").touch(exist_ok=True)
                    elif name == "no-input-close" and close is None and now - ready_at >= 1:
                        close = windows.request_close(owner, args.engine)
                    elif name == "long-session" and now - ready_at >= 125:
                        (directory / "capture.request").touch(exist_ok=True)
                        if (directory / "capture-ready.txt").exists():
                            sample = status["samples"][-1]
                            sequence = sample["sequence"]
                            if sequence == len(captures):
                                if last_request is None or now - last_request >= 0.4:
                                    windows.request_screenshot(owner, args.engine)
                                    last_request = now
                                for path in sorted(set((directory / "session/user/screenshots").glob("*.png")) - consumed):
                                    try:
                                        palette = (directory / "session/app/palette.bin").read_bytes()
                                        image = evidence.verify_image(path, palette, sequence, sample["buttons"])
                                    except ValueError:
                                        if path.stat().st_size > 4 * 1024 * 1024:
                                            raise ValueError("External screenshot exceeds size limit")
                                        continue
                                    consumed.add(path)
                                    captures.append(dict(**image, path=str(path.relative_to(output))))
                                    qualified_at = now
                                    break
                            if close is None and sequence == len(captures) - 1 and qualified_at is not None and now - qualified_at >= 1:
                                if sequence == 4:
                                    close = windows.request_close(owner, args.engine)
                                elif len(actions) == sequence:
                                    actions.append(dict(after_sequence=sequence, seconds_after_ready=now-ready_at,
                                        **windows.send_key(owner, args.engine, "cross", sequence % 2 == 0)))
                    time.sleep(0.02)
                process.wait(timeout=6)
                if name == "launcher-death":
                    wait_dead(root_pid)
                    wait_dead(owner)
                transport = json.loads((directory / "session/supervisor.json").read_text())
                if (transport["root_pid"] != root_pid or transport.get("lifetime") != "until_exit" or
                        not transport.get("owner_watch_verified") or not transport["tree_cleanup"]):
                    raise RuntimeError("Missing exact owned live-session cleanup evidence")
                record = dict(name=name, transport=transport, external_input=actions, external_close=close,
                              duration_seconds=time.monotonic()-began)
                if name in ("launcher-death", "requested-stop"):
                    if transport["reason"] != ("owner_exited" if name == "launcher-death" else "requested") or not transport["forced_termination"]:
                        raise RuntimeError("Forced cleanup did not have the expected cause")
                    wait_dead(root_pid)
                    if name == "launcher-death" and (directory / "session-result.json").exists():
                        raise RuntimeError("Killed launcher unexpectedly claimed a completed result")
                    if name == "requested-stop":
                        result = json.loads((directory / "session-result.json").read_text())
                        if process.returncode != 1 or result["status"] != "failed" or result["normal_exit_verified"]:
                            raise RuntimeError("Stop request was falsely reported as normal close")
                        record["result"] = result
                else:
                    result = json.loads((directory / "session-result.json").read_text())
                    record["result"] = result
                    if (process.returncode or result["status"] != "closed" or not result["normal_exit_verified"] or
                            not result["running_observed"] or not result["guest_entry_observed"] or result["audit"]["unresolved"] or
                            any(result[k] for k in ("guest_completed", "independent_av_qualification_performed", "graphics_verified",
                                "input_verified", "windows_render_verified", "automated_gameplay_input_sent", "automated_window_close_sent"))):
                        raise RuntimeError("Ordinary session failed or overclaimed qualification: " + result.get("error", ""))
                    if transport["reason"] != "exited" or transport["exit_code"] or transport["forced_termination"] or transport["active_before_cleanup"]:
                        raise RuntimeError("Window close did not leave an independently empty tree")
                    if name == "no-input-close":
                        if len(result["samples"]) != 1 or any(directory.rglob("*.png")) or any(directory.rglob("*.raw")):
                            raise RuntimeError("Ordinary runner created qualification artifacts or required input")
                    else:
                        if len(actions) != 4 or actions[0]["seconds_after_ready"] < 125 or result["samples"][1]["elapsed_us"] < 120_000_000:
                            raise RuntimeError("Missing responsive guest evidence beyond the old cutoff")
                        if any(a["root_pid"] != root_pid for a in actions) or close["root_pid"] != root_pid:
                            raise RuntimeError("External input ownership mismatch")
                        record["external_graphics"] = captures
                        record["external_input_analysis"] = evidence.verify_input(directory / "session/user/data/live-input.bin", result["samples"], captures)
                        audio = json.loads((directory / "external-audio.json").read_text())
                        record["external_audio_analysis"] = audio["analysis"]
                        record["external_process_capture"] = audio["process_capture"]
                record["expected_outcome_passed"] = True
                records.append(record)
                print(name + " passed its expected outcome", flush=True)
            finally:
                if process.poll() is None:
                    stop = directory / "session/stop.request"
                    if stop.parent.exists():
                        stop.touch(exist_ok=True)
                    try:
                        process.wait(timeout=8)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
    summary = dict(schema_version=1, status="passed", cases=records, guest_execution_tested=True,
                   physical_human_input_tested=False, hardware_acoustic_output_tested=False,
                   upstream_redistribution_approved=False)
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")


if __name__ == "__main__":
    sys.exit(worker() if len(sys.argv) > 1 and sys.argv[1] == "worker" else main())
