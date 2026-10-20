# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later

"""Link the opt-in observer to SDL from an already attested local research build.

Run in the existing research MSVC toolchain environment. No download, SDL/engine
rebuild, dependency pin change or binary redistribution is performed.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import run_homebrew_startup as startup

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', type=Path, required=True)
    parser.add_argument('--engine-report', type=Path, required=True)
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--engine-build', type=Path, required=True)
    parser.add_argument('--sdl-source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    startup.verify_inputs(args.engine.resolve(), args.engine_report.resolve(), args.fixture.resolve(), 'live-av')
    output = args.output.resolve(); output.mkdir(parents=True, exist_ok=False)
    library = (args.engine_build/'externals/sdl3/SDL3-static.lib').resolve(strict=True)
    source = ROOT/'tests/dualsense_sdl_probe.cpp'
    command = ['clang-cl', '/nologo', '/std:c++20', '/EHsc', '/MD', '/W4', '/WX',
               '/I'+str(args.sdl_source.resolve()/'include'), str(source),
               '/Fo'+str(output/'probe.obj'), '/Fe'+str(output/'dualsense-sdl-probe.exe'),
               '/link', str(library), 'kernel32.lib', 'user32.lib', 'gdi32.lib', 'winmm.lib', 'imm32.lib',
               'oleaut32.lib', 'ole32.lib', 'version.lib', 'uuid.lib', 'advapi32.lib',
               'setupapi.lib', 'shell32.lib', 'hid.lib', 'dinput8.lib', 'cfgmgr32.lib']
    result = subprocess.run(command, capture_output=True)
    (output/'build.log').write_bytes(result.stdout+result.stderr)
    if result.returncode: raise RuntimeError((result.stdout+result.stderr).decode('utf-8', errors='replace'))
    metadata = dict(command=command, sdl_static_library_sha256=startup.digest(library),
                    source_lf_sha256=hashlib.sha256(source.read_bytes().replace(b'\r\n',b'\n')).hexdigest(),
                    probe_sha256=startup.digest(output/'dualsense-sdl-probe.exe'),
                    engine_sha256=startup.digest(args.engine), engine_unchanged=True)
    (output/'build.json').write_bytes((json.dumps(metadata, indent=2)+'\n').encode('utf-8'))
    print(json.dumps(metadata))


if __name__ == '__main__': main()
