# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
"""OFFLINE build-bundle assembly only. Does not run any observer or device API."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import pnp_snapshot_v1 as snapshot

ROOT=snapshot.ROOT
CONFIG=ROOT/'config/pnp-snapshot-v1.json'


def collect_protected(config):
    files={}
    def add(name,item):
        name=name.replace('\\','/')
        path=snapshot.local_path(name)
        value=dict(sha256=item['sha256'],bytes=item.get('bytes',item.get('size')))
        if 'mtime_ns' in item:value['mtime_ns']=item['mtime_ns']
        if name in files:
            snapshot.need(all(files[name].get(k,v)==v for k,v in value.items()),'conflicting_frozen_inputs')
            files[name].update(value)
        else:files[name]=value
        stat=path.stat()
        snapshot.need(stat.st_size==value['bytes'] and snapshot.digest(path)==value['sha256'],'protected_hash_changed')
        if 'mtime_ns' in value:
            snapshot.need(str(stat.st_mtime_ns)==value['mtime_ns'],'protected_mtime_changed')
    original=snapshot.local_path(config['protected_bundle']['path'])
    snapshot.need(snapshot.digest(original)==config['protected_bundle']['sha256'],'protected_bundle_changed')
    old=snapshot.load_json(original)
    snapshot.need(len(old['inputs'])==975,'original_input_count')
    for name,item in old['inputs'].items():add(name,item)
    add(config['protected_bundle']['path'],dict(sha256=snapshot.digest(original),bytes=original.stat().st_size))
    for group in config['preserved_manifests']:
        manifest=snapshot.local_path(group['path'])
        snapshot.need(snapshot.digest(manifest)==group['sha256'],'preserved_manifest_changed')
        add(group['path'],dict(sha256=group['sha256'],bytes=manifest.stat().st_size))
        data=snapshot.load_json(manifest)
        data=data.get('artifacts',data) if isinstance(data,dict) else data
        rows=data.items() if isinstance(data,dict) else ((r['path'],r) for r in data)
        count=0
        for name,item in rows:
            count+=1
            relative='/'.join(x for x in (group['base'],name.replace('\\','/')) if x)
            add(relative,item)
        snapshot.need(count==group['entries'],'preservation_entry_count')
    for name,expected in config['frozen_source_lf_sha256'].items():
        raw=snapshot.local_path(name).read_bytes().replace(b'\r\n',b'\n')
        snapshot.need(__import__('hashlib').sha256(raw).hexdigest()==expected,'frozen_source_changed')
    return files,sorted(old['inputs'])


def build(output,host,windows,toolchain):
    config=snapshot.load_json(CONFIG)
    files,protected=collect_protected(config)
    head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    snapshot.need(not subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip(),'uncommitted_source')
    sources=sorted(set(config['frozen_source_lf_sha256']) | set(subprocess.check_output(
        ['git','diff','--name-only',config['baseline'],head],cwd=ROOT,text=True).splitlines()))
    snapshot.need(sources and all(snapshot.local_path(n).is_file() for n in sources),'missing_source')
    output=Path(output).absolute()
    snapshot.need(output.resolve()==output and output.is_relative_to(ROOT),'bundle_output_scope')
    output.mkdir(exist_ok=False);(output/'bin').mkdir()
    def add(path):
        path=Path(path).resolve();name=path.relative_to(ROOT).as_posix()
        item=dict(sha256=snapshot.digest(path),bytes=path.stat().st_size)
        if name in files:snapshot.need(all(item[k]==files[name][k] for k in item),'protected_input_overwritten')
        else:files[name]=item
        return name
    for name in sources:add(ROOT/name)
    binaries={}
    for role,path in (('host',host),('windows',windows)):
        identity=json.loads(subprocess.check_output([str(Path(path).resolve()),'--identity-only'],text=True,timeout=5))
        snapshot.need(identity==dict(schema='pnp-snapshot-worker-v1',source_commit=head,device_queries=0),'worker_source_commit_mismatch')
        dest=output/'bin'/Path(path).name
        with Path(path).open('rb') as source,dest.open('xb') as target:shutil.copyfileobj(source,target)
        binaries[role]=add(dest)
    old=snapshot.load_json(snapshot.local_path(config['protected_bundle']['path']))
    binaries['original_pnp']=old['executables']['pnp']
    metadata=snapshot.load_json(toolchain,1024*1024)
    snapshot.need(metadata.get('source_commit')==head and all(metadata.get('binary_sha256',{}).get(role)==snapshot.digest(path)
        for role,path in (('host',host),('windows',windows))),'toolchain_build_identity')
    for path in metadata['inputs']:add(snapshot.local_path(path))
    toolchain_name=add(toolchain)
    value=dict(schema=snapshot.SCHEMA,origin='offline-build',source_commit=head,baseline=config['baseline'],
        files=files,sources=sources,executables=binaries,toolchain=toolchain_name,
        protected_inputs=protected,policies=snapshot.POLICIES)
    path=output/'snapshot-build-v1.json'
    with path.open('x',encoding='utf-8') as f:json.dump(value,f,indent=2)
    digest=snapshot.digest(path)
    snapshot.verify_bundle(path,digest)
    return dict(path=str(path),sha256=digest,source_commit=head,files=len(files),protected_inputs=len(protected),
                binaries={k:files[n]['sha256'] for k,n in binaries.items()})


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--host-binary',type=Path,required=True)
    parser.add_argument('--windows-binary',type=Path,required=True)
    parser.add_argument('--toolchain',type=Path,required=True)
    args=parser.parse_args()
    try:
        result=build(args.output,args.host_binary,args.windows_binary,args.toolchain)
        print(json.dumps(result));return 0
    except (OSError,ValueError,KeyError):
        print('Offline bundle rejected; preserve partial output. No execution attempted.');return 1

if __name__=='__main__':raise SystemExit(main())
