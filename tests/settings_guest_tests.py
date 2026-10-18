# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Opt-in real guest evidence for persisted settings, inheritance and existing links."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from run_homebrew_startup import digest
from shortcut_guest_tests import activate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("engine", "engine-report", "supervisor", "hello-world", "service-roundtrip", "helper", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--settings-ui", action="store_true", help="Make preference changes through real Tk window controls")
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("Windows is required")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    state = output / "state"
    def call(*arguments, expected=0):
        result = subprocess.run([sys.executable, str(ROOT / "tools/ps4_launch.py"), "--state-dir", str(state),
            *map(str, arguments), "--json"], capture_output=True, text=True, timeout=150)
        if result.returncode != expected or result.stderr:
            raise RuntimeError(f"CLI failure ({result.returncode}): {result.stdout} {result.stderr}")
        return json.loads(result.stdout)
    call("register", "--engine", args.engine, "--engine-report", args.engine_report, "--supervisor", args.supervisor,
         "--hello-world", args.hello_world, "--service-roundtrip", args.service_roundtrip)
    registration_hash = digest(state / "launch-config.json")
    links = {title: Path(call("shortcut", title, "--directory", output / "links", "--helper", args.helper)["shortcut"])
             for title in ("hello-world", "service-roundtrip")}
    def link_metadata(link):
        return json.loads(subprocess.check_output([str(args.helper.resolve()), "inspect", str(link)], encoding="utf-8", timeout=15))
    original_links = {title: link_metadata(path) for title, path in links.items()}
    def change(action, level=None, title=None):
        if not args.settings_ui:
            arguments = ["settings", action]
            if level is not None:
                arguments.extend(["log_level", level])
            if title is not None:
                arguments.extend(["--title", title])
            call(*arguments)
            return
        import tkinter as tk
        from ps4_settings import SettingsWindow, LEVELS
        # Reopen for each update to exercise persistence, not a cached UI model.
        root = tk.Tk()
        try:
            window = SettingsWindow(root, state, title)
            root.update()
            if action == "set":
                window.level.current(LEVELS.index(level.title()) + 1)
                window.level.event_generate("<<ComboboxSelected>>")
                root.update()
                window.save_button.invoke()
            else:
                window.reset_button.invoke()
            root.update()
            if not window.status.get().startswith("Saved."):
                raise RuntimeError("Settings window did not save: " + window.status.get())
        finally:
            root.destroy()
    cases = []
    def observe(title, level, source, shell=False):
        if shell:
            before = set((state / "desktop-results").glob("*.json")) if (state / "desktop-results").exists() else set()
            activate(links[title])
            fresh = set((state / "desktop-results").glob("*.json")) - before
            if len(fresh) != 1:
                raise RuntimeError("Expected one desktop response")
            response = json.loads(fresh.pop().read_text())
        else:
            response = call("launch", title)
        if (response["status"] != "completed" or response["guest_entry_observed"] is not True or
                response["tree_cleanup"] is not True or response["effective_settings"] != {"log_level": level} or
                response["settings_sources"] != {"log_level": source}):
            raise RuntimeError("Missing guest/settings/cleanup evidence")
        session = Path(response["logs_directory"])
        evidence = json.loads((session / "startup-result.json").read_text())
        if evidence["g2_passed"] is not True:
            raise RuntimeError("Strict guest observation failed")
        engine_config = json.loads((session / "session/user/config.json").read_text())
        if engine_config["Log"]["filter"] != "*:" + level:
            raise RuntimeError("Engine did not retain the requested filter")
        log = session / "session/user/log/shad_log.txt"
        text = log.read_text(encoding="utf-8")
        counts = {name.lower(): len(re.findall("<" + name + ">", text)) for name in ("Debug", "Info", "Warning")}
        if counts["warning"] == 0 or (level == "warning" and (counts["debug"] or counts["info"])):
            raise RuntimeError("Warning filter did not have its expected runtime effect")
        if level in ("debug", "info") and not counts["info"]:
            raise RuntimeError("Expected info diagnostics missing")
        if (level == "info" and counts["debug"]) or (level == "debug" and not counts["debug"]):
            raise RuntimeError("Debug/info filter did not have its expected runtime effect")
        cases.append(dict(title=title, log_level=level, source=source, activation="shell" if shell else "cli",
            session_id=response["session_id"], guest_entry_observed=True, tree_cleanup=True,
            log_level_counts=counts, log_sha256=digest(log), trace_sha256=digest(session / "session/startup-audit.jsonl"),
            marker_interval_us=evidence["marker_interval_us"], service_roundtrip=evidence.get("service_roundtrip")))

    defaults = call("settings", "show")
    if defaults["effective_settings"] != {"log_level": "info"} or (state / "settings.json").exists():
        raise RuntimeError("Absent settings did not preserve defaults")
    observe("hello-world", "info", "default")
    change("set", "warning")
    observe("hello-world", "warning", "global", shell=True)
    change("set", "debug", "hello-world")
    observe("hello-world", "debug", "title")
    observe("service-roundtrip", "warning", "global", shell=True)
    change("reset", title="hello-world")
    observe("hello-world", "warning", "global")
    change("reset")
    observe("service-roundtrip", "info", "default", shell=True)
    if digest(state / "launch-config.json") != registration_hash:
        raise RuntimeError("Settings changed runtime registration")
    if {title: link_metadata(path) for title, path in links.items()} != original_links:
        raise RuntimeError("Settings changed shortcut launch properties")
    valid_preferences = (state / "settings.json").read_bytes()
    invalid = b'{"schema_version":2,"global":{},"titles":{}}'
    (state / "settings.json").write_bytes(invalid)
    rejected = call("launch", "hello-world", expected=3)
    if rejected["error"]["code"] != "invalid_settings" or rejected["engine_launch_attempted"] is not False or rejected["session_id"] is not None:
        raise RuntimeError("Invalid preferences were not rejected before execution")
    if len({case["session_id"] for case in cases}) != 6 or len(list((state / "sessions").iterdir())) != 6:
        raise RuntimeError("Expected six unique guest sessions and no rejected-request session")
    call("settings", "reset", "--all", expected=3)
    if (state / "settings.json").read_bytes() != invalid:
        raise RuntimeError("Future preference format was overwritten")
    (state / "settings.json").write_bytes(valid_preferences)
    summary = dict(schema_version=1, status="passed", guest_execution_tested=True, cases=cases,
                   preference_updates="tk_controls" if args.settings_ui else "cli",
                   registration_unchanged=True, shortcut_properties_unchanged=True,
                   invalid_settings_rejected_before_execution=True, future_settings_preserved=True,
                   upstream_redistribution_approved=False)
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
