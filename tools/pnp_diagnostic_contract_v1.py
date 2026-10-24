# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
"""Independent file-only HOST TEST lifecycle validation. No device/process APIs."""
import argparse
import json
from pathlib import Path
import pnp_coverage_v2 as native

SCHEMA = 'pnp-diagnostic-contract-v1'
STAGES = ('native_collection', 'capture_freeze', 'optional_replay', 'cleanup',
          'final_publication', 'scope_completion')
KINDS = {'devnodes', 'interfaces', 'lookup', 'properties', 'key'}
REASONS = {'none', 'clock', 'time', 'records', 'payload', 'events', 'capture',
           'replay', 'unknown', 'cleanup', 'writer'}
COMMON = set('schema origin sequence qpc event'.split())
FIELDS = {
    'header': set('frequency diagnostic_ms scan_ms record_cap payload_cap event_cap row_cap byte_cap '
                  'token_cap parent_cap depth_cap clock_domain native_internal_stages'.split()),
    'scope_start': set('begin deadline clock_valid'.split()),
    'stage_begin': set('id parent stage optional'.split()),
    'stage_end': set('id begin end elapsed_ticks clock_valid state reason'.split()),
    'call': set('ordinal kind threw'.split()),
    'fact': set('ordinal kind threw known'.split()),
    'native_result': set('frequency first_reason first_qpc ready coverage exception'.split()),
    'scope_end': set('begin end clock_valid'.split()),
    'footer': set('calls retained dropped events event_drops payload_bytes unknown first_diagnostic cleanup_ok '
                  'finalization_ok clock_valid diagnostic_complete self_close_measured recovery_accepted'.split()),
}
need, integer = native.need, native.integer


def boolean(v):
    need(type(v) is bool, 'Boolean required')


def load(path):
    path = Path(path)
    need(not str(path).endswith('.partial'), 'Unpublished partial output')
    with path.open('rb') as f:
        raw = f.read(1048577)
    need(raw and len(raw) <= 1048576 and raw.endswith(b'\n'), 'Empty/oversized/truncated contract')
    rows = [json.loads(line, object_pairs_hook=native.unique, parse_constant=native.bad_constant)
            for line in raw.decode('utf-8').splitlines()]
    need(rows and type(rows[0]) is dict and type(rows[0].get('byte_cap')) is int and
         len(raw) <= rows[0]['byte_cap'], 'Declared output byte cap')
    return rows


def validate(rows, native_rows=None, *, require_complete=True):
    need(type(rows) is list and 17 <= len(rows) <= 4096, 'Required lifecycle absent')
    last = 0
    for sequence, row in enumerate(rows):
        need(type(row) is dict, 'Contract row object')
        event = row.get('event')
        need(type(event) is str and event in FIELDS and set(row) == COMMON | FIELDS[event], 'Closed contract schema')
        need(row['schema'] == SCHEMA and row['origin'] == 'HOST TEST', 'Incompatible schema/origin')
        integer(row['sequence']); need(row['sequence'] == sequence, 'Sequence')
        integer(row['qpc']); need(row['qpc'] >= last, 'Clock reversed'); last = row['qpc']
    index = 0

    def take(event):
        nonlocal index
        need(index < len(rows) and rows[index]['event'] == event, 'Missing/out-of-order ' + event)
        r = rows[index]; index += 1
        return r

    h = take('header')
    for key, value in dict(diagnostic_ms=25, scan_ms=250, token_cap=128, parent_cap=8, depth_cap=32).items():
        integer(h[key]); need(h[key] == value, 'Policy changed')
    integer(h['frequency'], 0, 1000000000)
    integer(h['record_cap'], 0, 64); integer(h['payload_cap'], 0, 1048576)
    integer(h['event_cap'], 0, 4096); integer(h['row_cap'], 16, 4096); integer(h['byte_cap'], 4096, 1048576)
    need(len(rows) <= h['row_cap'], 'Declared row cap')
    need(h['clock_domain'] == 'host_test_ticks' and h['native_internal_stages'] == 'opaque', 'Unproven clock/internal instrumentation')
    start = take('scope_start'); boolean(start['clock_valid']); integer(start['begin']); integer(start['deadline'], -1)
    need(h['qpc'] == start['begin'] == start['qpc'], 'Scope start')
    valid = start['clock_valid']
    if valid:
        need(h['frequency'] > 0 and h['frequency'] % 40 == 0 and
             start['deadline'] == start['begin'] + h['frequency']//40 and start['deadline'] < 2**63, 'Shared deadline')
    else:
        need(start['deadline'] == -1, 'Invalid-clock uncertainty')
    calls, facts, ends = [], [], []
    proof = None
    prior_end = start['begin']
    for ident, stage in enumerate(STAGES, 1):
        a = take('stage_begin')
        integer(a['id'], 1, 6); integer(a['parent']); boolean(a['optional'])
        need(a['id'] == ident and a['parent'] == 0 and a['stage'] == stage and
             a['optional'] == (ident == 3) and a['qpc'] >= prior_end and
             (ident != 1 or a['qpc'] == start['begin']), 'Stage manifest/order/parent')
        if ident in (1, 2):
            event = 'call' if ident == 1 else 'fact'
            target = calls if ident == 1 else facts
            ordinal = 0
            while index < len(rows) and rows[index]['event'] == event:
                r = take(event); integer(r['ordinal'], 1); boolean(r['threw'])
                need(r['ordinal'] > ordinal and type(r['kind']) is str and r['kind'] in KINDS, 'Call/fact ordering or kind')
                if ident == 2:
                    boolean(r['known']); need(not r['threw'] or not r['known'], 'Thrown result cannot supply a fact')
                ordinal = r['ordinal']; target.append(r)
        b = take('stage_end')
        integer(b['id'], 1, 6); integer(b['begin']); integer(b['end']); integer(b['elapsed_ticks'], -1)
        boolean(b['clock_valid'])
        need(b['id'] == ident and b['begin'] == a['qpc'] and b['end'] == b['qpc'] >= b['begin'] and
             b['clock_valid'] == valid and b['elapsed_ticks'] == (b['end']-b['begin'] if valid else -1), 'Stage bracket/clock')
        need(type(b['reason']) is str and b['reason'] in REASONS, 'Unbounded reason')
        need(b['state'] in ('completed', 'failed', 'skipped', 'not_measurable'), 'Stage state')
        if not valid:
            need(b['state'] == 'not_measurable' and b['reason'] == 'clock', 'Clock uncertainty restored')
        elif b['state'] == 'completed':
            need(b['reason'] == 'none', 'Completed phase failed')
        elif b['state'] == 'skipped':
            need(ident == 3 and b['reason'] == 'time' and a['qpc'] >= start['deadline'], 'False optional skip')
        else:
            need(b['state'] == 'failed' and b['reason'] != 'none', 'Unjustified phase state')
        prior_end = b['end']; ends.append(b)
        if ident == 2:
            proof = take('native_result')
            need(proof['qpc'] == prior_end, 'Native freeze boundary')
    stop = take('scope_end'); footer = take('footer')
    need(index == len(rows), 'Data after terminal footer')
    integer(stop['begin']); integer(stop['end']); boolean(stop['clock_valid'])
    need(stop['begin'] == start['begin'] and stop['end'] == stop['qpc'] >= prior_end and stop['clock_valid'] == valid, 'Scope end')
    for key in ('calls','retained','dropped','events','event_drops','payload_bytes','unknown'):
        integer(footer[key])
    for key in ('cleanup_ok','finalization_ok','clock_valid','diagnostic_complete','self_close_measured','recovery_accepted'):
        boolean(footer[key])
    need(type(footer['first_diagnostic']) is str and footer['first_diagnostic'] in REASONS and footer['clock_valid'] == valid and
         not footer['self_close_measured'] and not footer['recovery_accepted'], 'Unproven acceptance/clock/final-write claim')
    need(footer['retained'] == len(facts) <= h['record_cap'] and footer['events'] == len(calls) <= h['event_cap'] and
         footer['calls'] == footer['retained']+footer['dropped'] == footer['events']+footer['event_drops'] and
         len(facts)+len(calls) <= footer['payload_bytes'] <= h['payload_cap'], 'Capture accounting')
    call_map = {r['ordinal']: r for r in calls}
    for r in calls + facts: need(r['ordinal'] <= footer['calls'], 'Unknown call ordinal')
    for r in facts:
        c = call_map.get(r['ordinal'])
        need((c is not None and (c['kind'], c['threw']) == (r['kind'], r['threw'])) or
             (c is None and footer['event_drops'] > 0), 'Fact/call binding')
    need(footer['unknown'] >= sum(not r['known'] for r in facts) or ends[2]['state'] != 'completed', 'Unknown facts suppressed')
    need(footer['cleanup_ok'] == (ends[3]['state'] == 'completed') or not valid, 'Cleanup state mismatch')
    need(footer['finalization_ok'] == (ends[4]['state'] == 'completed') or not valid, 'Finalization mismatch')
    integer(proof['frequency'], 1, 1000000000); integer(proof['first_reason'], 0, 9); integer(proof['first_qpc'])
    for key in ('ready','coverage','exception'): boolean(proof[key])
    need((proof['first_reason'] == 0) == (proof['first_qpc'] == 0), 'Native first-failure pair')
    bound = native_rows is not None
    if bound:
        native.validate(native_rows, allow_host_test=True, require_complete=False)
        need(native_rows[0]['origin'] == 'host-test', 'Native host evidence required')
        failure = next((r for r in native_rows if r['event'] == 'first_failure'), None)
        snapshots = [r for r in native_rows if r['event'] == 'snapshot']
        need(proof['frequency'] == native_rows[0]['qpc_frequency'] and
             proof['first_reason'] == (failure['reason'] if failure else 0) and
             proof['first_qpc'] == (failure['qpc'] if failure else 0) and
             proof['coverage'] == native_rows[-1]['coverage_complete'] and
             proof['ready'] == bool(snapshots and snapshots[-1]['initial_ready']), 'Native evidence changed')
        # A balanced lifecycle and fabricated zero capture cannot substantiate a
        # native snapshot. These are necessary lower bounds, not a claim to
        # recover private Provider IDs or an authenticated full call transcript.
        kinds = [r['kind'] for r in calls]
        property_min = sum(s['visited'] + sum(v['visited'] for v in s['interface_scans']) for s in snapshots)
        tokens = {r[k] for r in native_rows if r['event'] in ('devnode','interface','classification')
                  for k in ('token','root_token') if r[k]}
        if footer['diagnostic_complete']:
            need(kinds.count('devnodes') == len(snapshots) and kinds.count('interfaces') == 2*len(snapshots) and
                 kinds.count('properties') >= property_min and kinds.count('key') >= len(tokens), 'Native/capture inventory gap')
    complete = bool(bound and valid and footer['first_diagnostic'] == 'none' and not footer['dropped'] and
                    not footer['event_drops'] and not footer['unknown'] and footer['cleanup_ok'] and footer['finalization_ok'] and
                    not proof['exception'] and proof['coverage'] and not proof['first_reason'] and
                    footer['qpc'] < start['deadline'] and all(e['state'] == 'completed' for e in ends))
    need(footer['diagnostic_complete'] == complete, 'False diagnostic completeness')
    need((ends[5]['state'] == 'completed') == complete or not valid, 'Scope completion mismatch')
    need(complete or footer['first_diagnostic'] != 'none', 'Missing diagnostic failure')
    if require_complete: need(complete, 'Diagnostic evidence incomplete')
    return dict(schema=SCHEMA, diagnostic_complete=complete, native_bound=bound,
                native_first_reason=proof['first_reason'], first_diagnostic=footer['first_diagnostic'],
                calls=footer['calls'], retained=footer['retained'], recovery_accepted=False)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('contract', type=Path); p.add_argument('native', type=Path)
    p.add_argument('--allow-incomplete', action='store_true')
    a = p.parse_args()
    print(json.dumps(validate(load(a.contract), native.load(a.native), require_complete=not a.allow_incomplete), indent=2))


if __name__ == '__main__': main()
