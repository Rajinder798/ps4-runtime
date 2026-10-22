# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
"""Build separate arrival-v1 diagnostics against attested existing SDL. Never watches."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import live_av_v2_contract as contract
import run_homebrew_startup as startup

ROOT=Path(__file__).resolve().parents[1]
SOURCES=('tests/arrival_probe_v1.cpp','tests/arrival_windows_v1.cpp','tests/arrival_windows_v1.h',
         'tests/arrival_trace_v1.h','tests/dualsense_sdl_probe.cpp')
def source_hashes():
    return {p:hashlib.sha256((ROOT/p).read_bytes().replace(b'\r\n',b'\n')).hexdigest() for p in SOURCES}
def verify_probe(probe,engine,engine_report=None):
    metadata=json.loads((probe.parent/'arrival-build-v1.json').read_text())
    library=engine.parent/'externals/sdl3/SDL3-static.lib'
    if (metadata.get('schema')!='arrival-build-v1' or metadata['source_lf_sha256']!=source_hashes() or
        metadata['probe_sha256']!=startup.digest(probe) or metadata['engine_sha256']!=startup.digest(engine) or
        metadata['sdl_static_library_sha256']!=startup.digest(library) or
        metadata['build_script_sha256']!=startup.digest(Path(__file__)) or
        engine_report is not None and metadata['engine_report_sha256']!=startup.digest(engine_report)):
        raise ValueError('Independent arrival-v1 source/binary/engine/SDL attestation mismatch')
    if engine_report is not None:
        report=json.loads(engine_report.read_text())
        revision=next(s['revision'] for s in report['source_inventory']['submodules'] if s['path']=='externals/sdl3')
        if metadata.get('sdl_revision')!=revision:raise ValueError('Conflicting SDL revision attestation')
    return metadata
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('engine','engine-report','fixture','sdl-source','output'):parser.add_argument('--'+key,type=Path,required=True)
    args=parser.parse_args()
    contract.verify_inputs(args.engine,args.engine_report,args.fixture)
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=False)
    library=(args.engine.parent/'externals/sdl3/SDL3-static.lib').resolve(strict=True)
    report=json.loads(args.engine_report.read_text())
    pinned=next(s['revision'] for s in report['source_inventory']['submodules'] if s['path']=='externals/sdl3')
    actual=subprocess.check_output(['git','-C',str(args.sdl_source),'rev-parse','HEAD'],text=True).strip()
    if actual!=pinned or subprocess.check_output(['git','-C',str(args.sdl_source),'status','--porcelain'],text=True).strip():
        raise ValueError('SDL include source is not the clean attested pinned revision')
    objects=[]
    for name in ('arrival_probe_v1','arrival_windows_v1'):
        command=['clang-cl','/nologo','/std:c++20','/EHsc','/MD','/W4','/WX','/D_WIN32_WINNT=0x0A00',
                 '/I'+str(args.sdl_source.resolve()/'include'),'/c',str(ROOT/'tests'/f'{name}.cpp'),'/Fo'+str(output/f'{name}.obj')]
        result=subprocess.run(command,capture_output=True)
        (output/f'{name}.log').write_bytes(result.stdout+result.stderr)
        if result.returncode:raise RuntimeError(f'{name} compile failed; original log preserved')
        objects.append(str(output/f'{name}.obj'))
    command=['clang-cl','/nologo',*objects,'/Fe'+str(output/'arrival-probe-v1.exe'),'/link',str(library),
        'kernel32.lib','user32.lib','gdi32.lib','winmm.lib','imm32.lib','oleaut32.lib','ole32.lib','version.lib',
        'uuid.lib','advapi32.lib','setupapi.lib','shell32.lib','hid.lib','dinput8.lib','cfgmgr32.lib']
    result=subprocess.run(command,capture_output=True);(output/'link.log').write_bytes(result.stdout+result.stderr)
    if result.returncode:raise RuntimeError('Arrival link failed; original log preserved')
    metadata=dict(schema='arrival-build-v1',source_lf_sha256=source_hashes(),probe_sha256=startup.digest(output/'arrival-probe-v1.exe'),
        engine_sha256=startup.digest(args.engine),engine_report_sha256=startup.digest(args.engine_report),
        sdl_static_library_sha256=startup.digest(library),build_script_sha256=startup.digest(Path(__file__)),
        link_command=command,sdl_revision=pinned,live_execution_performed=False)
    (output/'arrival-build-v1.json').write_text(json.dumps(metadata,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(metadata))
if __name__=='__main__':main()
