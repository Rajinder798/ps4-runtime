# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
"""Build the read-only guard and an exact offline input bundle. Never starts observers."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from no_guest_coordinator_v1 import ROOT,digest,need,verify_bundle

SOURCES=('tools/no_guest_coordinator_v1.py','tools/no_guest_session_v1.py','tools/coordinator_windows_v1.py',
         'tools/build_no_guest_coordinator_v1.py','config/no-guest-coordinator-v1.json',
         'tests/no_guest_coordinator_v1/endpoint_clock_v1.cpp','tools/pnp_coverage_v2.py',
         'tools/arrival_diagnostics_v1.py','tools/boundary_cleanup_v2.py')


def protected_files():
    out={}
    def add(name,sha,size):
        name=Path(name).as_posix();p=ROOT/name
        need(p.stat().st_size==size and digest(p)==sha,'historical_input_changed')
        value=dict(sha256=sha,bytes=size)
        need(name not in out or out[name]==value,'conflicting_historical_hash');out[name]=value
    old=ROOT/'build/live-av-v2/pnp-sdl-boundary-001'
    for name,item in json.loads((old/'original-snapshot.json').read_text()).items():add(name,item['sha256'],item['bytes'])
    for folder in (old,ROOT/'build/live-av-v2/pnp-readiness-v2-001'):
        for item in json.loads((folder/'artifact-manifest.json').read_text())['artifacts']:
            add((folder/item['path']).relative_to(ROOT),item['sha256'],item['bytes'])
        name=(folder/'artifact-manifest.json').relative_to(ROOT)
        add(name,digest(ROOT/name),(ROOT/name).stat().st_size)
    return out


def build(output):
    output=output.absolute();need(output.is_relative_to(ROOT/'build') and not output.exists(),'fresh_build_output_required')
    inputs=protected_files();pins=json.loads((ROOT/'config/no-guest-coordinator-v1.json').read_text())
    for role in ('pnp','sdl'):
        for name,item in pins[role]['inputs'].items():
            need(digest(ROOT/name)==item['sha256'],'frozen_observer_changed');inputs[name]=item
    output.mkdir(parents=False,exist_ok=False)
    compiler=shutil.which('clang-cl');need(compiler is not None,'clang_cl_environment_required')
    binary=output/'endpoint-clock-v1.exe';source=ROOT/'tests/no_guest_coordinator_v1/endpoint_clock_v1.cpp'
    command=[compiler,'/nologo','/std:c++20','/EHsc','/MD','/W4','/WX',str(source),'/Fe'+str(binary),
             '/Fo'+str(output/'endpoint-clock-v1.obj'),'/link','ole32.lib','uuid.lib']
    result=subprocess.run(command,capture_output=True,timeout=90)
    (output/'build.log').write_bytes(result.stdout+result.stderr)
    need(result.returncode==0,'guard_build_failed')
    relative=binary.relative_to(ROOT).as_posix()
    metadata=dict(schema='endpoint-clock-build-v1',binary=relative,sha256=digest(binary),
        source_lf_sha256=hashlib.sha256(source.read_bytes().replace(b'\r\n',b'\n')).hexdigest(),
        compiler_sha256=digest(Path(compiler)),compile_command=command,live_execution_performed=False)
    meta=output/'endpoint-clock-build-v1.json';meta.write_text(json.dumps(metadata,indent=2)+'\n')
    for name in (*SOURCES,relative,meta.relative_to(ROOT).as_posix()):
        p=ROOT/name;inputs[name]=dict(sha256=digest(p),bytes=p.stat().st_size)
    bundle=dict(schema='no-guest-build-v1',origin='offline-build',inputs=inputs,
                executables=dict(pnp=pins['pnp']['path'],sdl=pins['sdl']['path'],endpoint=relative),
                guard_metadata=meta.relative_to(ROOT).as_posix(),
                source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip())
    path=output/'coordinator-build-v1.json';path.write_text(json.dumps(bundle,indent=2)+'\n')
    checksum=digest(path);verify_bundle(path,checksum)
    print(json.dumps(dict(bundle=path.relative_to(ROOT).as_posix(),sha256=checksum,inputs=len(inputs),live_initialized=False)))
    return path


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();build(args.output)
