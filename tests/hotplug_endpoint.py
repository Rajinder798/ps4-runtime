# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
"""Approved alternate hotplug-only endpoint evidence, not the old strict contract."""
import json
from pathlib import Path
from muted_endpoint import MutedEndpoint

def validate_rows(rows):
    if len(rows)<3 or rows[-1].get('event')!='summary' or rows[-1].get('status')!='passed':
        raise RuntimeError('Incomplete hotplug endpoint observation')
    samples=rows[:-1];baseline={};last_ms=-1;previous=None;changes=0;previous_count=0
    for s in samples:
        if s.get('schema_version')!=1 or s.get('event')!='sample' or type(s['elapsed_ms']) is not int or s['elapsed_ms']<last_ms:
            raise RuntimeError('Invalid endpoint clock/schema')
        last_ms=s['elapsed_ms'];selected=s['default_token'];endpoints=s['endpoints']
        if (type(selected) is not int or not 1<=len(endpoints)<=4 or
            any(type(r['token']) is not int for r in endpoints) or
            [r['token'] for r in endpoints]!=list(range(len(endpoints))) or len(endpoints)<len(baseline) or
            len(endpoints) not in (previous_count,previous_count+1) or
            (len(endpoints)>previous_count and selected!=len(endpoints)-1) or
            selected not in range(len(endpoints)) or type(s['default_changed']) is not bool or
            s['default_changed']!=(previous is not None and previous!=selected)):
            raise RuntimeError('Endpoint identities/transition record invalid')
        if s['default_changed']:changes+=1
        for r in endpoints:
            token=r['token']
            if type(r['available']) is not bool or type(r['device_state']) is not int:
                raise RuntimeError('Invalid endpoint availability')
            if r['available']:
                v=r['volume']
                if r['device_state']!=1 or r['muted'] is not True or type(v) not in (int,float) or not 0<=v<=1 or r['same_device_volume'] is not True:
                    raise RuntimeError('Endpoint unmuted or volume changed')
                if token not in baseline:baseline[token]=v
                if baseline[token]!=v:raise RuntimeError('Endpoint per-device volume changed')
            elif (token==selected or token not in baseline or r['device_state']==1 or
                  r['muted'] is not None or r['volume'] is not None or r['same_device_volume'] is not None):
                raise RuntimeError('Absent/default endpoint falsely presented as muted')
        previous=selected;previous_count=len(endpoints)
    final=rows[-1]
    if (any(type(final.get(k)) is not int for k in ('samples','default_changes','endpoint_identities')) or
        final.get('schema_version')!=1 or final.get('samples')!=len(samples) or
        final.get('default_changes')!=changes or final.get('endpoint_identities')!=len(baseline)):
        raise RuntimeError('Endpoint summary mismatch')
    return dict(status='passed',protocol='separately approved hotplug endpoint tracking',samples=len(samples),
        duration_ms=last_ms,default_changes=changes,endpoint_identities=len(baseline),per_endpoint_volume=baseline,
        every_available_tracked_endpoint_muted=True,system_settings_changed=False,
        observation='Read-only polling of every seen default endpoint; unavailable endpoints recorded honestly. Between-sample changes and unrelated endpoints are not qualified.')

def validate_report(path):
    p=Path(path)
    if p.stat().st_size>32*1024*1024:raise RuntimeError('Endpoint evidence exceeds bounded size')
    return validate_rows([json.loads(s) for s in p.read_text(encoding='utf-8').splitlines()])
