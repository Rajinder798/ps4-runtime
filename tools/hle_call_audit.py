# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Report which declared imports a real guest run entered, from an HLE call audit.

The diagnostic research engine variant (strict patch plus `hle-call-audit.patch`)
appends one `hle_first_call` event to the strict startup audit the first time each
registered HLE host-call wrapper is entered. This tool validates those events,
checks the remaining events with the existing strict-audit rules, and maps every
first call back to the program's declared imports.

Granularity is one host wrapper: an import is "entered" when the wrapper its
identity is registered at was entered, possibly through an alias sharing that
wrapper. An import that was not entered was not reached through its HLE wrapper
during this bounded run; that says nothing about other inputs or longer runs.
Objects (LIB_OBJ) are data and cannot be observed. Entering a function says
nothing about whether its implementation is correct or complete.

  report --imports FILE --audit FILE --profile NAME [--source DIR] [--json]
"""
import argparse
import json
from pathlib import Path
import sys

import engine_coverage
import run_homebrew_startup

PROFILES = ("hello-world", "service-roundtrip")
SYMBOL_KEYS = {"nid", "library", "module"}


def split(events):
    """Validate the variant's own events; return (strict events, ready event, first calls)."""
    ready, calls, rest = None, [], []
    previous, entered, seen = -1, False, set()
    for event in events:
        if (not isinstance(event, dict) or event.get("schema_version") != 1 or
                type(event.get("elapsed_us")) is not int or event["elapsed_us"] < previous):
            raise ValueError("Invalid or non-monotonic strict audit")
        previous = event["elapsed_us"]
        kind = event.get("event")
        if kind == "hle_call_audit":
            addresses, identities = event.get("registered_addresses"), event.get("registered_identities")
            if (ready is not None or entered or not rest or set(event) != {
                    "schema_version", "elapsed_us", "event", "registered_addresses", "registered_identities"} or
                    type(addresses) is not int or type(identities) is not int or not 0 < addresses <= identities):
                raise ValueError("Invalid or misplaced HLE call audit readiness event")
            ready = event
        elif kind == "hle_first_call":
            symbols = event.get("symbols")
            if (ready is None or set(event) != {"schema_version", "elapsed_us", "event", "symbols"} or
                    not isinstance(symbols, list)):
                raise ValueError("Invalid or misplaced HLE first-call event")
            identities = []
            for symbol in symbols:
                if (not isinstance(symbol, dict) or set(symbol) != SYMBOL_KEYS or
                        not all(isinstance(symbol[key], str) and symbol[key] for key in SYMBOL_KEYS)):
                    raise ValueError("Invalid HLE first-call symbol")
                identities.append((symbol["nid"], symbol["library"], symbol["module"]))
            if identities != sorted(set(identities)):
                raise ValueError("HLE first-call symbols are not unique and ordered")
            if seen.intersection(identities):
                raise ValueError("An HLE identity was first-called by two wrappers")
            seen.update(identities)
            calls.append({"elapsed_us": event["elapsed_us"], "after_guest_entry": entered,
                          "identities": identities})
        else:
            entered = entered or kind == "guest_entry"
            rest.append(event)
    if ready is None:
        raise ValueError("No HLE call audit readiness event; this is not the HLE call audit engine")
    return rest, ready, calls


def report(inventory, events, profile, names=None):
    if inventory.get("operation") != "imports" or inventory.get("schema_version") != 1:
        raise ValueError("Expected `ps4-runtime imports --json` output (schema 1)")
    if profile not in PROFILES:
        raise ValueError("Unknown fixture profile")
    names = names or {}
    rest, ready, calls = split(events)
    evidence = run_homebrew_startup.evaluate(rest, profile)
    if not evidence["guest_entry_observed"]:
        raise ValueError("The audit does not show strict guest entry")
    declared = {(entry["nid"], entry["library"], entry["module"]): entry for entry in inventory["imports"]}
    if len(declared) != len(inventory["imports"]):
        raise ValueError("Duplicate declared import identity")
    first, unattributed, undeclared = {}, [], []
    for call in calls:
        hits = [identity for identity in call["identities"] if identity in declared]
        if not call["identities"]:
            unattributed.append({key: call[key] for key in ("elapsed_us", "after_guest_entry")})
        elif not hits:
            undeclared.append({"elapsed_us": call["elapsed_us"], "after_guest_entry": call["after_guest_entry"],
                               "symbols": [{"nid": n, "name": names.get(n), "library": l, "module": m}
                                           for n, l, m in call["identities"]]})
        for identity in hits:
            first[identity] = call
    imports = []
    for identity, entry in declared.items():
        call = first.get(identity)
        imports.append({"nid": entry["nid"], "name": names.get(entry["nid"]), "library": entry["library"],
                        "module": entry["module"], "type": entry["type"],
                        "observable": entry["type"] == "function", "entered": call is not None,
                        "first_call_us": None if call is None else call["elapsed_us"],
                        "after_guest_entry": None if call is None else call["after_guest_entry"]})
    entered = [entry for entry in imports if entry["entered"]]
    return {"schema_version": 1, "operation": "hle_call_audit", "profile": profile,
            "guest_entry_observed": True, "markers_observed": evidence["markers_observed"],
            "registered_addresses": ready["registered_addresses"],
            "registered_identities": ready["registered_identities"],
            "first_call_events": len(calls), "imports": len(imports),
            "observable_imports": sum(entry["observable"] for entry in imports),
            "entered_count": len(entered),
            "entered_before_guest_entry": sum(not entry["after_guest_entry"] for entry in entered),
            "not_entered_count": len(imports) - len(entered),
            "unattributed_wrapper_entries": unattributed, "undeclared_entries": undeclared,
            "import_results": imports, "granularity": "first entry per registered HLE host-call wrapper",
            "implementation_correctness_tested": False}


def check_oracles(result, oracles):
    """Each oracle names alternative NIDs; one must be entered before its marker event."""
    by_nid = {entry["nid"]: entry for entry in result["import_results"]}
    outcomes = []
    for oracle in oracles:
        hits = [by_nid[nid]["first_call_us"] for nid in oracle["any_of"]
                if nid in by_nid and by_nid[nid]["entered"]]
        passed = bool(hits) and min(hits) < oracle["before_us"]
        outcomes.append({"oracle": oracle["name"], "passed": passed,
                         "first_call_us": min(hits) if hits else None, "before_us": oracle["before_us"]})
    return outcomes


def to_text(result):
    lines = [f"HLE call audit ({result['profile']}): {result['entered_count']} of "
             f"{result['observable_imports']} observable declared imports entered during this run"]
    for entry in result["import_results"]:
        mark = "entered" if entry["entered"] else ("object " if not entry["observable"] else "not entered")
        lines.append(f"  {mark:11} {entry['nid']} {entry['name'] or '(unknown name)'} {entry['library']}")
    lines.append(f"Unattributed wrapper entries: {len(result['unattributed_wrapper_entries'])}; "
                 f"undeclared identities entered: {len(result['undeclared_entries'])}")
    lines.append("One bounded run; entry is not implementation correctness.")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    show = commands.add_parser("report")
    show.add_argument("--imports", type=Path, required=True)
    show.add_argument("--audit", type=Path, required=True)
    show.add_argument("--profile", choices=PROFILES, required=True)
    show.add_argument("--source", type=Path, help="engine source, only for AeroLib names")
    show.add_argument("--json", action="store_true")
    args = parser.parse_args()
    names = engine_coverage.nid_names(args.source) if args.source else {}
    result = report(json.loads(args.imports.read_text(encoding="utf-8")),
                    run_homebrew_startup.read_events(args.audit, final=True), args.profile, names)
    sys.stdout.write(json.dumps(result, indent=2) + "\n" if args.json else to_text(result))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError) as error:
        sys.exit(f"hle call audit error: {error}")
