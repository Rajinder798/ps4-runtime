# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later

"""Opt-in paired Windows Shell/real guest PCM investigation; never retries a case.

The Shell test entry imports each source tree's unmodified desktop/launcher path.
Only challenge selection is replaced, with the preserved failure's exact inputs.
This is a diagnostic shortcut, not a claim about an installed production link.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def shell_worker(source, state):
    sys.path.insert(0, str(source / "tools"))
    import run_videoout_research as video
    import ps4_desktop as desktop
    original = video.secrets.SystemRandom.sample
    def sample(self, population, k):
        if list(population) == list(range(4)) and k == 4:
            return [2, 1, 0, 3]
        return original(self, population, k)
    palette = iter([3, 2, 4, 6])
    def choice(population):
        value = next(palette)
        if value not in population:
            raise RuntimeError("Unexpected palette selection")
        return value
    video.secrets.SystemRandom.sample = sample
    video.secrets.choice = choice
    return desktop.run(state, "interactive-av")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--current", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--runs", type=int, default=20)
    for name in ("engine", "engine-report", "supervisor", "fixture", "capture-helper", "helper"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != "win32" or not 1 <= args.runs <= 20:
        parser.error("Windows and 1..20 runs per source required")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    sys.path.insert(0, str(ROOT / "tools"))
    sys.path.insert(0, str(ROOT / "tests"))
    import audio_evidence as audio
    from live_launch_guest_tests import ShellChild
    records = []
    inputs = {name: dict(path=str(getattr(args, name).resolve()), sha256=digest(getattr(args, name)))
              for name in ("engine", "engine_report", "supervisor", "fixture", "capture_helper", "helper")}
    def save():
        (output / "summary.json").write_text(json.dumps(dict(schema_version=1,
            status="complete" if len(records) == args.runs * 2 else "in_progress", inputs=inputs,
            test_driver_sha256=digest(Path(__file__)), runs_per_version=args.runs,
            audio_challenge=[2,1,0,3], palette=[3,2,4,6], cases=records), indent=2) + "\n")
    save()
    for iteration in range(1, args.runs + 1):
        # Alternate which source goes first as well as alternating versions.
        order = [("baseline", args.baseline), ("current", args.current)]
        if iteration % 2 == 0:
            order.reverse()
        for label, source in order:
            source = source.resolve()
            directory = output / f"{label}-{iteration:02}"
            directory.mkdir()
            state = directory / "state"
            def call(*arguments):
                p = subprocess.run([sys.executable, str(source / "tools/ps4_launch.py"),
                    "--state-dir", str(state), *map(str, arguments), "--json"],
                    capture_output=True, text=True, timeout=30)
                if p.returncode or p.stderr:
                    raise RuntimeError(p.stdout + p.stderr)
                return json.loads(p.stdout)
            call("register", "--engine", args.engine.resolve(), "--engine-report", args.engine_report.resolve(),
                 "--supervisor", args.supervisor.resolve(), "--interactive-av", args.fixture.resolve(),
                 "--capture-helper", args.capture_helper.resolve())
            call("settings", "set", "volume_percent", "100", "--title", "interactive-av")
            call("settings", "set", "log_level", "debug", "--title", "interactive-av")
            link = directory / "fixed-input-shell.lnk"
            command = subprocess.list2cmdline([str(Path(__file__).resolve()), "--shell-worker", str(source), str(state)])
            subprocess.run([str(args.helper.resolve()), "create", str(link),
                str(Path(sys.executable).with_name("pythonw.exe")), command, str(source),
                "PS4 Runtime fixed-input audio investigation"], check=True, capture_output=True, timeout=15)
            record = dict(version=label, iteration=iteration, source=str(source),
                began_utc=datetime.now(timezone.utc).isoformat(), shortcut_sha256=digest(link))
            child = ShellChild(link)
            try:
                deadline = time.monotonic() + 65
                response = None
                while time.monotonic() < deadline:
                    results = list((state / "desktop-results").glob("*.json"))
                    if len(results) == 1:
                        response = json.loads(results[0].read_text())
                        break
                    if child.poll() is not None:
                        break
                    time.sleep(.1)
                record["desktop_response"] = response
                # Failed desktop calls persist their evidence before displaying a modal.
                # Bound that owned process after recording failure; never replay the case.
                if response is None or response["status"] != "completed":
                    record["failed"] = True
                    record["failure_dialog_process_terminated"] = child.poll() is None
                    if child.poll() is None:
                        child.kill()
                record["desktop_exit_code"] = child.wait(10)
                if response and response.get("logs_directory"):
                    session = Path(response["logs_directory"])
                    detail = json.loads((session / "videoout-result.json").read_text())
                    raw = session / "session/wasapi-capture/wasapi-output.raw"
                    pcm, checksum = audio.decode_pcm(raw)
                    bad = [i for i in range(len(pcm)//2)
                           if max(abs(pcm[2*i]),abs(pcm[2*i+1])) > (2000/32768)*1.05]
                    try:
                        analysis = audio.analyze_volume(pcm, [2,1,0,3], 100)
                        record["independent_audio_analysis"] = analysis
                    except ValueError as error:
                        record["independent_audio_error"] = str(error)
                        record["failed"] = True
                    record.update(pcm_path=str(raw), pcm_sha256=checksum,
                        pcm_frames=len(pcm)//2, peak=max(map(abs,pcm)), overshoot_frames=len(bad),
                        first_overshoot_frame=bad[0] if bad else None, last_overshoot_frame=bad[-1] if bad else None,
                        initial_config_sha256=detail["initial_config_sha256"],
                        audio_challenge=detail["audio_challenge"], palette=detail["palette"],
                        transport=detail["transport"], error=detail.get("error"),
                        capture=json.loads((raw.parent / "capture.json").read_text()),
                        result_sha256=digest(session / "videoout-result.json"))
                    if detail["audio_challenge"] != [2,1,0,3] or detail["palette"] != [3,2,4,6]:
                        raise RuntimeError("Matched inputs were not applied")
                record.setdefault("failed", record["desktop_exit_code"] != 0)
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait(10)
                child.close()
            record["ended_utc"] = datetime.now(timezone.utc).isoformat()
            records.append(record)
            save()
            print(json.dumps({k:record.get(k) for k in ("version","iteration","failed","peak","overshoot_frames")}), flush=True)
    return int(any(record["failed"] for record in records))


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--shell-worker":
        raise SystemExit(shell_worker(Path(sys.argv[2]), Path(sys.argv[3])))
    raise SystemExit(main())
