# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Per-title save persistence across launches through the title save store (step 3).

Three bounded launches share one fresh store:

  A  save_roundtrip as PRTS00001: writes the save; host verify_save, then commit.
  B  save_readback  as PRTS00001: staged from the store, must read it back (PASS).
  C  save_readback  as PRTS00002: staged from its own empty store, must fail at
     "mount existing", and no save may appear anywhere.

Each launch reuses the save runner's strict-audit rules, session preparation and
supervision. See docs/title-save-store.md.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import platform
import secrets
import shutil
import subprocess
import sys

import psf
import run_homebrew_startup as startup
import run_save_roundtrip as save
import title_save_store as store

ROOT = Path(__file__).resolve().parents[1]
READER_MARKERS = ("save-readback: begin", "save-readback: PASS bytes=256 existing=1 search=1")
READER_FAILURE = "save-readback: FAIL"
OTHER_TITLE = "PRTS00002"
ISOLATION_FAILURE = READER_FAILURE + " mount existing"


def verify_reader(fixture):
    contract = json.loads((ROOT / "config/save-readback.json").read_text())
    if (contract["schema_version"] != 1 or
            startup.digest(ROOT / "research/homebrew/save_readback/main.cpp") != contract["source_sha256"]):
        raise ValueError("Reviewed read-back fixture source checksum mismatch")
    if startup.digest(fixture) != contract["oelf_sha256"]:
        raise ValueError("Read-back fixture hash differs from the selected build")


def stage_app(work, fixture, name, title, challenge):
    """Fresh app mount: the verified fixture, a minimal param.sfo for title and the shared challenge."""
    app = work / "app"
    (app / "sce_sys").mkdir(parents=True)
    staged = app / name
    shutil.copyfile(fixture, staged)
    (app / "sce_sys/param.sfo").write_bytes(psf.write(
        {"TITLE_ID": title, "TITLE": "PS4 Runtime save persistence fixture", "APP_VER": "01.00"}))
    (app / "challenge.bin").write_bytes(challenge)
    return staged


def launch(*, engine, supervisor, work, staged, markers, failure, timeout, expect_failure=None):
    """One supervised launch. Stops on the PASS marker, or on the guest's first failure line."""
    trace = work / "startup-audit.jsonl"
    command = [engine, "--game", staged, "--ignore-game-patch", "--startup-audit", trace]

    def failure_text(events):
        return next((e["text"] for e in events if isinstance(e, dict) and e.get("event") == "guest_output"
                     and isinstance(e.get("text"), str) and e["text"].startswith(failure)), None)

    def poll():
        events = startup.read_events(trace)
        if failure_text(events) is not None:
            return True
        return save.evaluate(events, markers, failure)["markers_observed"]

    transport = startup.supervise(supervisor, command, work, timeout, poll)
    events = startup.read_events(trace, final=True)
    guest_failure = failure_text(events)
    # Strict rules still apply to everything else, so judge the trace without the failure line.
    evidence = save.evaluate([e for e in events if guest_failure is None or not (
        isinstance(e, dict) and e.get("event") == "guest_output" and e.get("text") == guest_failure)], markers, failure)
    outcome = dict(command=list(map(str, command)), transport=transport, guest_failure=guest_failure,
                   trace_sha256=startup.digest(trace), **evidence)
    if transport.get("reason") != "requested" or not evidence["guest_entry_observed"] or transport.get("tree_cleanup") is not True:
        raise ValueError("Launch did not reach guest entry with a requested, cleaned-up stop")
    if expect_failure is None:
        if guest_failure is not None or not evidence["markers_observed"]:
            raise ValueError(f"Expected a guest PASS; got {guest_failure or 'no PASS marker'}")
    elif guest_failure is None or not guest_failure.startswith(expect_failure) or evidence["markers_observed"]:
        raise ValueError(f"Expected guest failure '{expect_failure}'; got {guest_failure or 'PASS'}")
    return outcome


def fresh_session(output, case):
    """A new case folder with the save runner's usual empty session homes."""
    (output / case).mkdir()
    work = output / case / "session"
    startup.prepare_session(work)
    return work


def snapshot(root):
    root = Path(root)
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()} if root.exists() else {}


def saves_in(work):
    return sorted(str(p.relative_to(work)) for p in (work / "user/home").glob("*/savedata/*"))


def run_persistence(*, engine, engine_report, writer, reader, supervisor, output, timeout=30, variant=None):
    """Run in a caller-created empty output directory; return (exit code, evidence)."""
    if not math.isfinite(timeout) or not 3 <= timeout <= 120 or any(output.iterdir()):
        raise ValueError("A valid timeout and empty output directory are required")
    result = {"schema_version": 1, "status": "failed", "passed": False, "profile": "save-persist",
              "title_id": save.TITLE_ID, "other_title_id": OTHER_TITLE, "guest_execution_tested": False,
              "host": platform.platform(), "cpu": platform.processor(), "timeout_seconds": timeout,
              "launches": {}, "upstream_redistribution_approved": False}
    if variant is not None:
        result["variant"] = variant
    code = 1
    state = output / "store"
    try:
        if sys.platform != "win32" or platform.machine().lower() not in ("amd64", "x86_64"):
            raise ValueError("Research runner requires Windows x86-64")
        engine, writer, reader, supervisor = (p.resolve(strict=True) for p in (engine, writer, reader, supervisor))
        result["build"] = save.verify_inputs(engine, engine_report.resolve(strict=True), writer, variant=variant)
        verify_reader(reader)
        result.update(engine_sha256=startup.digest(engine), writer_sha256=startup.digest(writer),
                      reader_sha256=startup.digest(reader), supervisor_sha256=startup.digest(supervisor))
        vulkan = shutil.which("vulkaninfo")
        if not vulkan:
            raise ValueError("vulkaninfo is required to record the graphics host")
        diagnostics = subprocess.run([vulkan, "--summary"], capture_output=True, timeout=10, check=False,
                                     **startup.background_process_options())
        (output / "vulkan-summary.txt").write_bytes(diagnostics.stdout + diagnostics.stderr)
        if diagnostics.returncode:
            raise ValueError("Vulkan host diagnostic failed; see vulkan-summary.txt")
        challenge = secrets.token_bytes(256)
        result["challenge_sha256"] = hashlib.sha256(challenge).hexdigest()
        common = dict(engine=engine, supervisor=supervisor, timeout=timeout)

        # A: the writer stores the save in a fresh session, then the store keeps it.
        work = fresh_session(output, "a-write")
        record = result["launches"]["a-write"] = {"staged": store.stage(state, save.TITLE_ID, work)}
        if record["staged"]["users"]:
            raise ValueError("A fresh store must not stage any save for the first launch")
        staged = stage_app(work, writer, "save_roundtrip.oelf", save.TITLE_ID, challenge)
        record.update(launch(**common, work=work, staged=staged, markers=save.MARKERS, failure=save.FAILURE))
        result["guest_execution_tested"] = True
        record["save"] = save.verify_save(work, challenge)
        record["committed"] = store.commit(state, save.TITLE_ID, work)
        if record["committed"]["users"] != [record["save"]["user_id"]]:
            raise ValueError("The store did not keep exactly the verified save")
        committed = snapshot(state / "titles" / save.TITLE_ID)

        # B: a fresh session of the same title, staged from the store, reads it back.
        work = fresh_session(output, "b-same-title")
        record = result["launches"]["b-same-title"] = {"staged": store.stage(state, save.TITLE_ID, work)}
        if record["staged"]["users"] != result["launches"]["a-write"]["committed"]["users"]:
            raise ValueError("The stored save was not staged for the same title")
        staged = stage_app(work, reader, "save_readback.oelf", save.TITLE_ID, challenge)
        record.update(launch(**common, work=work, staged=staged, markers=READER_MARKERS, failure=READER_FAILURE))
        record["save"] = save.verify_save(work, challenge)
        if snapshot(state / "titles" / save.TITLE_ID) != committed:
            raise ValueError("The store changed without a commit")

        # C: another title, staged from its own empty store, must not find the save.
        work = fresh_session(output, "c-other-title")
        record = result["launches"]["c-other-title"] = {"staged": store.stage(state, OTHER_TITLE, work)}
        if record["staged"]["users"]:
            raise ValueError("Another title's store must start empty")
        staged = stage_app(work, reader, "save_readback.oelf", OTHER_TITLE, challenge)
        record.update(launch(**common, work=work, staged=staged, markers=READER_MARKERS, failure=READER_FAILURE,
                             expect_failure=ISOLATION_FAILURE))
        record["save_folders_after"] = saves_in(work)
        if any(save.TITLE_ID in path or save.DIRECTORY in path for path in record["save_folders_after"]):
            raise ValueError("The first title's save became visible to another title")
        result["store_after"] = {"titles": sorted(p.name for p in (state / "titles").iterdir()),
                                 save.TITLE_ID: committed}
        result.update(status="passed", passed=True)
        code = 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        result["error"] = str(error)
    finally:
        (output / "persist-result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return code, result


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for name in ("engine", "engine-report", "writer", "reader", "supervisor"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="New research directory")
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--variant", help="Engine variant name (e.g. release-no-libressl)")
    args = parser.parse_args()
    if not math.isfinite(args.timeout) or not 3 <= args.timeout <= 120:
        parser.error("--timeout must be finite and between 3 and 120 seconds")
    output = args.output.resolve()
    try:
        output.mkdir(parents=True, exist_ok=False)
    except OSError as error:
        parser.error(f"--output must be a new writable directory: {error}")
    code, result = run_persistence(engine=args.engine, engine_report=args.engine_report, writer=args.writer,
                                   reader=args.reader, supervisor=args.supervisor, output=output, timeout=args.timeout,
                                   variant=args.variant)
    print(json.dumps({k: result.get(k) for k in ("status", "error")}, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
