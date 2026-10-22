# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
"""HOST TEST raw acquisition and original policy; never imports the Windows source."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools'))
import pnp_rejection_v1 as diagnostic
import no_guest_coordinator_v1 as coordinator
DRIVER = Path(sys.argv.pop(1)).resolve()

class RejectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.folder = Path(cls.tmp.name).resolve()/'fixtures'
        subprocess.run([str(DRIVER), '--host-test', str(cls.folder)], check=True,
                       capture_output=True, timeout=40)
        cls.rows = {}
        cls.original = {}
        for p in cls.folder.glob('*.rejection.jsonl'):
            name = p.name.removesuffix('.rejection.jsonl')
            cls.rows[name] = diagnostic.read(p)
            cls.original[name] = diagnostic.read(cls.folder/(name+'.v2.jsonl'), 8*1024*1024, 20000)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def report(self, name):
        return diagnostic.validate(self.rows[name], self.original[name], allow_host_test=True)

    def details(self, name):
        return [r for r in self.rows[name] if r['event'] in ('rejection', 'context')]

    def snapshot(self, name):
        return next(r for r in self.rows[name] if r['event'] == 'snapshot')

    def test_all_canonical_hid_combinations_preserve_original_readiness(self):
        for n in range(8):
            name = 'canonical-'+str(n)
            self.assertTrue(self.report(name)['diagnostic_complete'])
            self.assertEqual(self.report(name)['original_readiness'], [True])
            self.assertEqual(self.report(name)['original_first_failure'], 0)

    def test_all_complete_streams_independently_validate(self):
        for name in self.rows:
            if name == 'writer-fault':
                continue
            with self.subTest(name=name):
                self.assertFalse(self.report(name)['recovery_accepted'])
                self.assertTrue(self.report(name)['diagnostic_only'])

    def test_documented_partial_shape_is_context_not_a_target_identity(self):
        r = self.details('partial')[0]
        self.assertEqual((r['shape'], r['component_order'], r['complete_pair']),
                         ('documented_vendor_usage', 'vid_usage', 'none'))
        self.assertEqual(r['original_property_reason'], 'invalid_hardware_syntax')
        self.assertEqual(r['list_relationship'], 'partial_only')
        self.assertEqual(self.report('partial')['original_readiness'], [False])

    def test_complete_pair_survives_as_diagnostic_context_after_first_rejection(self):
        for name, index in [('full-partial', 1), ('partial-full', 0)]:
            r = self.details(name)[0]
            self.assertTrue(r['has_complete_pair'])
            self.assertEqual(r['complete_pair'], 'target')
            self.assertEqual(r['list_relationship'], 'full_with_partial_context')
            self.assertEqual(r['first_rejected_entry'], index)
            self.assertEqual(self.report(name)['original_first_failure'], 1)
            self.assertEqual(self.report(name)['original_readiness'], [False])

    def test_partial_context_and_full_identity_conflicts_remain_separate(self):
        self.assertEqual(self.details('partial-conflict')[0]['list_relationship'], 'conflicting')
        self.assertEqual(self.details('mixed-bus-context')[0]['list_relationship'], 'conflicting')
        r = self.details('conflict')[0]
        self.assertEqual((r['list_relationship'], r['original_reason']), ('conflicting', 'conflicting_identities'))

    def test_property_failures_preserve_acquisition_metadata(self):
        expected = {'missing': ('valid', 'missing_hardware_id', 0),
                    'termination': ('invalid_termination', 'invalid_multisz_termination', 0),
                    'property-type': ('unexpected_type', 'unexpected_property_type', 0),
                    'property-api': ('api_failure', 'property_api_failure', 37),
                    'property-limit': ('limit', 'property_limit', 0),
                    'odd-length': ('invalid_length', 'invalid_property_length', 0)}
        for name, (decoding, reason, code) in expected.items():
            r = self.details(name)[0]
            self.assertEqual((r['decoding'], r['original_property_reason'], r['property_code']),
                             (decoding, reason, code))
            self.assertEqual(r['code_domain'], 'configret')
            self.assertEqual(r['property_api'], 'CM_Get_DevNode_PropertyW')

    def test_generic_target_ancestry_does_not_supply_own_pair(self):
        r = self.details('generic-target')[0]
        self.assertEqual(r['event'], 'context')
        self.assertEqual((r['relation'], r['list_relationship'], r['complete_pair']),
                         ('target', 'generic_only', 'none'))
        self.assertTrue(r['target_related_hid_own_failure'])
        self.assertEqual(self.report('generic-target')['original_readiness'], [False])

    def test_unknown_ancestry_stays_potentially_target_related(self):
        for name in ('generic-unknown', 'generic-root-code13', 'root-proof-unavailable', 'cycle', 'depth'):
            r = self.details(name)[0]
            self.assertEqual(r['relation'], 'unknown')
            self.assertTrue(r['possible_target'])
            self.assertFalse(self.report(name)['diagnostic_complete'])

    def test_original_relationship_boundary_is_not_misattributed_to_later_bad_property(self):
        r = next(x for x in self.details('transport-boundary') if x['enumerator'] == 'hid')
        self.assertEqual(r['relation'], 'target')
        self.assertEqual(r['property_owner'], 'relationship')
        self.assertEqual(r['original_ancestry_property_reason'], 'none')
        r = next(x for x in self.details('foreign-ancestor') if x['enumerator'] == 'hid')
        self.assertEqual(r['property_owner'], 'ancestor')
        self.assertEqual(r['original_property_reason'], 'none')
        self.assertEqual(r['original_ancestry_property_reason'], 'conflicting_identities')

    def test_topology_crosses_failed_own_property_without_qualification(self):
        r = self.details('own-reject-target')[0]
        self.assertEqual(r['relation'], 'target')
        self.assertTrue(r['target_related_hid_own_failure'])
        self.assertEqual(len(r['chain']), 3)
        self.assertEqual(self.report('own-reject-target')['original_first_failure'], 1)

    def test_different_branch_requires_full_walk_to_independent_tree_root(self):
        r = self.details('own-reject-other')[0]
        self.assertEqual((r['relation'], r['parent_outcome']), ('other_branch', 'tree_root_reached'))
        self.assertFalse(r['possible_target'])
        self.assertEqual(self.report('own-reject-other')['original_readiness'], [False])

    def test_ancestor_property_failure_is_not_assigned_to_child(self):
        rows = [r for r in self.details('ancestor-reject') if r['property_owner'] == 'ancestor']
        self.assertTrue(rows)
        for r in rows:
            self.assertNotEqual(r['node_token'], r['property_token'])
            self.assertEqual(r['original_reason'], 'parent_unresolved')
            self.assertEqual(r['original_property_reason'], 'invalid_hardware_syntax')
            self.assertEqual(r['relation'], 'target')
            self.assertFalse(r['target_related_hid_own_failure'])

    def test_enumerator_api_and_type_failure_are_distinguished(self):
        for name in ('enumerator-type', 'enumerator-api'):
            r = self.details(name)[0]
            self.assertEqual(r['property_key'], 'enumerator_name')
            self.assertEqual(r['original_property_reason'],
                             'enumerator_unavailable' if name.endswith('api') else 'enumerator_malformed')

    def test_no_target_anchor_or_classification_never_proves_unrelatedness(self):
        for name in ('unclassifiable', 'no-target-anchor'):
            for r in self.details(name):
                self.assertEqual(r['relation'], 'unknown')
                self.assertTrue(r['possible_target'])
            self.assertFalse(self.report(name)['diagnostic_complete'])

    def test_installed_inactive_root_and_rejected_interface_are_separate(self):
        self.assertEqual(self.report('historical-root')['original_readiness'], [True])
        native = next(x for x in self.original['historical-root'] if x['event'] == 'snapshot')
        self.assertEqual(native['installed_inactive_roots'], 1)
        self.assertFalse(native['ambiguous'])
        self.assertTrue(any(x['inactive_nonpresent'] for x in self.details('inactive-rejected')))

    def test_exact_aggregate_reproduction_is_synthetic_and_unchanged(self):
        s = self.snapshot('exact-counts')
        self.assertEqual((s['node_indeterminate'], s['interface_indeterminate']), (27, 23))
        self.assertEqual({x['reason']: x['count'] for x in s['reasons']},
                         {'invalid_hardware_syntax': 22, 'missing_hardware_id': 7, 'unrecognized_form': 21})
        self.assertEqual(s['indeterminate'], s['target_related']+s['other_branch']+s['unknown_ancestry'])
        self.assertEqual(s['details'], 50)
        self.assertEqual(self.report('exact-counts')['original_readiness'], [False])
        self.assertEqual(self.rows['exact-counts'][0]['origin'], 'host-test')

    def test_sdl_wired_open_cannot_promote_missing_hid(self):
        native = self.original['missing-hid']
        f = native[0]['qpc_frequency']
        strict = [dict(event='opened', instance_id=1, qpc=100, qpc_frequency=f, connection='wired',
                       vendor=1356, product=3302, virtual=False),
                  dict(event='hotplug_opened', instance_id=1, episode=0, qpc=101, qpc_frequency=f,
                       sdl_timestamp_ns=0, connection='wired', vendor=1356, product=3302,
                       real_type=6, virtual=False, sole=True)]
        device = dict(instance_id=1, vendor=1356, product=3302, identity_redacted=False,
                      real_type=6, virtual=False, is_gamepad=True)
        sdl = [dict(event='windows_registration', interface=k, code=0) for k in ('usb', 'hid')]
        sdl += [dict(event='sdl_open_result', instance_id=1, ok=True, wired=True),
                dict(event='sdl_clock_anchor'), dict(event='poll_heartbeat'),
                dict(event='sdl_inventory', joysticks=[device], gamepads=[device])]
        self.assertTrue(coordinator.sdl_ready(sdl, strict, f))
        with self.assertRaises(ValueError):
            coordinator.pnp_ready(native)
        self.assertEqual(self.report('missing-hid')['original_readiness'], [False])

    def test_caps_preserve_original_counts_and_mark_omissions(self):
        for name in ('byte-cap', 'row-cap'):
            s = self.snapshot(name)
            self.assertEqual(s['indeterminate'], 50)
            self.assertGreater(s['omitted'], 0)
            self.assertFalse(s['detail_complete'])
            self.assertEqual(self.report(name)['first_diagnostic_failure'], 'evidence_limit')
            self.assertLessEqual((self.folder/(name+'.rejection.jsonl')).stat().st_size,
                                 self.rows[name][0]['byte_cap'])
        for name in ('detail-cap', 'token-cap'):
            s = self.snapshot(name)
            self.assertLessEqual(s['details'], 64)
            self.assertLessEqual(s['tokens'], 128)
            self.assertGreater(s['omitted'], 0)
            self.assertFalse(self.report(name)['diagnostic_complete'])

    def test_scan_overhead_is_visible_in_original_and_companion(self):
        self.assertTrue(self.snapshot('scan-time')['over_budget'])
        self.assertEqual(self.report('scan-time')['original_first_failure'], 9)
        self.assertFalse(self.report('scan-time')['diagnostic_complete'])

    def test_diagnostic_time_entry_cache_and_raw_notification_limits(self):
        self.assertEqual(self.report('diagnostic-time')['first_diagnostic_failure'], 'diagnostic_time_limit')
        self.assertEqual(self.report('diagnostic-time')['original_first_failure'], 1)
        self.assertEqual(self.details('entry-cap')[0]['decoding'], 'limit')
        self.assertEqual(self.details('entry-cap')[0]['original_property_reason'], 'property_limit')
        cache = self.snapshot('acquisition-cache-cap')
        self.assertFalse(cache['detail_complete'])
        self.assertEqual(cache['indeterminate'], cache['node_indeterminate']+cache['interface_indeterminate'])
        self.assertTrue(any(x['reason'] == 'resource_limit' for x in cache['reasons']))
        self.assertEqual(self.report('raw-notification')['first_diagnostic_failure'], 'raw_notifications_unsupported')

    def test_writer_failure_leaves_partial_evidence_and_original_cleanup(self):
        with self.assertRaises(ValueError):
            self.report('writer-fault')
        original = diagnostic.original_policy.validate(self.original['writer-fault'],
                                                       allow_host_test=True, require_complete=False)
        self.assertEqual(original['first_failure'], 1)
        self.assertEqual(next(x['code'] for x in self.original['writer-fault'] if x['event'] == 'cleanup'), 0)

    def test_first_original_failure_survives_separate_cleanup_failure(self):
        r = self.report('cleanup-after-first')
        self.assertEqual(r['original_first_failure'], 1)
        self.assertFalse(r['diagnostic_complete'])
        self.assertFalse(next(x['original_cleanup_ok'] for x in self.rows['cleanup-after-first'] if x['event'] == 'cleanup'))

    def test_snapshot_local_tokens_and_sequences_reset_without_cross_snapshot_identity(self):
        self.assertEqual(self.report('two-snapshots')['snapshots'], 2)
        anchors = [x for x in self.rows['two-snapshots'] if x['event'] == 'target_anchor']
        self.assertEqual([x['token'] for x in anchors], [1, 1])

    def test_privacy_no_raw_ids_serials_paths_or_fingerprints(self):
        for name, rows in self.rows.items():
            raw = json.dumps(rows).upper()
            for sentinel in ('PRIVATE', '11:22:33', '054C', '045E', '0CE6', 'FA00', 'SERIAL', 'HASH', 'FINGERPRINT'):
                self.assertNotIn(sentinel, raw, name)

    def test_independent_validator_rejects_malformed_and_forged_proof(self):
        changes = {'raw_id': 'PRIVATE', 'shape': 'PRIVATE', 'component_order': 'vid_serial',
                   'node_token': 0, 'property_token': 128, 'depth': 9, 'chain': [1, 1],
                   'code_domain': 'win32', 'complete_pair': 'PRIVATE', 'present': False,
                   'possible_target': False, 'property_owner': 'ancestor', 'relation': 'other_branch',
                   'root_token': 128, 'strings': 65, 'first_rejected_entry': 64}
        for key, value in changes.items():
            rows = copy.deepcopy(self.rows['own-reject-target'])
            next(x for x in rows if x['event'] == 'rejection')[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                diagnostic.validate(rows, self.original['own-reject-target'], allow_host_test=True)
        for key, value in [('indeterminate', 0), ('target_related', 0), ('original_ready', True),
                           ('omitted', 1), ('tokens', 0), ('attribution_complete', False),
                           ('context_unknown_ancestry', 6144), ('inactive_nonpresent', 6144)]:
            rows = copy.deepcopy(self.rows['own-reject-target'])
            next(x for x in rows if x['event'] == 'snapshot')[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                diagnostic.validate(rows, self.original['own-reject-target'], allow_host_test=True)
        for event, key, value in [('target_anchor', 'hardware_code', False), ('target_anchor', 'present', 1),
                                  ('tree_anchor', 'lookup_code', False), ('snapshot_begin', 'target_roots', 0),
                                  ('snapshot_begin', 'present_set_complete', False)]:
            rows = copy.deepcopy(self.rows['own-reject-target'])
            next(x for x in rows if x['event'] == event)[key] = value
            with self.subTest(event=event, key=key), self.assertRaises(ValueError):
                diagnostic.validate(rows, self.original['own-reject-target'], allow_host_test=True)

    def test_host_origin_truncation_duplicate_keys_and_nonfinite_are_rejected(self):
        with self.assertRaises(ValueError):
            diagnostic.validate(self.rows['partial'], self.original['partial'])
        raw = (self.folder/'partial.rejection.jsonl').read_bytes()
        for data in (raw[:-1], raw.replace(b'"sequence":0', b'"sequence":0,"sequence":0', 1),
                     raw.replace(b'"sequence":0', b'"sequence":NaN', 1)):
            path = self.folder/'bad.jsonl'
            path.write_bytes(data)
            with self.assertRaises(ValueError):
                diagnostic.validate(diagnostic.read(path), self.original['partial'], allow_host_test=True)

    def test_no_live_cli_or_silent_coordinator_selection(self):
        r = subprocess.run([str(DRIVER), '--observe-live'], capture_output=True, timeout=5)
        self.assertEqual(r.returncode, 2)
        self.assertFalse((self.folder/'forbidden.jsonl').exists())
        for name in ('tools/no_guest_coordinator_v1.py', 'tools/no_guest_session_v1.py',
                     'config/no-guest-coordinator-v1.json'):
            self.assertNotIn('rejection_v1', (ROOT/name).read_text())

    def test_frozen_sources_and_validator_contracts_match_baseline(self):
        pins = json.loads((ROOT/'config/pnp-rejection-v1-baseline.json').read_text())
        for name, expected in pins['source_lf_sha256'].items():
            raw = (ROOT/name).read_bytes().replace(b'\r\n', b'\n')
            self.assertEqual(hashlib.sha256(raw).hexdigest(), expected, name)
        native = self.original['partial']
        rows = copy.deepcopy(native)
        next(x for x in rows if x['event'] == 'devnode')['extra_diagnostic'] = True
        with self.assertRaises(ValueError):
            diagnostic.original_policy.validate(rows, allow_host_test=True, require_complete=False)

if __name__ == '__main__':
    unittest.main()
