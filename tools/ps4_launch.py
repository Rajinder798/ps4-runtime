# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Versioned local launch interface for the two verified research homebrew fixtures."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import re
import sys
import tempfile
import uuid

import run_homebrew_startup as research

PROFILES = ("hello-world", "service-roundtrip")
CONFIG_NAME = "launch-config.json"
MAX_CONFIG_BYTES = 65536


class LaunchError(Exception):
    def __init__(self, code, message, exit_code=3):
        super().__init__(message)
        self.code, self.exit_code = code, exit_code


def object_without_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def read_config(home):
    try:
        path = home / CONFIG_NAME
        if path.stat().st_size > MAX_CONFIG_BYTES:
            raise ValueError("Configuration exceeds size limit")
        config = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=object_without_duplicates)
        validate_config(config)
        return config
    except FileNotFoundError as error:
        raise LaunchError("not_registered", "Register the local engine and supported fixtures first.") from error
    except (OSError, ValueError, TypeError) as error:
        raise LaunchError("invalid_config", "Launch configuration is invalid or unsupported; register again explicitly.") from error


def validate_config(config):
    if (not isinstance(config, dict) or set(config) != {"schema_version", "engine", "engine_report", "supervisor", "fixtures"} or
            type(config["schema_version"]) is not int or config["schema_version"] != 1):
        raise ValueError("Unsupported configuration schema")
    fixtures = config["fixtures"]
    if not isinstance(fixtures, dict) or not fixtures or not set(fixtures) <= set(PROFILES):
        raise ValueError("Only the reviewed fixture IDs are supported")
    for item in [config[k] for k in ("engine", "engine_report", "supervisor")] + list(fixtures.values()):
        if (not isinstance(item, dict) or set(item) != {"path", "sha256"} or
                not isinstance(item["path"], str) or "\0" in item["path"] or not Path(item["path"]).is_absolute() or
                not isinstance(item["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"])):
            raise ValueError("Invalid registered input")


def input_record(path):
    path = path.resolve(strict=True)
    if not path.is_file():
        raise ValueError("Registered input must be a file")
    return dict(path=str(path), sha256=research.digest(path))


def check_inputs(config, title):
    if title not in config["fixtures"]:
        raise LaunchError("unsupported_title", "This fixture is not registered. Only the two reviewed homebrew IDs are supported.")
    items = {key: config[key] for key in ("engine", "engine_report", "supervisor")}
    items["fixture"] = config["fixtures"][title]
    try:
        for item in items.values():
            if not Path(item["path"]).is_file() or research.digest(item["path"]) != item["sha256"]:
                raise ValueError("Missing or changed registered input")
        paths = {key: Path(item["path"]) for key, item in items.items()}
        research.verify_inputs(paths["engine"], paths["engine_report"], paths["fixture"], title)
        return paths
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        raise LaunchError("input_verification_failed", "Registered inputs or the pinned research contract changed; rebuild/verify and register again.", 4) from error


def register(home, engine, engine_report, supervisor, fixtures, replace=False):
    try:
        config = dict(schema_version=1, engine=input_record(engine), engine_report=input_record(engine_report),
                      supervisor=input_record(supervisor), fixtures={k: input_record(v) for k, v in fixtures.items()})
        validate_config(config)
        for title in fixtures:
            check_inputs(config, title)
        home.mkdir(parents=True, exist_ok=True)
        # A complete temporary file is published atomically. First registration
        # cannot overwrite a concurrent registration; replacement is explicit.
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=home, delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(config, stream, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            if replace:
                os.replace(temporary, home / CONFIG_NAME)
            else:
                os.link(temporary, home / CONFIG_NAME)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()
        return config
    except FileExistsError as error:
        raise LaunchError("already_registered", "Registration already exists; use --replace to update it explicitly.") from error
    except LaunchError:
        raise
    except (OSError, ValueError, TypeError) as error:
        raise LaunchError("registration_failed", "Could not verify or persist the local registration.") from error


def supported_host():
    return sys.platform == "win32" and platform.machine().lower() in ("amd64", "x86_64")


def launch(home, title):
    response = dict(schema_version=1, operation="launch", title=title, status="failed", session_id=None,
                    logs_directory=None, engine_launch_attempted=False, guest_entry_observed=False,
                    guest_execution_tested=False, tree_cleanup=None, upstream_redistribution_approved=False)
    session = None
    try:
        config = read_config(home)
        paths = check_inputs(config, title)
        if not supported_host():
            raise LaunchError("unsupported_host", "The research engine requires Windows x86-64.", 4)
        session_id = uuid.uuid4().hex
        candidate = home / "sessions" / session_id
        candidate.mkdir(parents=True, exist_ok=False)
        session = candidate
        response.update(session_id=session_id, logs_directory=str(session),
                        started_at=datetime.now(timezone.utc).isoformat())
        code, evidence = research.run_attempt(**paths, output=session, profile=title)
        response.update(engine_launch_attempted=evidence["engine_launch_attempted"],
                        guest_entry_observed=evidence["guest_entry_observed"],
                        guest_execution_tested=evidence["guest_execution_tested"],
                        tree_cleanup=evidence.get("transport", {}).get("tree_cleanup"))
        if code:
            attempted = response["engine_launch_attempted"]
            raise LaunchError("guest_failed" if attempted else "prerequisite_failed",
                              "The fixture did not complete its verified observation; see session logs.", 5 if attempted else 4)
        response.update(status="completed", completion="fixture_observed_and_stopped")
        exit_code = 0
    except LaunchError as error:
        response["error"] = dict(code=error.code, message=str(error))
        exit_code = error.exit_code
    except (OSError, ValueError, TypeError, KeyError) as error:
        response["error"] = dict(code="session_failed", message="Could not create or complete the launch session.")
        exit_code = 6
    if session is not None:
        try:
            (session / "launch-result.json").write_text(json.dumps(response, indent=2) + "\n", encoding="utf-8")
        except OSError:
            response.update(status="failed", error=dict(code="session_failed", message="Could not persist the launch result."))
            exit_code = 6
    return exit_code, response


def default_home():
    if os.environ.get("PS4_RUNTIME_HOME"):
        return Path(os.environ["PS4_RUNTIME_HOME"])
    if os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "PS4Runtime"
    return Path.home() / ".local/share/ps4-runtime"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, default=default_home())
    operations = parser.add_subparsers(dest="operation", required=True)
    setup = operations.add_parser("register", help="Verify and persist paths once; does not execute a guest")
    for name in ("engine", "engine-report", "supervisor"):
        setup.add_argument("--" + name, type=Path, required=True)
    for name in PROFILES:
        setup.add_argument("--" + name, type=Path)
    setup.add_argument("--replace", action="store_true")
    setup.add_argument("--json", action="store_true")
    run = operations.add_parser("launch", help="Run one registered supported fixture in a fresh bounded session")
    run.add_argument("title")
    run.add_argument("--json", action="store_true")
    args = parser.parse_args()
    home = args.state_dir.resolve()
    if args.operation == "register":
        fixtures = {name: getattr(args, name.replace("-", "_")) for name in PROFILES
                    if getattr(args, name.replace("-", "_")) is not None}
        if not fixtures:
            parser.error("register requires --hello-world and/or --service-roundtrip")
        try:
            register(home, args.engine, args.engine_report, args.supervisor, fixtures, args.replace)
            code, response = 0, dict(schema_version=1, operation="register", status="registered",
                                    titles=sorted(fixtures), configuration=str(home / CONFIG_NAME))
        except LaunchError as error:
            code, response = error.exit_code, dict(schema_version=1, operation="register", status="failed",
                                                  error=dict(code=error.code, message=str(error)))
    else:
        code, response = launch(home, args.title)
    if args.json:
        print(json.dumps(response, ensure_ascii=True))
    elif code:
        print("error[" + response["error"]["code"] + "]: " + response["error"]["message"], file=sys.stderr)
        if response.get("logs_directory"):
            print("Session logs: " + response["logs_directory"], file=sys.stderr)
    else:
        print("Registered: " + ", ".join(response["titles"]) if args.operation == "register"
              else "Completed " + args.title + "; session logs: " + response["logs_directory"])
    return code


if __name__ == "__main__":
    sys.exit(main())
