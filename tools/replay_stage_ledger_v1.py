# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
"""File-only preservation and historical replay for the host-only ledger task.

The old production Python gate is reported separately from file preservation.
No runtime identity is substituted and no runner/device adapter is invoked.
"""
import argparse
import json
from pathlib import Path
import sys
import pnp_snapshot_v1 as snapshot
import replay_hid_assessment_v1 as historical

def verify(baseline):
    pre=json.loads(Path(baseline).read_text(encoding='utf-8-sig'))
    snapshot.need(pre['schema']=='stage-ledger-preservation-v1','preservation_schema')
    snapshot.need(pre['legacy_protected_files']==3602 and len(pre['protected'])<=8192,'preservation_count')
    for name,row in pre['protected'].items():
        path=snapshot.local_path(name);stat=path.stat()
        snapshot.need(stat.st_size==row['bytes'] and str(stat.st_mtime_ns)==row['mtime_ns'] and
                      snapshot.digest(path)==row['sha256'],'preserved_file_changed: '+name)
    bundle=snapshot.ROOT/'build/live-av-v2/pnp-snapshot-harness-v1-001/bundle-final-17a4b95/snapshot-build-v1.json'
    expected='7553f13c8dc9367a4288aa6e70774e2833ec8820a35098e5c041f781a79dc96a'
    snapshot.need(snapshot.digest(bundle)==expected,'bundle_changed')
    production_gate='passed'
    try:data=snapshot.verify_bundle(bundle,expected)
    except ValueError as error:
        if str(error)!='python_identity_changed':raise
        # verify_bundle checked every reference before this independent external
        # interpreter check. Do not label the failed production gate a pass.
        data=json.loads(bundle.read_text(encoding='utf-8'));production_gate=str(error)
    snapshot.need(len(data['files'])==3293 and len(data['protected_inputs'])==975,'bundle_counts')
    return dict(schema='stage-ledger-preservation-result-v1',protected_files=len(pre['protected']),
                legacy_files=3602,bundle_references=3293,frozen_inputs=975,all_hash_size_mtime_unchanged=True,
                production_runtime_gate=production_gate,production_gate_passed=production_gate=='passed',
                current_python_sha256=snapshot.digest(Path(sys.executable)),
                expected_python_sha256=pre['expected_python_sha256'],no_repinning=True)

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--preservation',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args(argv);snapshot.need(not args.output.exists(),'fresh_output_required')
    preservation=verify(args.preservation)
    # This function only reads native streams/guest records/images; unlike the
    # older CLI's preserve(), it does not hide or bypass the runtime gate above.
    result=historical.replay();result['ledger_preservation']=preservation
    with args.output.open('x',encoding='utf-8',newline='\n') as f:json.dump(result,f,indent=2);f.write('\n')
    print(json.dumps(dict(preservation=preservation,guest_verdict=result['original_guest']['verdict'],
                          connected_snapshot='FAILED exit 1; original readiness false',new_device_queries=0),indent=2))
    return 0

if __name__=='__main__':sys.exit(main())
