# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later

"""Exercise the patched exception policy with actual Windows C++ throws/faults."""
import argparse
import json
from pathlib import Path
import subprocess

import research_contract

ROOT = Path(__file__).resolve().parents[1]


def run(source, output):
    contract = research_contract.verify(source)
    if not output.resolve().is_relative_to((ROOT / "build").resolve()):
        raise ValueError("Test output must stay under build/")
    output.mkdir(parents=True)  # Refuse stale evidence.
    executable = output / "host-exceptions.exe"
    with (output / "compiler.log").open("wb") as log:
        subprocess.run(["clang-cl", "/nologo", "/std:c++20", "/EHsc", "/MT", "/W4", "/WX",
                        "/I" + str(source / "src"), str(ROOT / "tests/host_exception_driver.cpp"),
                        "/Fe" + str(executable), "/Fo" + str(output / "driver.obj")],
                       check=True, stdout=log, stderr=subprocess.STDOUT, timeout=120)
    native = subprocess.run([str(executable), "native-unhandled"], capture_output=True, timeout=20,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    native_code = native.returncode & 0xffffffff
    if native_code not in (0xe06d7363, 0xc0000409, 0x40000015) or native.stdout or native.stderr:
        raise ValueError("Unexpected native uncaught C++ termination")
    expected = {
        "caught-host": (0, ["deferred", "caught=42"]),
        "caught-guest": (0, ["retained", "caught=42"]),
        "unhandled-host": (native_code, ["deferred"]),
        "unhandled-guest": (native_code, ["retained"]),
        "host-access-violation": (0xc0000005, ["retained"]),
    }
    cases = [dict(name="native-unhandled", exit_code=native_code, stdout=[], stderr="")]
    for name, (code, lines) in expected.items():
        process = subprocess.run([str(executable), name], capture_output=True, timeout=20,
                                 creationflags=subprocess.CREATE_NO_WINDOW)
        actual_code = process.returncode & 0xffffffff
        actual_lines = process.stdout.decode("ascii").splitlines()
        record = dict(name=name, exit_code=actual_code, stdout=actual_lines,
                      stderr=process.stderr.decode("utf-8", errors="replace"))
        cases.append(record)
        (output / (name + ".json")).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        if actual_code != code or actual_lines != lines or process.stderr:
            raise ValueError("Windows exception boundary failed: " + name)
    research_contract.verify(source)
    result = dict(schema_version=1, status="passed", cases=cases,
                  patch_sha256=contract["patch_sha256"], patched_tree=contract["expected_patched_tree"],
                  guest_fault_execution_tested=False, engine_shutdown_tested=False)
    (output / "host-exceptions.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.source.resolve(), args.output.resolve()), indent=2))
