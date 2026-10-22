# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
"""Read-only, independently validated companion evidence. Import never queries hardware."""
import argparse
import json
from pathlib import Path
import pnp_coverage_v2 as original_policy

SCHEMA = 'pnp-rejection-v1'
COMMON = set('schema sequence qpc event'.split())
DETAIL = set('sample attempt source enumerator node_token property_token property_key property_api '
             'property_owner property_code code_domain property_type byte_length_class strings count_known '
             'decoding first_rejected_entry shape component_order list_relationship complete_pair has_complete_pair '
             'original_property_reason original_reason original_ancestry_property_reason present interface_flags inactive_nonpresent relation '
             'parent_outcome parent_code depth chain root_token possible_target target_related_hid_own_failure'.split())
FIELDS = {
    'header': set('origin frequency byte_cap row_cap detail_cap token_cap entry_cap depth_cap diagnostic_ms scan_ms raw_notification_cap'.split()),
    'snapshot_begin': set('sample begin present_set_complete target_roots'.split()),
    'target_anchor': set('sample token bus hardware enumerator_code hardware_code status_code present started has_problem'.split()),
    'tree_anchor': set('sample token lookup_code'.split()),
    'rejection': DETAIL, 'context': DETAIL,
    'snapshot': set('sample begin end indeterminate contexts context_unknown_ancestry node_indeterminate interface_indeterminate '
                    'target_related other_branch unknown_ancestry inactive_nonpresent target_related_hid_own_failure '
                    'details omitted tokens detail_complete attribution_complete over_budget original_ready reasons'.split()),
    'first_failure': {'reason'},
    'cleanup': {'original_first_failure', 'original_cleanup_ok'},
    'summary': {'writer_ok', 'diagnostic_failure', 'recovery_accepted'},
}
ORDERS = {'none', 'other', 'vid_pid', 'vid_pid_rev', 'vid_pid_mi', 'vid_pid_col', 'vid_pid_rev_mi',
          'vid_pid_rev_col', 'vid_pid_mi_col', 'vid_pid_rev_mi_col', 'vid_usage'}
FAILURES = {'evidence_limit', 'token_limit', 'detail_limit', 'diagnostic_time_limit',
            'scan_budget_exceeded', 'raw_notifications_unsupported'}

def need(value, reason):
    if not value:
        raise ValueError(reason)

def integer(value, lo=0, hi=2**63-1):
    need(type(value) is int and lo <= value <= hi, 'Integer outside diagnostic bounds')

def boolean(value):
    need(type(value) is bool, 'Diagnostic boolean required')

def choice(value, values):
    need(type(value) is str and value in values, 'Unknown diagnostic category')

def _pairs(items):
    result = {}
    for key, value in items:
        need(key not in result, 'Duplicate JSON key')
        result[key] = value
    return result

def read(path, cap=1048576, row_cap=4096):
    with Path(path).open('rb') as f:
        raw = f.read(cap+1)
    need(0 < len(raw) <= cap and raw.endswith(b'\n'), 'Oversize or truncated diagnostic stream')
    lines = raw.splitlines()
    need(len(lines) <= row_cap and all(0 < len(x) <= 16384 for x in lines), 'Row/line limit')
    def constant(_):
        raise ValueError('Nonfinite JSON constant')
    return [json.loads(x, object_pairs_hook=_pairs, parse_constant=constant) for x in lines]

def validate(rows, original, *, allow_host_test=False):
    # Original global identity, HID, lifecycle and first-failure requirements remain authoritative.
    original_result = original_policy.validate(original, allow_host_test=allow_host_test, require_complete=False)
    need(type(rows) is list and rows and len(rows) <= 4096, 'Missing companion evidence')
    header = rows[0]
    need(header.get('event') == 'header', 'Companion header required')
    snapshots = {x['sample']: x for x in original if x['event'] == 'snapshot'}
    original_first = next((x['reason'] for x in original if x['event'] == 'first_failure'), 0)
    original_cleanup = next(x['code'] == 0 for x in original if x['event'] == 'cleanup')
    previous = 0
    active = None
    ended = []
    failure = cleanup = summary = None
    byte_count = 0
    for index, row in enumerate(rows):
        need(type(row) is dict and row.get('event') in FIELDS, 'Unknown companion event')
        event = row['event']
        need(set(row) == COMMON | FIELDS[event] and row['schema'] == SCHEMA, 'Companion closed schema mismatch')
        integer(row['sequence']); need(row['sequence'] == index, 'Companion sequence mismatch')
        integer(row['qpc'], 1); need(row['qpc'] >= previous, 'Companion clock reversed')
        previous = row['qpc']
        byte_count += len(json.dumps(row, separators=(',', ':'), ensure_ascii=True).encode())+1
        if event == 'header':
            need(index == 0, 'Repeated companion header')
            choice(row['origin'], {'live', 'host-test'})
            need(allow_host_test or row['origin'] == 'live', 'HOST TEST is not physical evidence')
            need(row['origin'] == original[0]['origin'], 'Original/companion origin mismatch')
            integer(row['frequency'], 1, 10**12)
            need(row['frequency'] == original[0]['qpc_frequency'], 'Companion clock domain mismatch')
            integer(row['byte_cap'], 4096, 1048576); integer(row['row_cap'], 8, 4096)
            for key, value in dict(detail_cap=64, token_cap=128, entry_cap=64, depth_cap=8,
                                   diagnostic_ms=25, scan_ms=250, raw_notification_cap=0).items():
                need(type(row[key]) is int and row[key] == value, 'Unknown companion budgets')
        elif event == 'snapshot_begin':
            need(active is None and cleanup is None, 'Overlapping companion snapshots')
            integer(row['sample'], 1)
            need(row['sample'] == len(ended)+1 and row['sample'] in snapshots, 'Companion sample mismatch')
            integer(row['begin'], header['qpc'], row['qpc'])
            boolean(row['present_set_complete']); integer(row['target_roots'], 0, 2048)
            native = snapshots[row['sample']]
            need(native['qpc_begin'] <= row['begin'] <= native['qpc_end'], 'Companion scan outside original bracket')
            need(row['present_set_complete'] == (native['devnode_enumeration_complete'] and
                 native['devnode_code'] == native['devnode_cleanup_code'] == 0 and
                 not native['devnode_limit_hit']) and row['target_roots'] == native['present_qualified_roots'],
                 'Anchor scope disagrees with original presence/root evidence')
            active = dict(begin=row, details=[], target=set(), tree=None, tokens=set())
        elif event in ('target_anchor', 'tree_anchor'):
            integer(row['sample'], 1)
            need(active is not None and row['sample'] == active['begin']['sample'], 'Anchor outside snapshot')
            integer(row['token'], 1, 128)
            need(row['token'] not in active['tokens'], 'Duplicate anchor token')
            active['tokens'].add(row['token'])
            if event == 'tree_anchor':
                integer(row['lookup_code'], 0, 2**32-1)
                need(active['tree'] is None and row['lookup_code'] == 0, 'Missing independent tree-root proof')
                active['tree'] = row['token']
            else:
                for k in ('enumerator_code', 'hardware_code', 'status_code'): integer(row[k], 0, 2**32-1)
                for k in ('present', 'started', 'has_problem'): boolean(row[k])
                need(row['bus'] == 'usb' and row['hardware'] == 'target_usb_parent' and
                     row['enumerator_code'] == row['hardware_code'] == row['status_code'] == 0 and
                     row['present'] is row['started'] is True and row['has_problem'] is False,
                     'Target anchor lacks original own-ID/state/presence proof')
                active['target'].add(row['token'])
        elif event in ('rejection', 'context'):
            integer(row['sample'], 1)
            need(active is not None and cleanup is None and row['sample'] == active['begin']['sample'], 'Detail outside snapshot')
            integer(row['attempt'], 1, 6144)
            need(not active['details'] or row['attempt'] > active['details'][-1]['attempt'], 'Repeated detail attempt')
            need(len(active['details']) < 64, 'Detail cap exceeded')
            choice(row['source'], {'present_devnode', 'usb_interface', 'hid_interface'})
            choice(row['enumerator'], {'usb', 'hid', 'other', 'unknown'})
            for k in ('node_token', 'property_token'): integer(row[k], 1, 128)
            integer(row['root_token'], 0, 128); integer(row['depth'], 0, 8)
            need(type(row['chain']) is list and len(row['chain']) == row['depth']+1 and
                 len(set(row['chain'])) == len(row['chain']) and row['chain'][0] == row['node_token'],
                 'Invalid bounded topology chain')
            for t in row['chain']: integer(t, 1, 128)
            need(row['property_token'] in row['chain'], 'Property owner outside recorded walk')
            active['tokens'].update(row['chain'])
            choice(row['property_owner'], {'own', 'ancestor', 'relationship'})
            need((row['property_owner'] == 'ancestor') == (row['property_token'] != row['node_token']), 'Own/ancestor conflation')
            choice(row['property_key'], {'hardware_ids', 'enumerator_name', 'none'})
            need(row['property_api'] == ('none' if row['property_key'] == 'none' else 'CM_Get_DevNode_PropertyW'), 'Property API mismatch')
            need((row['property_key'] == 'none') == (row['property_owner'] == 'relationship'), 'Property phase mismatch')
            need(row['code_domain'] == 'configret', 'Return-code domain mismatch')
            for k in ('property_code', 'property_type', 'parent_code', 'interface_flags'): integer(row[k], 0, 2**32-1)
            choice(row['byte_length_class'], {'unknown', 'zero', 'empty_size', 'small', 'medium', 'bounded', 'over_cap'})
            integer(row['strings'], 0, 64); integer(row['first_rejected_entry'], -1, 63)
            boolean(row['count_known'])
            if row['count_known']:
                need(row['decoding'] == 'valid' and row['first_rejected_entry'] < row['strings'], 'Decoded list/index mismatch')
            else:
                need(row['strings'] == 0 and row['first_rejected_entry'] == -1, 'Invented undecoded list count')
            choice(row['decoding'], {'valid', 'api_failure', 'unexpected_type', 'limit', 'invalid_length',
                                     'invalid_termination', 'not_queried', 'invalid_string', 'valid_string'})
            choice(row['shape'], {'none', 'documented_vendor_usage', 'full_vendor', 'unrecognized', 'invalid_component'})
            choice(row['component_order'], ORDERS)
            choice(row['list_relationship'], {'not_decoded', 'empty', 'conflicting', 'unsupported', 'invalid_syntax',
                                              'partial_only', 'full_with_partial_context', 'full_consistent', 'generic_only'})
            choice(row['complete_pair'], {'none', 'target', 'other', 'mixed'})
            boolean(row['has_complete_pair'])
            need(row['has_complete_pair'] == (row['complete_pair'] != 'none'), 'Complete-pair context mismatch')
            if row['shape'] == 'documented_vendor_usage':
                need(row['component_order'] == 'vid_usage' and row['decoding'] == 'valid' and
                     row['original_property_reason'] == 'invalid_hardware_syntax', 'Partial shape promoted or unexplained')
            choice(row['original_property_reason'], original_policy.REASONS)
            choice(row['original_ancestry_property_reason'], original_policy.REASONS)
            choice(row['original_reason'], original_policy.REASONS - ({'none'} if event == 'rejection' else set()))
            if event == 'context': need(row['original_reason'] == 'none', 'Context altered original classification')
            integer(row['present'], -1, 1)
            need(row['source'] != 'present_devnode' or row['present'] == 1, 'Present source lost presence')
            boolean(row['inactive_nonpresent'])
            need(row['inactive_nonpresent'] == (row['source'] != 'present_devnode' and
                 not row['interface_flags'] & 1 and row['present'] == 0), 'Inactive/present conflation')
            choice(row['relation'], {'target', 'other_branch', 'unknown'})
            choice(row['parent_outcome'], {'parent_unavailable', 'time_limit', 'target_reached', 'tree_root_reached',
                                          'no_target_anchor', 'depth_limit', 'acquisition_limit', 'cycle'})
            if row['relation'] == 'target':
                need(row['parent_outcome'] == 'target_reached' and row['root_token'] in active['target'] and
                     row['chain'][-1] == row['root_token'], 'Target topology lacks independent anchor')
            elif row['relation'] == 'other_branch':
                need(row['parent_outcome'] == 'tree_root_reached' and active['target'] and
                     active['begin']['present_set_complete'] and row['root_token'] == active['tree'] and
                     row['chain'][-1] == active['tree'] and not active['target'].intersection(row['chain']),
                     'Unrelatedness inferred without full independent ancestry')
            else:
                need(row['parent_outcome'] not in {'target_reached', 'tree_root_reached'}, 'Known ancestry labelled unknown')
            boolean(row['possible_target'])
            need(row['possible_target'] == (row['relation'] != 'other_branch'), 'Unknown ancestry excluded from target scope')
            boolean(row['target_related_hid_own_failure'])
            if row['target_related_hid_own_failure']:
                need(row['relation'] == 'target' and row['enumerator'] == 'hid' and row['property_owner'] == 'own' and
                     row['original_property_reason'] != 'none', 'Invented own HID qualification failure')
            active['details'].append(row)
        elif event == 'snapshot':
            integer(row['sample'], 1)
            need(active is not None and row['sample'] == active['begin']['sample'], 'Missing companion snapshot begin')
            native = snapshots[row['sample']]
            integer(row['begin'], header['qpc'], row['qpc']); integer(row['end'], row['begin'], row['qpc'])
            need(row['begin'] == active['begin']['begin'], 'Companion bracket changed')
            for k in ('indeterminate', 'contexts', 'context_unknown_ancestry', 'node_indeterminate', 'interface_indeterminate', 'target_related',
                      'other_branch', 'unknown_ancestry', 'inactive_nonpresent', 'target_related_hid_own_failure', 'omitted'):
                integer(row[k], 0, 6144)
            integer(row['details'], 0, 64); integer(row['tokens'], 0, 128)
            need(row['indeterminate']+row['contexts'] <= 6144 and
                 row['details']+row['omitted'] == row['indeterminate']+row['contexts'], 'Missing/extra diagnostic attempts')
            need(row['indeterminate'] == row['node_indeterminate']+row['interface_indeterminate'] ==
                 row['target_related']+row['other_branch']+row['unknown_ancestry'], 'Scope aggregate mismatch')
            need(row['context_unknown_ancestry'] <= row['contexts'] and
                 row['inactive_nonpresent'] <= row['interface_indeterminate']+row['contexts'] and
                 row['target_related_hid_own_failure'] <= row['target_related']+row['contexts'],
                 'Scope subcounts exceed possible attempts')
            need(row['node_indeterminate'] == native['indeterminate'] and
                 row['interface_indeterminate'] == native['interface_indeterminate'], 'Original global rejection counts changed')
            need(type(row['reasons']) is list and len(row['reasons']) <= len(original_policy.REASONS), 'Histogram cap')
            reasons = {}
            for item in row['reasons']:
                need(type(item) is dict and set(item) == {'reason', 'count'}, 'Histogram schema')
                choice(item['reason'], original_policy.REASONS - {'none'})
                integer(item['count'], 1, 6144)
                need(item['reason'] not in reasons, 'Repeated rejection reason')
                reasons[item['reason']] = item['count']
            need(sum(reasons.values()) == row['indeterminate'] and reasons ==
                 {x['reason']: x['count'] for x in native['classification_failures']}, 'Original rejection reasons changed')
            need(row['details'] == len(active['details']) and len(active['tokens']) <= row['tokens'], 'Detail/token counts mismatch')
            for k in ('detail_complete', 'attribution_complete', 'over_budget', 'original_ready'): boolean(row[k])
            need(row['original_ready'] == native['initial_ready'], 'Diagnostic changed original readiness')
            need(row['attribution_complete'] == (row['unknown_ancestry'] == row['context_unknown_ancestry'] == 0),
                 'Unknown ancestry concealed')
            need(row['over_budget'] == (1000*(row['end']-row['begin']) > 250*header['frequency']), 'Silent scan overhead')
            if row['detail_complete']:
                need(row['omitted'] == 0 and not row['over_budget'] and
                     len(active['target']) == active['begin']['target_roots'], 'Incomplete details claim completeness')
                details = active['details']
                rejected = [x for x in details if x['event'] == 'rejection']
                need(sum(x['relation'] == 'target' for x in rejected) == row['target_related'] and
                     sum(x['relation'] == 'other_branch' for x in rejected) == row['other_branch'] and
                     sum(x['relation'] == 'unknown' for x in rejected) == row['unknown_ancestry'] and
                     sum(x['inactive_nonpresent'] for x in details) == row['inactive_nonpresent'] and
                     sum(x['event'] == 'context' and x['relation'] == 'unknown' for x in details) == row['context_unknown_ancestry'] and
                     sum(x['target_related_hid_own_failure'] for x in details) == row['target_related_hid_own_failure'],
                     'Detailed scope/qualification disagrees with aggregates')
            ended.append(row);active = None
        elif event == 'first_failure':
            need(failure is None and cleanup is None, 'Diagnostic first failure overwritten')
            choice(row['reason'], FAILURES); failure = row
        elif event == 'cleanup':
            need(active is None and cleanup is None, 'Incomplete/duplicate cleanup')
            integer(row['original_first_failure'], 0, 9); boolean(row['original_cleanup_ok'])
            need(row['original_first_failure'] == original_first and row['original_cleanup_ok'] == original_cleanup,
                 'Original first failure/cleanup changed')
            cleanup = row
        elif event == 'summary':
            need(index == len(rows)-1 and cleanup is not None and active is None, 'Missing final cleanup/summary')
            for k in ('writer_ok', 'diagnostic_failure', 'recovery_accepted'): boolean(row[k])
            need(row['diagnostic_failure'] == (failure is not None) and not row['recovery_accepted'],
                 'Companion overrides acceptance or hides failure')
            summary = row
    need(summary is not None and len(ended) == len(snapshots) and
         len(rows) <= header['row_cap'] and byte_count <= header['byte_cap'], 'Incomplete/capped companion stream')
    return dict(schema=SCHEMA, origin=header['origin'], snapshots=len(ended),
                diagnostic_complete=summary['writer_ok'] and failure is None and original_cleanup and
                    all(x['detail_complete'] and x['attribution_complete'] for x in ended),
                first_diagnostic_failure=failure['reason'] if failure else None,
                original_first_failure=original_first, original_collection_complete=original_result['collection_complete'],
                original_readiness=[x['initial_ready'] for x in snapshots.values()],
                recovery_accepted=False, diagnostic_only=True)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('diagnostic', type=Path)
    parser.add_argument('--original-v2', required=True, type=Path)
    parser.add_argument('--allow-host-test', action='store_true')
    args = parser.parse_args()
    try:
        rows = read(args.diagnostic)
        original = read(args.original_v2, 8*1024*1024, 20000)
        result = validate(rows, original, allow_host_test=args.allow_host_test)
        print(json.dumps(result, allow_nan=False))
        return 0
    except (OSError, ValueError):
        print('Companion evidence rejected; preserve original failure and partial data.')
        return 1

if __name__ == '__main__':
    raise SystemExit(main())
