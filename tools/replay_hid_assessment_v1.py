# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
"""File-only historical replay/preservation. No execution, device, audio or network API.

Writes only a fresh output file; all historical inputs are opened read-only.
The original guest rejection and readiness failures are asserted, never promoted.
"""
import argparse
import json
from pathlib import Path
import sys

import pnp_snapshot_v1 as snapshot
import pnp_coverage_v2 as original

ROOT=Path(__file__).resolve().parents[1]

def load(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))

def event(rows,name):
    return next(r for r in rows if r['event']==name)

def preserve(baseline):
    p=load(baseline)
    snapshot.need(p['schema']=='hid-list-assessment-preservation-v1','preservation_schema')
    snapshot.need(0<len(p['protected'])<=8192,'preservation_count')
    for name,row in p['protected'].items():
        path=snapshot.local_path(name)
        stat=path.stat()
        snapshot.need(snapshot.digest(path)==row['sha256'] and stat.st_size==row['bytes'] and
                      str(stat.st_mtime_ns)==row['mtime_ns'],'preserved_file_changed: '+name)
    bundle=ROOT/'build/live-av-v2/pnp-snapshot-harness-v1-001/bundle-final-17a4b95/snapshot-build-v1.json'
    b=snapshot.verify_bundle(bundle,'7553f13c8dc9367a4288aa6e70774e2833ec8820a35098e5c041f781a79dc96a')
    return dict(files=len(p['protected']),bundle_references=len(b['files']),frozen_inputs=len(b['protected_inputs']),
                exact_hash_size_mtime=True,sealed_sets=p['sealed_sets'],baseline_sha256=snapshot.digest(baseline))

def guest_replay():
    # Import only existing offline readers/oracles; never invoke their runners.
    import arrival_diagnostics_v1 as arrival
    import live_av_v2_evidence as evidence
    import run_homebrew_startup as startup
    session=ROOT/'build/live-av-v2/physical-arrival-recovery-001'
    prior=load(ROOT/'build/live-av-v2/physical-arrival-report-001/verification.json')
    native=arrival.load(session/'arrival-native-v1.jsonl')
    native_result=arrival.validate_native(native)
    samples=evidence.progress(startup.read_events(session/'guest/session/startup-audit.jsonl',final=True),allow_failure=True)['samples']
    journal=evidence.verify_records((session/'guest/session/user/data/live-av-v2.bin').read_bytes(),samples)
    witnesses=arrival.load(session/'arrival-guest-v1.jsonl')
    guest=arrival.validate_guest(witnesses,samples)
    strict=[json.loads(line) for line in (session/'native.jsonl').read_text(encoding='utf-8').splitlines()]
    boundaries=arrival.boundaries(native,witnesses,samples,strict)
    palette=(session/'guest/session/app/palette.bin').read_bytes()
    images=[evidence.verify_image(session/phase['path'],palette,samples[phase['sequence']]) for phase in prior['phases'] if 'path' in phase]
    snapshot.need(len(images)==6,'guest_original_images_changed')
    try:evidence.verify_physical(strict,samples,prior['phases'],[p['label'] for p in prior['phases']],prior['transport'],False)
    except ValueError as error:rejection=str(error)
    else:raise ValueError('historical_guest_failure_was_promoted')
    return dict(verdict='FAIL 6/9',strict_rejection=rejection,images_checked=len(images),
                native=native_result,journal=journal,witness=guest,boundaries=boundaries)

def replay():
    attempts=[]
    for name in ('pnp-v2-sdl-physical-001-review','pnp-v2-sdl-physical-002-review'):
        folder=ROOT/'build/live-av-v2'/name
        rows=original.load(folder/'session/pnp/pnp.jsonl')
        validation=original.validate(rows,require_complete=False)
        result=load(folder/'session/result.json')
        snapshot.need(result['status']=='FAILED' and validation['first_failure']==1,'no_guest_failure_changed')
        snapshot.need(not event(rows,'snapshot')['initial_ready'],'historical_readiness_promoted')
        attempts.append(dict(name=name,original=validation,snapshot=event(rows,'snapshot'),
                             original_first_failure=event(rows,'first_failure'),preserved_cleanup=result.get('cleanup')))
    for name in ('pnp-snapshot-physical-001-review','pnp-snapshot-connected-001-review'):
        folder=ROOT/'build/live-av-v2'/name
        inspected=snapshot.inspect_streams(folder/'session')
        result=load(folder/'session/result-v1.json')
        snapshot.need(inspected==result['inspection'] and not inspected['snapshot_ready'],'one_shot_failure_changed')
        attempts.append(dict(name=name,inspection=inspected,cleanup=result['cleanup']))
    connected=ROOT/'build/live-av-v2/pnp-snapshot-connected-001-review'
    rows=original.load(connected/'session/pnp-v2.jsonl')
    diag=[json.loads(line) for line in (connected/'session/rejection-v1.jsonl').read_text().splitlines()]
    s=event(rows,'snapshot');d=event(diag,'snapshot');frequency=rows[0]['qpc_frequency']
    of=event(rows,'first_failure');df=event(diag,'first_failure')
    timing=dict(original_scan_ms=(s['qpc_end']-s['qpc_begin'])*1000/frequency,
                diagnostic_scope_ms=(d['end']-d['begin'])*1000/frequency,
                failure_after_companion_begin_ms=(df['qpc']-d['begin'])*1000/frequency,
                publication_after_companion_begin_ms=(event(diag,'snapshot_begin')['qpc']-d['begin'])*1000/frequency,
                original_after_companion_failure_ms=(of['qpc']-df['qpc'])*1000/frequency)
    snapshot.need(d['details']==40 and d['omitted']==10 and timing['original_after_companion_failure_ms']==0.914,'connected_observations_changed')
    return dict(schema='hid-list-historical-replay-v1',origin='offline file replay; no live acquisition',
                attempts=attempts,connected_timing=timing,original_guest=guest_replay(),
                disconnected_operator_supplement='preserved separately; controller disconnected throughout; precondition unmet',
                connected_operator_confirmations=[load(connected/'operator-before.json'),load(connected/'operator-after.json')],
                raw_six_strings_available=False,omitted_ten_details_reconstructable=False,recovery_accepted=False)

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--preservation',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args(argv)
    snapshot.need(not args.output.exists(),'output_exists')
    preservation=preserve(args.preservation)
    result=replay();result['preservation']=preservation
    with args.output.open('x',encoding='utf-8',newline='\n') as f:json.dump(result,f,indent=2);f.write('\n')
    print(json.dumps(dict(preservation=preservation,guest_verdict=result['original_guest']['verdict'],
                          connected_timing=result['connected_timing'],live_queries=0),indent=2))
    return 0

if __name__=='__main__':sys.exit(main())
