# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
"""File-only corruptions plus a synthetic-provider executable; no live APIs."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'tools'))
import pnp_diagnostic_contract_v1 as contract
import pnp_coverage_v2 as native

WORKER = sys.argv.pop(1)


class ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.folder = Path(os.environ.get('PNP_CONTRACT_REPORT_DIR', cls.temp.name))/'cases'
        result = subprocess.run([WORKER, str(cls.folder)], capture_output=True, text=True, timeout=35)
        if result.returncode:
            raise AssertionError(f'Worker exit {result.returncode}: ' + result.stdout + result.stderr)
        cls.worker_output = result.stdout
        cls.rows = contract.load(cls.folder/'good/contract.jsonl')
        cls.native = native.load(cls.folder/'good/native.jsonl')

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def resequence(self, rows):
        for i, row in enumerate(rows): row['sequence'] = i
        return rows

    def reject(self, rows):
        with self.assertRaises(ValueError):
            contract.validate(self.resequence(rows), self.native, require_complete=False)

    def test_valid_control_and_typed_forwarding(self):
        result = contract.validate(self.rows, self.native)
        self.assertTrue(result['diagnostic_complete'])
        self.assertFalse(result['recovery_accepted'])
        self.assertIn('27 fixture cases passed', self.worker_output)
        for path in self.folder.glob('*/result.json'):
            r = json.loads(path.read_text())
            self.assertTrue(r['transcripts_equal'])
            self.assertGreater(r['calls'], 0)

    def test_faults_remain_incomplete_and_native_failure_is_preserved(self):
        for folder in self.folder.iterdir():
            if folder.name == 'good': continue
            with self.subTest(case=folder.name):
                result = json.loads((folder/'result.json').read_text())
                self.assertFalse(result['complete'])
                if not result['published']:
                    self.assertFalse((folder/'contract.jsonl').exists())
                    continue
                n = native.load(folder/'native.jsonl')
                report = contract.validate(contract.load(folder/'contract.jsonl'), n, require_complete=False)
                self.assertFalse(report['diagnostic_complete'])
                self.assertEqual(report['native_first_reason'], result['native_first'])
                with self.assertRaises(ValueError): contract.validate(contract.load(folder/'contract.jsonl'), n)
        self.assertEqual(json.loads((self.folder/'native-failure/result.json').read_text())['native_first'], 1)
        self.assertEqual(json.loads((self.folder/'native-throw/result.json').read_text())['native_first'], 3)
        self.assertEqual(json.loads((self.folder/'native-overhead/result.json').read_text())['native_first'], 9)

    def test_delete_all_stage_brackets_is_rejected(self):
        self.reject([r for r in copy.deepcopy(self.rows) if r['event'] not in ('stage_begin','stage_end')])

    def test_each_required_stage_cannot_disappear(self):
        for ident in range(1, 7):
            with self.subTest(stage=ident):
                self.reject([r for r in copy.deepcopy(self.rows)
                             if not (r['event'] in ('stage_begin','stage_end') and r['id'] == ident)])

    def test_remove_all_terminal_stages_is_rejected(self):
        self.reject([r for r in copy.deepcopy(self.rows)
                     if not (r['event'] in ('stage_begin','stage_end') and r['id'] >= 4)])

    def test_scope_start_end_footer_and_native_proof_are_mandatory(self):
        for event in ('header','scope_start','scope_end','footer','native_result'):
            with self.subTest(event=event): self.reject([r for r in copy.deepcopy(self.rows) if r['event'] != event])

    def test_late_footer_and_false_finalization_are_rejected(self):
        rows = copy.deepcopy(self.rows)
        rows[-1]['qpc'] = next(r['deadline'] for r in rows if r['event'] == 'scope_start')
        self.reject(rows)
        for field in ('finalization_ok','cleanup_ok','clock_valid'):
            rows = copy.deepcopy(self.rows); rows[-1][field] = False
            self.reject(rows)

    def test_duplicate_and_reordered_terminal_phases_are_rejected(self):
        rows = copy.deepcopy(self.rows)
        index = next(i for i, r in enumerate(rows) if r['event'] == 'stage_begin' and r['id'] == 4)
        rows[index:index] = copy.deepcopy(rows[index:index+2])
        self.reject(rows)
        rows = copy.deepcopy(self.rows)
        for r in rows:
            if r['event'] == 'stage_begin' and r['id'] == 4: r['stage'] = 'final_publication'
        self.reject(rows)

    def test_invalid_parent_state_cardinality_and_skip(self):
        for field, value in (('parent',1), ('id',2), ('optional',True), ('stage','raw_windows_api')):
            rows = copy.deepcopy(self.rows)
            next(r for r in rows if r['event']=='stage_begin')[field] = value
            self.reject(rows)
        for state in ('skipped','not_measurable','unknown'):
            rows = copy.deepcopy(self.rows)
            next(r for r in rows if r['event']=='stage_end')['state'] = state
            self.reject(rows)

    def test_capture_counts_missing_facts_and_unknowns_cannot_be_complete(self):
        for field in ('calls','retained','dropped','events','event_drops','unknown','payload_bytes'):
            rows = copy.deepcopy(self.rows)
            rows[-1][field] = rows[-1][field]+1 if field != 'payload_bytes' else 1048577
            self.reject(rows)
        rows = copy.deepcopy(self.rows)
        next(r for r in rows if r['event']=='fact')['known'] = False
        self.reject(rows)
        rows = copy.deepcopy(self.rows)
        next(r for r in rows if r['event']=='fact')['ordinal'] = rows[-1]['calls']+1
        self.reject(rows)
        rows = [r for r in copy.deepcopy(self.rows) if r['event'] not in ('call','fact')]
        for key in ('calls','retained','dropped','events','event_drops','payload_bytes','unknown'): rows[-1][key] = 0
        self.reject(rows)
        rows = copy.deepcopy(self.rows); rows[-1]['payload_bytes'] = 0; self.reject(rows)

    def test_clock_uncertainty_overflow_policy_and_native_domain(self):
        for field, value in (('frequency',41), ('record_cap',65), ('payload_cap',1048577),
                             ('token_cap',129), ('depth_cap',33), ('native_internal_stages','measured')):
            rows = copy.deepcopy(self.rows); rows[0][field] = value; self.reject(rows)
        rows = copy.deepcopy(self.rows)
        next(r for r in rows if r['event']=='scope_start')['deadline'] = 2**63
        self.reject(rows)
        rows = copy.deepcopy(self.rows)
        next(r for r in rows if r['event']=='stage_end')['elapsed_ticks'] = -1
        self.reject(rows)
        rows = copy.deepcopy(self.rows)
        next(r for r in rows if r['event']=='native_result')['frequency'] += 1
        self.reject(rows)

    def test_independent_native_binding_is_required_and_immutable(self):
        with self.assertRaises(ValueError): contract.validate(self.rows)
        for field, value in (('first_reason',1), ('first_qpc',42), ('ready',False), ('coverage',False)):
            rows = copy.deepcopy(self.rows)
            next(r for r in rows if r['event']=='native_result')[field] = value
            self.reject(rows)

    def test_closed_schema_privacy_and_old_schema_rejection(self):
        encoded = json.dumps(self.rows)
        for forbidden in ('PRIVATE','SERIAL','instance_path','hardware_ids','exception_message'):
            self.assertNotIn(forbidden, encoded)
            rows = copy.deepcopy(self.rows); rows[-1][forbidden] = 'secret'; self.reject(rows)
        rows = copy.deepcopy(self.rows); rows[0]['schema'] = 'diagnostic-stage-ledger-v1'; self.reject(rows)
        rows = copy.deepcopy(self.rows); rows[0]['origin'] = 'Windows observation'; self.reject(rows)
        rows = copy.deepcopy(self.rows); rows[-1]['recovery_accepted'] = True; self.reject(rows)
        rows = copy.deepcopy(self.rows); rows[-1]['self_close_measured'] = True; self.reject(rows)

    def test_strict_types_sequences_and_json_file_boundaries(self):
        for field, value in (('qpc',True), ('event',[])):
            rows = copy.deepcopy(self.rows); rows[0][field] = value; self.reject(rows)
        rows = copy.deepcopy(self.rows); rows[0]['sequence'] = False
        with self.assertRaises(ValueError): contract.validate(rows, self.native)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'bad.jsonl'
            for text in ('{}', '{"event":1,"event":2}\n', '{"qpc":NaN}\n', '{}\n'*1048576):
                path.write_text(text)
                with self.assertRaises((ValueError,UnicodeError)): contract.load(path)
            with self.assertRaises(ValueError): contract.load(str(path)+'.partial')

    def test_partial_extension_alias_is_rejected(self):
        # Windows resolves this case alias to the producer's uncommitted partial.
        # Enforce the reserved suffix identically on both hosts, even if its
        # provisional footer is a syntactically valid success.
        with tempfile.TemporaryDirectory() as folder:
            for suffix in ('.PARTIAL', '.partial.', '.partial ', '.partial::$DATA'):
                with self.subTest(suffix=suffix):
                    path = Path(folder)/('unpublished'+suffix)
                    if ':' not in path.name:
                        path.write_text(''.join(json.dumps(r)+'\n' for r in self.rows))
                    with self.assertRaises(ValueError): contract.load(path)


if __name__ == '__main__': unittest.main()
