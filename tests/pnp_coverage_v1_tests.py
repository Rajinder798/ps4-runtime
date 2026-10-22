# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
"""Actual native collector with synthetic providers only. No device API/live watcher."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
import pnp_coverage_v1 as pnp

DRIVER = Path(sys.argv.pop(1)).resolve()


class CoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.folder = Path(cls.tmp.name)/'synthetic'
        subprocess.run([str(DRIVER), '--host-test', str(cls.folder)], check=True, capture_output=True)
        cls.streams = {p.stem: pnp.load(p) for p in cls.folder.glob('*.jsonl')}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def report(self, name, complete=False):
        return pnp.validate(self.streams[name], allow_host_test=True, require_complete=complete)

    def test_property_backed_opaque_notification_and_parent_child(self):
        report = self.report('intended', True)
        self.assertEqual(report['intended_notifications'], 1)
        rows = self.streams['intended']
        child = next(r for r in rows if r['event'] == 'classification')
        self.assertEqual((child['role'], child['depth'], child['root_hardware']), ('hid_child', 2, 'target_usb_parent'))
        self.assertNotEqual(child['token'], child['root_token'])
        self.assertEqual(self.report('related-hid', True)['intended_notifications'], 1)

    def test_host_tests_never_accepted_as_physical_evidence(self):
        for rows in self.streams.values():
            with self.assertRaises(ValueError):
                pnp.validate(rows, require_complete=False)

    def test_unmatched_is_accounted_without_identifiers(self):
        self.assertEqual(self.report('unmatched', True)['unmatched_notifications'], 1)
        row = next(r for r in self.streams['unmatched'] if r['event'] == 'classification')
        self.assertEqual((row['token'], row['root_token'], row['status']), (0, 0, 0))
        self.assertFalse(any(r['event'] == 'devnode' for r in self.streams['unmatched']))

    def test_missing_malformed_unavailable_properties_and_parent_cycle(self):
        for name in ('missing-hardware', 'malformed-hardware', 'parent-unavailable', 'parent-cycle',
                     'status-unavailable', 'key-unavailable', 'malformed-enumerator'):
            with self.subTest(name=name):
                self.assertFalse(self.report(name)['collection_complete'])
                self.assertIsNotNone(self.report(name)['first_failure'])
                with self.assertRaises(ValueError): self.report(name, True)

    def test_multiple_controllers_not_selected(self):
        row = next(r for r in self.streams['multiple'] if r['event'] == 'snapshot')
        self.assertTrue(row['ambiguous'])
        self.assertEqual(row['roots'], 2)
        self.assertFalse(self.report('multiple')['collection_complete'])

    def test_devnode_without_interface_is_distinct(self):
        self.assertTrue(self.report('node-without-interface', True)['collection_complete'])
        row = next(r for r in self.streams['node-without-interface'] if r['event'] == 'snapshot')
        self.assertEqual((row['usb_parents'], row['hid_children'], row['active_usb'], row['active_hid']), (1, 1, 0, 0))

    def test_interface_enabled_present_and_started_are_separate(self):
        self.assertTrue(self.report('not-started', True)['collection_complete'])
        row = next(r for r in self.streams['not-started'] if r['event'] == 'devnode' and r['role'] == 'hid_child')
        self.assertEqual((row['present'], row['started'], row['problem']), (1, 0, 10))
        self.assertTrue(self.report('inactive-interface', True)['collection_complete'])
        self.assertTrue(self.report('optional-compatible-malformed', True)['collection_complete'])
        row = next(r for r in self.streams['inactive-interface'] if r['event'] == 'snapshot')
        self.assertEqual(row['inactive_interfaces'], 1)
        self.assertTrue(self.report('notice-without-present-node', True)['observation_disagreements'])

    def test_removal_property_failure_retains_receipt_and_api_code(self):
        rows = self.streams['removal-lookup-failed']
        receipt = next(r for r in rows if r['event'] == 'receipt')
        result = next(r for r in rows if r['event'] == 'classification')
        self.assertEqual((receipt['action'], result['lookup_attempted'], result['lookup_code'], result['outcome']), (1, True, 433, 'indeterminate'))
        self.assertEqual(receipt['receipt'], result['receipt'])
        self.assertFalse(self.report('removal-lookup-failed')['collection_complete'])

    def test_failed_partial_enumeration_never_complete_absence(self):
        for name in ('enumeration-failed', 'enumeration-partial', 'interface-enumeration-failed',
                     'interface-detail-failed', 'empty-incomplete'):
            self.assertFalse(self.report(name)['coverage_complete'])
        row = next(r for r in self.streams['empty-incomplete'] if r['event'] == 'snapshot')
        self.assertEqual(row['presence'], 'unknown')
        self.assertEqual(self.report('empty-complete', True)['snapshots'], 1)

    def test_notice_and_snapshot_disagreement_is_diagnostic_only(self):
        report = self.report('notice-snapshot-disagreement', True)
        self.assertEqual(report['observation_disagreements'][0]['kind'], 'arrival_then_no_qualifying_node')
        self.assertFalse(report['recovery_accepted'])
        self.assertFalse(report['physical_absence_proven'])

    def test_queue_and_resource_limits_latch_first_failure(self):
        for name in ('queue-overflow', 'relevant-cap', 'node-cap', 'token-cap', 'malformed-callback',
                     'lookup-cleanup-error', 'storage-limit'):
            with self.subTest(name=name):
                report = self.report(name)
                self.assertFalse(report['collection_complete'])
                failures = [r for r in self.streams[name] if r['event'] == 'first_failure']
                self.assertEqual(len(failures), 1)
                self.assertLess(failures[0]['sequence'], next(r['sequence'] for r in self.streams[name] if r['event'] == 'cleanup'))
        queue = next(r for r in self.streams['queue-overflow'] if r['event'] == 'queue')
        self.assertEqual((queue['processed'], queue['dropped'], sum(queue['counts'])), (256, 1, 257))
        row = next(r for r in self.streams['storage-limit'] if r['event'] == 'cleanup')
        self.assertEqual(row['code'], 5)
        self.assertEqual(self.report('metadata-resources')['first_failure'], 3)
        self.assertEqual(self.report('registration-cleanup-error')['first_failure'], 6)

    def test_out_of_order_clocks_are_rejected(self):
        with self.assertRaises(ValueError): self.report('clock-reversal')
        for key in ('qpc', 'qpc_begin', 'qpc_end'):
            rows = copy.deepcopy(self.streams['intended'])
            row = next(r for r in rows if r['event'] == 'classification')
            row[key] = 1
            with self.assertRaises(ValueError): pnp.validate(rows, allow_host_test=True)

    def test_privacy_and_exact_allowlists(self):
        for path in self.folder.glob('*.jsonl'):
            data = path.read_text()
            for private in ('PRIVATE', 'SERIAL', '11:22:33:44:55:66', '\\\\?\\', 'VID_054C', 'DevicePath'):
                self.assertNotIn(private, data)
        for event in ('receipt', 'classification', 'snapshot', 'devnode', 'interface'):
            rows = copy.deepcopy(self.streams['intended'])
            next(r for r in rows if r['event'] == event)['serial'] = 'PRIVATE'
            with self.assertRaises(ValueError): pnp.validate(rows, allow_host_test=True)

    def test_recovery_acceptance_cannot_be_overridden(self):
        for rows in self.streams.values(): self.assertFalse(rows[-1]['recovery_accepted'])
        rows = copy.deepcopy(self.streams['intended']); rows[-1]['recovery_accepted'] = True
        with self.assertRaises(ValueError): pnp.validate(rows, allow_host_test=True)

    def test_incomplete_claims_and_missing_classification_cannot_pass(self):
        for name in ('empty-incomplete', 'multiple', 'missing-hardware'):
            rows = copy.deepcopy(self.streams[name])
            rows[-1].update(collection_complete=True, coverage_complete=True)
            with self.assertRaises(ValueError): pnp.validate(rows, allow_host_test=True)
        rows = copy.deepcopy(self.streams['intended'])
        rows = [r for r in rows if r['event'] != 'classification']
        for i, row in enumerate(rows): row['sequence'] = i
        with self.assertRaises(ValueError): pnp.validate(rows, allow_host_test=True)

    def test_bad_property_proof_and_counts_cannot_pass(self):
        for key, value in (('root_hardware', 'unmatched'), ('root_hardware_code', 13), ('depth', 0),
                           ('started', 0), ('hardware', 'unmatched'), ('token', 129)):
            rows = copy.deepcopy(self.streams['intended'])
            next(r for r in rows if r['event'] == 'classification')[key] = value
            with self.assertRaises(ValueError): pnp.validate(rows, allow_host_test=True)
        rows = copy.deepcopy(self.streams['intended'])
        next(r for r in rows if r['event'] == 'queue')['processed'] += 1
        with self.assertRaises(ValueError): pnp.validate(rows, allow_host_test=True)

    def test_overhead_and_cadence_cannot_be_hidden(self):
        for name in ('scan-overhead', 'drain-overhead', 'late-cadence'):
            self.assertFalse(self.report(name)['collection_complete'])
            self.assertEqual(self.report(name)['first_failure'], 9)
        rows = copy.deepcopy(self.streams['intended'])
        next(r for r in rows if r['event'] == 'snapshot')['over_budget'] = True
        with self.assertRaises(ValueError): pnp.validate(rows, allow_host_test=True)
        rows = copy.deepcopy(self.streams['intended'])
        next(r for r in rows if r['event'] == 'snapshot')['cadence_late'] = True
        with self.assertRaises(ValueError): pnp.validate(rows, allow_host_test=True)

    def test_storage_rejects_corruption_duplicates_and_truncation(self):
        original = (self.folder/'intended.jsonl').read_bytes()
        for raw in (original[:-1], original.replace(b'"sequence":0', b'"sequence":0,"sequence":0', 1),
                    original.replace(b'"sequence":0', b'"sequence":NaN', 1), b'x'*(pnp.MAX_BYTES+1)):
            path = Path(self.tmp.name)/'invalid.jsonl'; path.write_bytes(raw)
            with self.assertRaises((ValueError, UnicodeError)): pnp.load(path)


if __name__ == '__main__':
    unittest.main()
