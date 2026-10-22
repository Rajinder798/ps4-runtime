# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
"""Offline pnp-coverage-v1 validation. Never grants physical recovery acceptance."""
import argparse
import json
from pathlib import Path

SCHEMA = 'pnp-coverage-v1'
MAX_BYTES = 8 * 1024 * 1024
NOT_QUERIED = 2**32 - 1
COMMON = {'schema', 'sequence', 'qpc', 'event'}
DETAIL = set('outcome role token root_token key_code root_key_code root_hardware root_hardware_code '
             'root_enumerator_code bus hardware hardware_code compatible_code composite enumerator_code '
             'parent_code ancestry_code depth ancestry_complete present root_present status_code started status problem '
             'enumerator_valid hardware_valid compatible_valid resource_limited'.split())
FIELDS = {
    'header': set('origin clock process_id qpc_frequency byte_cap row_cap period_ms scan_budget_ms node_cap interface_cap '
                  'relevant_cap token_cap parent_cap queue_cap property_bytes max_duration_ms'.split()),
    'session': {'duration_ms', 'qpc_begin'},
    'registration': {'interface', 'code'},
    'unregistration': {'interface', 'code'},
    'receipt': {'receipt', 'received_qpc', 'interface', 'action', 'payload_valid'},
    'classification': DETAIL | set('receipt qpc_begin qpc_end lookup_attempted lookup_code detail_code '
                                  'interface_code cleanup_code interface_flags'.split()),
    'drain': {'qpc_begin', 'qpc_end', 'processed', 'over_budget'},
    'snapshot_begin': {'sample', 'qpc_begin'},
    'devnode': DETAIL | {'sample', 'interface', 'interface_flags', 'detail_code'},
    'interface': DETAIL | {'sample', 'interface', 'interface_flags', 'detail_code'},
    'snapshot': set('sample qpc_begin qpc_end devnode_code devnode_cleanup_code devnode_terminal_code devnode_limit_hit devnode_enumeration_complete '
                    'visited intended unmatched indeterminate usb_parents hid_children not_started roots active_usb '
                    'active_hid inactive_interfaces interface_indeterminate interface_unmatched resource_failures ambiguous over_budget cadence_late coverage_complete '
                    'presence interface_scans errors classification_failures'.split()),
    'queue': {'processed', 'dropped', 'malformed', 'counts'},
    'stopped': {'qpc_begin', 'qpc_end', 'stop_requested'},
    'first_failure': {'reason'},
    'cleanup': {'code'},
    'summary': {'collection_complete', 'coverage_complete', 'cleanup_ok', 'recovery_accepted'},
}
BOOLS = set('composite enumerator_valid hardware_valid compatible_valid resource_limited ancestry_complete payload_valid lookup_attempted devnode_limit_hit devnode_enumeration_complete ambiguous cadence_late '
            'over_budget coverage_complete stop_requested collection_complete cleanup_ok recovery_accepted'.split())
STRINGS = {'schema', 'event', 'origin', 'clock', 'interface', 'outcome', 'role', 'bus', 'hardware', 'root_hardware', 'presence'}
ARRAYS = {'interface_scans', 'errors', 'counts', 'classification_failures'}
HARDWARE = {'target_usb_parent', 'target_usb_function', 'target_hid', 'unmatched', 'missing', 'malformed'}


def need(value, message):
    if not value:
        raise ValueError(message)


def integer(value, low=0, high=2**63-1):
    need(type(value) is int and low <= value <= high, 'Invalid integer or range')


def unique(pairs):
    out = {}
    for key, value in pairs:
        need(key not in out, 'Duplicate JSON field')
        out[key] = value
    return out


def bad_constant(_):
    raise ValueError('Non-finite JSON value')


def load(path):
    with Path(path).open('rb') as source:
        raw = source.read(MAX_BYTES + 1)
    need(raw and len(raw) <= MAX_BYTES and raw.endswith(b'\n'), 'Oversized/empty/truncated PnP evidence')
    rows = [json.loads(line, object_pairs_hook=unique, parse_constant=bad_constant)
            for line in raw.decode('utf-8').splitlines()]
    need(rows and type(rows[0]) is dict and type(rows[0].get('byte_cap')) is int and
         len(raw) <= rows[0]['byte_cap'], 'Declared byte cap exceeded')
    return rows


def validate(rows, *, allow_host_test=False, require_complete=True):
    need(type(rows) is list and rows, 'Missing PnP evidence')
    need(len(rows) <= 20000, 'Row cap exceeded')
    receipts, classified, snapshots, begins, details = {}, {}, [], {}, {}
    registrations, unregistrations = {}, {}
    queue = summary = session = stopped = cleanup = None
    failures, gaps, disagreements = [], [], []
    previous = previous_received = 0
    drain_processed = 0
    drains_complete = True
    header = rows[0]
    need(type(header) is dict and header.get('event') == 'header', 'Header must be first')
    for i, r in enumerate(rows):
        need(type(r) is dict and r.get('event') in FIELDS, 'Unknown PnP event')
        event = r['event']
        need(set(r) == COMMON | FIELDS[event] and r['schema'] == SCHEMA, 'PnP schema mismatch')
        integer(r['sequence'])
        need(r['sequence'] == i, 'Sequence mismatch')
        integer(r['qpc'], 1)
        need(r['qpc'] >= previous, 'Publication clock reversed')
        previous = r['qpc']
        for key, value in r.items():
            if key in BOOLS:
                need(type(value) is bool, 'Boolean required')
            elif key in STRINGS:
                need(type(value) is str, 'Enum string required')
            elif key in ARRAYS:
                need(type(value) is list, 'Array required')
            else:
                integer(value, -1 if key in {'present', 'root_present', 'started', 'problem'} else 0)
                if key.endswith('_code') or key in {'code', 'status', 'interface_flags'}:
                    integer(value, 0, NOT_QUERIED)
        if event == 'header':
            need(i == 0, 'Repeated header')
            need(r['origin'] in ('live', 'host-test') and (allow_host_test or r['origin'] == 'live'), 'Host tests are not physical evidence')
            need(r['clock'] in ('qpc', 'steady') and (r['origin'] != 'live' or r['clock'] == 'qpc'), 'Live Windows QPC required')
            integer(r['process_id'], 1, 2**32-1)
            integer(r['qpc_frequency'], 1, 10**12)
            integer(r['byte_cap'], 4096, MAX_BYTES)
            integer(r['row_cap'], 8, 20000)
            need(len(rows) <= r['row_cap'], 'Declared row cap exceeded')
            for key, value in dict(period_ms=2000, scan_budget_ms=250, node_cap=2048, interface_cap=2048,
                                   relevant_cap=64, token_cap=128, parent_cap=8, queue_cap=256,
                                   property_bytes=16384, max_duration_ms=360000).items():
                need(r[key] == value, 'Unknown coverage limits')
        elif event == 'session':
            need(session is None and i == 1, 'Invalid session placement')
            integer(r['duration_ms'], 1000, 360000)
            need(header['qpc'] <= r['qpc_begin'] <= r['qpc'], 'Invalid session clock')
            session = r
        elif event in ('registration', 'unregistration'):
            need(r['interface'] in ('usb', 'hid'), 'Unknown notification class')
            table = registrations if event == 'registration' else unregistrations
            need(r['interface'] not in table, 'Repeated notification lifecycle')
            table[r['interface']] = r['code']
            if event == 'unregistration':
                need(registrations.get(r['interface']) == 0, 'Unregister without successful registration')
        elif event == 'receipt':
            need(r['interface'] in ('usb', 'hid', 'unknown') and r['action'] in (0, 1, 2), 'Invalid receipt metadata')
            integer(r['receipt'], 1)
            need(r['receipt'] not in receipts, 'Repeated receipt')
            need(header['qpc'] <= r['received_qpc'] <= r['qpc'] and
                 r['received_qpc'] >= previous_received, 'Callback clock reversed or outside observation')
            previous_received = r['received_qpc']
            receipts[r['receipt']] = r
        elif event == 'classification':
            ident = r['receipt']
            need(ident in receipts and ident not in classified, 'Classification without unique receipt')
            receipt = receipts[ident]
            need(r['lookup_attempted'] == receipt['payload_valid'], 'Lookup attempt not accounted')
            need(receipt['qpc'] <= r['qpc_begin'] <= r['qpc_end'] <= r['qpc'], 'Invalid property lookup bracket')
            if not r['lookup_attempted'] or r['lookup_code'] or r['interface_code']:
                need(r['outcome'] == 'indeterminate', 'Failed lookup classified as identity')
            classified[ident] = r
        elif event == 'drain':
            need(header['qpc'] <= r['qpc_begin'] <= r['qpc_end'] <= r['qpc'], 'Invalid drain bracket')
            integer(r['processed'], 1, 256)
            need(r['over_budget'] == (1000*(r['qpc_end']-r['qpc_begin']) > 250*header['qpc_frequency']), 'Incorrect drain overhead')
            drain_processed += r['processed']
            need(drain_processed == len(classified), 'Drain receipt accounting mismatch')
            drains_complete &= not r['over_budget']
        elif event == 'snapshot_begin':
            need(r['sample'] == len(begins)+1 and r['sample'] not in begins, 'Snapshot order mismatch')
            need(header['qpc'] <= r['qpc_begin'] <= r['qpc'], 'Invalid snapshot begin')
            begins[r['sample']] = r
            details[r['sample']] = []
        elif event in ('devnode', 'interface'):
            need(r['sample'] in begins and r['sample'] == len(begins) and
                 r['sample'] > len(snapshots), 'Detail outside active snapshot')
            need(r['outcome'] == 'intended', 'Unrelated devnode identity must be redacted to counts')
            need(r['interface'] in (('other',) if event == 'devnode' else ('usb', 'hid')), 'Invalid detail class')
            details[r['sample']].append(r)
            need(len(details[r['sample']]) <= 64, 'Relevant record budget exceeded')
            if event == 'devnode':
                need(r['present'] == 1, 'Present-set devnode must be present')
        elif event == 'snapshot':
            sample = r['sample']
            need(sample in begins and sample == len(snapshots)+1, 'Snapshot end mismatch')
            need(r['qpc_begin'] == begins[sample]['qpc_begin'] and
                 begins[sample]['qpc'] <= r['qpc_end'] <= r['qpc'], 'Invalid snapshot bracket')
            need(r['qpc_end']-r['qpc_begin'] >= 0, 'Snapshot clock reversed')
            integer(r['visited'], 0, 2048)
            need(r['intended']+r['unmatched']+r['indeterminate'] == r['visited'], 'Devnode classification counts disagree')
            need(r['ambiguous'] == (r['roots'] > 1), 'Candidate ambiguity missing')
            need(r['over_budget'] == (1000*(r['qpc_end']-r['qpc_begin']) > 250*header['qpc_frequency']), 'Overhead incorrectly labelled')
            late = bool(snapshots and 1000*(r['qpc_begin']-snapshots[-1]['qpc_begin']) > 2350*header['qpc_frequency'])
            need(r['cadence_late'] == late, 'Missing cadence overhead')
            need(r['presence'] == ('qualifying_nodes' if r['intended'] else
                                  'no_qualifying_node' if r['coverage_complete'] else 'unknown'), 'Incomplete enumeration represented as absence')
            need(len(r['interface_scans']) == 2 and all(type(s) is dict for s in r['interface_scans']) and
                 {s.get('interface') for s in r['interface_scans']} == {'usb', 'hid'}, 'Missing interface coverage')
            interface_gap = False
            for s in r['interface_scans']:
                need(type(s) is dict and set(s) == {'interface', 'code', 'cleanup_code', 'terminal_code', 'limit_hit', 'complete', 'visited'}, 'Interface scan schema mismatch')
                integer(s['code'], 0, NOT_QUERIED); integer(s['cleanup_code'], 0, NOT_QUERIED); integer(s['visited'], 0, 2048)
                integer(s['terminal_code'], 0, NOT_QUERIED)
                need(type(s['complete']) is bool and type(s['limit_hit']) is bool, 'Interface coverage flag required')
                if s['complete']: need(s['terminal_code'] == 259 and not s['limit_hit'] and not s['code'], 'Invalid interface enum completion')
                interface_gap |= bool(s['code'] or s['cleanup_code'] or not s['complete'] or s['limit_hit'])
            need(len(r['errors']) <= 32, 'Error histogram budget exceeded')
            for e in r['errors']:
                need(type(e) is dict and set(e) == {'api', 'code', 'count'} and
                     e['api'] in {'hardware', 'enumerator', 'ancestry', 'status', 'interface_detail'}, 'Error histogram schema mismatch')
                integer(e['code'], 1, NOT_QUERIED); integer(e['count'], 1, 6144)
            need(len(r['classification_failures']) <= 8, 'Classification histogram budget exceeded')
            reasons = set()
            for e in r['classification_failures']:
                need(type(e) is dict and set(e) == {'reason', 'count'} and e['reason'] in {
                    'resource_limit', 'enumerator_unavailable', 'enumerator_malformed', 'hardware_unavailable',
                    'hardware_missing', 'hardware_malformed', 'ancestry_unresolved', 'interface_lookup_failed'} and
                    e['reason'] not in reasons, 'Classification failure schema mismatch')
                reasons.add(e['reason']); integer(e['count'], 1, 6144)
            need(sum(e['count'] for e in r['classification_failures']) == r['indeterminate']+r['interface_indeterminate'], 'Missing classification failure outcomes')
            if r['devnode_enumeration_complete']: need(r['devnode_terminal_code'] == 259 and not r['devnode_limit_hit'] and not r['devnode_code'], 'Invalid devnode enum completion')
            if r['coverage_complete']:
                need(not any((r['devnode_code'], r['devnode_cleanup_code'], not r['devnode_enumeration_complete'],
                              r['indeterminate'], r['interface_indeterminate'], r['resource_failures'], r['ambiguous'], r['over_budget'], r['cadence_late'], interface_gap,
                              r['errors'], r['devnode_limit_hit'])), 'Incomplete snapshot claims complete coverage')
                node_rows = [d for d in details[sample] if d['event'] == 'devnode']
                interface_rows = [d for d in details[sample] if d['event'] == 'interface']
                need(len(node_rows) == r['intended'] and
                     sum(d['role'] == 'usb_parent' for d in node_rows) == r['usb_parents'] and
                     sum(d['role'] in ('hid_child', 'related_hid') for d in node_rows) == r['hid_children'], 'Relevant devnode counts mismatch')
                need(len({d['root_token'] for d in details[sample]}) == r['roots'], 'Root count mismatch')
                need(sum(d['interface'] == 'usb' and bool(d['interface_flags'] & 1) for d in interface_rows) == r['active_usb'] and
                     sum(d['interface'] == 'hid' and bool(d['interface_flags'] & 1) for d in interface_rows) == r['active_hid'] and
                     sum(not (d['interface_flags'] & 1) for d in interface_rows) == r['inactive_interfaces'], 'Interface counts mismatch')
                need(r['active_usb']+r['active_hid']+r['inactive_interfaces']+r['interface_unmatched'] == sum(s['visited'] for s in r['interface_scans']), 'Interface classification accounting mismatch')
                need(all(d['token'] and d['root_token'] and not d['status_code'] for d in details[sample]), 'Unknown relevant properties claim complete coverage')
            if snapshots:
                gaps.append((r['qpc_begin']-snapshots[-1]['qpc_begin'])/header['qpc_frequency'])
            # These are observation disagreements, including possible enumeration races.
            # They are never promoted to a cause, physical absence or recovery verdict.
            for ident, c in classified.items():
                lower = snapshots[-1]['qpc_end'] if snapshots else 0
                if r['coverage_complete'] and not r['intended'] and c['outcome'] == 'intended' and receipts[ident]['action'] == 0 and lower < c['qpc_end'] <= r['qpc_begin']:
                    disagreements.append({'sample': sample, 'receipt': ident, 'kind': 'arrival_then_no_qualifying_node'})
            for d in details[sample]:
                if d['event'] == 'interface' and d['interface_flags'] & 1 and d['present'] == 0:
                    disagreements.append({'sample': sample, 'token': d['token'], 'kind': 'active_interface_node_not_present'})
            snapshots.append(r)
        elif event == 'queue':
            need(queue is None and len(r['counts']) == 9, 'Invalid queue accounting')
            for n in r['counts']: integer(n)
            need(r['processed'] == len(receipts) and sum(r['counts']) == r['processed']+r['dropped'], 'Callbacks silently lost')
            actual = [0]*9
            for receipt in receipts.values():
                index = {'usb': 0, 'hid': 1, 'unknown': 2}[receipt['interface']]*3+receipt['action']
                actual[index] += 1
            need(all(total >= count for total, count in zip(r['counts'], actual)), 'Class/action accounting mismatch')
            need(r['malformed'] == sum(not n['payload_valid'] for n in receipts.values()), 'Malformed accounting mismatch')
            queue = r
        elif event == 'first_failure':
            need(not failures and cleanup is None, 'First failure overwritten or recorded after cleanup')
            integer(r['reason'], 1, 9)
            failures.append(r)
        elif event == 'stopped':
            need(stopped is None and session and r['qpc_begin'] == session['qpc_begin'] and
                 r['qpc_begin'] <= r['qpc_end'] <= r['qpc'], 'Invalid stop clock')
            stopped = r
        elif event == 'cleanup':
            need(cleanup is None, 'Repeated cleanup')
            cleanup = r
        elif event == 'summary':
            need(i == len(rows)-1 and cleanup, 'Missing cleanup/final summary')
            need(not r['recovery_accepted'], 'Diagnostics cannot accept recovery')
            need(r['cleanup_ok'] == (cleanup['code'] == 0), 'Cleanup result mismatch')
            summary = r
        if event in ('classification', 'devnode', 'interface'):
            need(r['outcome'] in ('intended', 'unmatched', 'indeterminate') and r['bus'] in ('usb', 'hid', 'other', 'unknown'), 'Unknown identity classification')
            need(r['role'] in ('usb_parent', 'usb_function', 'hid_child', 'related_hid', 'unresolved', 'none') and
                 r['hardware'] in HARDWARE and r['root_hardware'] in HARDWARE, 'Unknown identity metadata')
            for k in ('present', 'root_present', 'started'): integer(r[k], -1, 1)
            integer(r['depth'], 0, 8)
            integer(r['token'], 0, 128); integer(r['root_token'], 0, 128)
            if r['outcome'] == 'intended':
                need(r['root_hardware'] == 'target_usb_parent' and not r['root_hardware_code'] and
                     not r['root_enumerator_code'] and not r['hardware_code'] and not r['enumerator_code'] and
                     r['enumerator_valid'] and r['hardware_valid'] and r['ancestry_complete'] and r['ancestry_code'] == 0, 'Intended identity lacks property/ancestry proof')
                expected = {'usb_parent': ('usb', 'target_usb_parent'), 'usb_function': ('usb', 'target_usb_function'),
                            'hid_child': ('hid', 'target_hid'), 'related_hid': ('hid', 'unmatched')}
                need(r['role'] in expected and (r['bus'], r['hardware']) == expected[r['role']], 'Hardware identity/role conflict')
                need((r['role'] == 'usb_parent') == (r['depth'] == 0), 'Parent relationship missing')
                if r['status_code'] == 0:
                    need(r['started'] == int(bool(r['status'] & 8)) and
                         (r['status'] & 0x400 or r['problem'] == 0), 'Startup/status mismatch')
            else:
                need(r['token'] == r['root_token'] == r['status'] == 0 and r['started'] == r['problem'] == -1,
                     'Unrelated identifiers/status must be redacted')
    need(summary is not None, 'Missing summary; evidence incomplete')
    lifecycle = registrations == {'usb': 0, 'hid': 0} and unregistrations == registrations
    cadence = max(gaps, default=0) <= 2.35
    closed = len(begins) == len(snapshots) and bool(snapshots)
    classifications_complete = receipts.keys() == classified.keys() and drain_processed == len(receipts) and drains_complete and all(c['outcome'] != 'indeterminate' and
        not c['lookup_code'] and not c['interface_code'] and not c['cleanup_code'] for c in classified.values())
    observed_complete = closed and all(s['coverage_complete'] for s in snapshots) and classifications_complete and \
        bool(queue) and not queue['dropped'] and not queue['malformed'] and cadence
    if stopped and session and 1000*(stopped['qpc_end']-stopped['qpc_begin']) > (session['duration_ms']+250)*header['qpc_frequency']:
        observed_complete = False
    if summary['coverage_complete']:
        need(observed_complete and not failures, 'Coverage claimed without complete observations')
    complete = bool(summary['collection_complete'] and summary['coverage_complete'] and summary['cleanup_ok'] and
                    lifecycle and session and stopped and observed_complete and not failures)
    need(not summary['collection_complete'] or complete, 'False collection completeness claim')
    if require_complete:
        need(complete, 'PnP diagnostic coverage incomplete')
    return dict(schema=SCHEMA, origin=header['origin'], records=len(rows), snapshots=len(snapshots),
                receipts=len(receipts), intended_notifications=sum(c['outcome'] == 'intended' for c in classified.values()),
                unmatched_notifications=sum(c['outcome'] == 'unmatched' for c in classified.values()),
                indeterminate_notifications=sum(c['outcome'] == 'indeterminate' for c in classified.values()),
                collection_complete=complete, coverage_complete=bool(observed_complete and summary['coverage_complete']),
                max_snapshot_gap_seconds=max(gaps, default=0), observation_disagreements=disagreements,
                first_failure=failures[0]['reason'] if failures else None, recovery_accepted=False,
                physical_absence_proven=False, diagnostic_only=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('evidence', type=Path)
    parser.add_argument('--allow-host-test', action='store_true')
    parser.add_argument('--allow-incomplete', action='store_true')
    args = parser.parse_args()
    print(json.dumps(validate(load(args.evidence), allow_host_test=args.allow_host_test,
                              require_complete=not args.allow_incomplete), indent=2))


if __name__ == '__main__':
    main()
