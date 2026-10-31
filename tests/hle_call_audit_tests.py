# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Check the HLE call audit header output, parser, report and contract without an engine."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import hle_call_audit
import run_hle_call_audit
import run_homebrew_startup

driver = sys.argv[1]


def check(condition, label):
    if not condition:
        raise AssertionError(label)


def rejects(action, text, label):
    try:
        action()
    except ValueError as error:
        check(text in str(error), f"{label}: {error}")
        return
    raise AssertionError(f"{label}: accepted")


def inventory(*entries):
    return {"schema_version": 1, "operation": "imports",
            "imports": [{"nid": nid, "library": "libkernel", "module": "libkernel", "type": kind, "bind": "global"}
                        for nid, kind in entries]}


def run_driver(directory, mode):
    trace = Path(directory) / f"{mode}.jsonl"
    completed = subprocess.run([driver, trace, mode], capture_output=True, text=True, timeout=20)
    check(completed.returncode == 0, f"driver {mode}: {completed.returncode} {completed.stderr}")
    return trace


with tempfile.TemporaryDirectory(prefix="hle-call-audit-") as directory:
    disabled = Path(directory) / "disabled.jsonl"
    check(subprocess.run([driver, disabled, "disabled"], timeout=20).returncode == 0 and not disabled.exists(),
          "an unconfigured audit must write nothing")
    events = run_homebrew_startup.read_events(run_driver(directory, "sleep"), final=True)

# The header's real output: ordered unique aliases, an unattributed wrapper, escaping.
calls = [e for e in events if e["event"] == "hle_first_call"]
check([c["symbols"] for c in calls] == [
    [{"nid": "writeAlias", "library": "libkernel", "module": "libkernel"},
     {"nid": "writeNid", "library": "libkernel", "module": "libkernel"}],
    [], [{"nid": "sleepNid", "library": "libkernel", "module": "libkernel"}]], f"first calls: {calls}")
ready = [e for e in events if e["event"] == "hle_call_audit"]
check(ready == [dict(ready[0], registered_addresses=3, registered_identities=4)], f"readiness: {ready}")

# The strict runner refuses this variant's events, so the engines cannot be swapped.
rejects(lambda: run_homebrew_startup.evaluate(events, "service-roundtrip"), "Unknown strict audit event",
        "strict evaluation of a variant audit")

declared = inventory(("writeNid", "function"), ("sleepNid", "function"), ("unusedNid", "function"),
                     ("guardNid", "object"))
result = hle_call_audit.report(declared, events, "service-roundtrip", {"writeNid": "write"})
by_nid = {entry["nid"]: entry for entry in result["import_results"]}
check(by_nid["writeNid"]["entered"] and by_nid["writeNid"]["name"] == "write" and
      by_nid["writeNid"]["after_guest_entry"] is True, "alias wrapper marks the declared import entered")
check(by_nid["sleepNid"]["entered"] and not by_nid["unusedNid"]["entered"], "entered and not entered")
check(not by_nid["guardNid"]["observable"] and not by_nid["guardNid"]["entered"], "objects are not observable")
check((result["entered_count"], result["observable_imports"], result["not_entered_count"],
       len(result["unattributed_wrapper_entries"]), result["undeclared_entries"],
       result["implementation_correctness_tested"]) == (2, 3, 2, 1, [], False), f"summary: {result}")
undeclared = hle_call_audit.report(inventory(("sleepNid", "function")), events, "service-roundtrip")
check([s["nid"] for s in undeclared["undeclared_entries"][0]["symbols"]] == ["writeAlias", "writeNid"],
      "an entered wrapper with no declared identity is reported, not dropped")

markers = {e["text"]: e["elapsed_us"] for e in events if e["event"] == "guest_output"}
begin, done = markers["service-roundtrip: begin"], markers["service-roundtrip: PASS threads=2 bytes=256 seek=128"]
outcomes = hle_call_audit.check_oracles(result, [
    {"name": "write before begin", "any_of": ["missingNid", "writeNid"], "before_us": begin},
    {"name": "sleep before begin", "any_of": ["sleepNid"], "before_us": begin},
    {"name": "sleep before done", "any_of": ["sleepNid"], "before_us": done},
    {"name": "never entered", "any_of": ["unusedNid"], "before_us": done}])
check([o["passed"] for o in outcomes] == [True, False, True, False], f"oracles: {outcomes}")

# Malformed or misplaced variant events.
configured, rest = events[0], events[1:]
ready_index = next(i for i, e in enumerate(events) if e["event"] == "hle_call_audit")
entry_index = next(i for i, e in enumerate(events) if e["event"] == "guest_entry")
first_call = events[entry_index + 1]
strict_only = [e for e in events if not e["event"].startswith("hle_")]
rejects(lambda: hle_call_audit.split(strict_only), "not the HLE call audit engine", "a strict-engine audit")
rejects(lambda: hle_call_audit.split([configured] + [events[ready_index]] * 2), "misplaced HLE call audit",
        "duplicate readiness")
late = [e for e in events if e["event"] != "hle_call_audit"]
late.insert(entry_index, dict(events[ready_index], elapsed_us=late[entry_index - 1]["elapsed_us"]))
rejects(lambda: hle_call_audit.split(late), "misplaced HLE call audit", "readiness after guest entry")
rejects(lambda: hle_call_audit.split([events[ready_index]]), "misplaced HLE call audit", "readiness first")
rejects(lambda: hle_call_audit.split([configured, dict(first_call, elapsed_us=configured["elapsed_us"])]),
        "misplaced HLE first-call", "first call before readiness")
rejects(lambda: hle_call_audit.split(events[:entry_index + 1] + [dict(first_call, extra=1)]),
        "Invalid or misplaced HLE first-call", "extra first-call field")
rejects(lambda: hle_call_audit.split(events[:entry_index + 1] + [
    dict(first_call, symbols=list(reversed(first_call["symbols"])))]), "unique and ordered", "unordered symbols")
rejects(lambda: hle_call_audit.split(events[:entry_index + 1] + [
    dict(first_call, symbols=[dict(first_call["symbols"][0], nid="")])]), "Invalid HLE first-call symbol",
    "empty identity")
rejects(lambda: hle_call_audit.split(events[:entry_index + 2] + [first_call]), "two wrappers",
        "identity first-called twice")
rejects(lambda: hle_call_audit.split(events[:entry_index + 1] + [dict(first_call, elapsed_us=0)]),
        "non-monotonic", "time going backwards")
rejects(lambda: hle_call_audit.split([configured, dict(events[ready_index], registered_addresses=5)]),
        "misplaced HLE call audit", "more addresses than identities")
unresolved = dict(configured, elapsed_us=events[ready_index]["elapsed_us"], event="unresolved", symbol="x",
                  library="l", module="m", reason="r")
rejects(lambda: hle_call_audit.report(declared, events[:ready_index + 1] + [unresolved], "service-roundtrip"),
        "Unresolved import", "strict rules still apply to the remaining events")
rejects(lambda: hle_call_audit.report(declared, events[:entry_index], "service-roundtrip"),
        "strict guest entry", "no guest entry")
rejects(lambda: hle_call_audit.report(declared, events, "audio-pattern"), "Unknown fixture profile",
        "only the G2 profiles")
rejects(lambda: hle_call_audit.report({"operation": "imports", "schema_version": 2}, events, "service-roundtrip"),
        "schema 1", "foreign inventory")

# The committed contract matches the committed patch, header and strict research inputs.
contract = run_hle_call_audit.load_contract()
check(len(contract["expected_tree"]) == 40 and contract["base"]["expected_patched_tree"] !=
      contract["expected_tree"], "variant tree is pinned and differs from the strict tree")
check(set(contract["oracles"]) == set(hle_call_audit.PROFILES) and
      all(o["any_of"] and o["before_marker"] for p in contract["oracles"].values() for o in p),
      "every G2 profile has independent oracles")
with tempfile.TemporaryDirectory(prefix="hle-call-audit-engine-") as directory:
    engine = Path(directory) / "shadPS4.exe"
    engine.write_bytes(b"not an engine")
    report = dict(contract["base"], status="hle_call_audit_engine_built",
                  hle_call_audit_patch_sha256=contract["patch_sha256"],
                  hle_call_audit_header_sha256=contract["header_sha256"], patched_tree=contract["expected_tree"],
                  executable_sha256=run_homebrew_startup.digest(engine))
    report.pop("expected_patched_tree")
    path = Path(directory) / "build.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    check(run_hle_call_audit.verify_engine(engine, path)[0] == report, "matching build evidence")
    for key, value in (("executable_sha256", "0" * 64), ("patched_tree", contract["base"]["expected_patched_tree"]),
                       ("status", "strict_engine_built"), ("patch_sha256", "0" * 64)):
        path.write_text(json.dumps(dict(report, **{key: value})), encoding="utf-8")
        rejects(lambda: run_hle_call_audit.verify_engine(engine, path), "does not match", f"tampered {key}")

print("hle call audit contract: passed")
