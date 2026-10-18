# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Compile/run real FFmpeg and patched AJM AAC host tests, not guest audio tests."""
import argparse
import json
from pathlib import Path
import subprocess

import research_contract as inputs

ROOT = Path(__file__).resolve().parents[1]


def run(source, binary, output):
    contract = inputs.verify(source)
    if not output.resolve().is_relative_to((ROOT / "build").resolve()):
        raise ValueError("Test output must stay under build/")
    output.mkdir(parents=True) # Fresh tests; no stale result reuse.
    ffmpeg = source / "externals/ffmpeg-core"
    audit = json.loads((ROOT / "config/ffmpeg-audit.json").read_text())
    if subprocess.check_output(["git", "-C", str(ffmpeg), "rev-parse", "HEAD"]).decode().strip() != audit["wrapper"]["revision"]:
        raise ValueError("Unexpected FFmpeg source")
    if subprocess.check_output(["git", "-C", str(ffmpeg), "status", "--porcelain"]).strip():
        raise ValueError("Unreviewed FFmpeg header changes")
    libraries = binary / "externals/ffmpeg-94dde08/lib"
    links = []
    for name in ("avcodec", "avutil", "swresample"):
        path = libraries / (name + ".lib")
        if inputs.digest(path) != audit["libraries"][name]["sha256"]:
            raise ValueError("Unexpected AAC library bytes")
        links.append(str(path))
    links += ["ole32.lib", "user32.lib", "bcrypt.lib"]
    common = ["clang-cl", "/nologo", "/std:c++20", "/EHsc", "/MT", "/W4", "/WX",
              "/DFMT_HEADER_ONLY", "/I" + str(ROOT / "research/shadps4"),
              "/I" + str(source / "src"), "/I" + str(ffmpeg / "include"),
              "/I" + str(source / "externals/ext-boost"),
              "/I" + str(binary / "_deps/fmt-src/include"), "/I" + str(ROOT / "tests")]
    with (output / "compiler.log").open("wb") as log:
        def command(args):
            subprocess.run(args, check=True, stdout=log, stderr=subprocess.STDOUT, timeout=120)
        command([*common, str(ROOT / "tests/aac_decoder_driver.cpp"),
                 "/Fe" + str(output / "backend.exe"), "/Fo" + str(output / "backend.obj"),
                 "/link", *links])
        command([*common, "/c", str(ROOT / "tests/ajm_aac_driver.cpp"),
                 "/Fo" + str(output / "driver.obj")])
        command([*common, "/c", str(source / "src/core/libraries/ajm/ajm_aac.cpp"),
                 "/Fo" + str(output / "adapter.obj")])
        command(["clang-cl", "/nologo", "/MT", str(output / "driver.obj"),
                 str(output / "adapter.obj"), "/Fe" + str(output / "adapter.exe"), "/link", *links])
    results = {}
    for name in ("backend", "adapter"):
        report = json.loads(subprocess.check_output([str(output / (name + ".exe"))], timeout=30))
        if report.get("status") != "passed" or report.get("guest_audio_tested") is not False:
            raise ValueError("AAC test result failed")
        results[name] = report
    inputs.verify(source)
    result = dict(schema_version=1, status="passed", **results,
                  aac_header_sha256=contract["aac_header_sha256"], guest_audio_tested=False)
    (output / "aac-tests.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--build", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.source.resolve(), args.build.resolve(), args.output.resolve()), indent=2))
