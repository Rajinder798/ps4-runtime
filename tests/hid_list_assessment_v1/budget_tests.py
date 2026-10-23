# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
"""Independently inspect actual frozen native streams under deterministic clocks."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import pnp_coverage_v2 as original
import pnp_rejection_v1 as companion
import pnp_snapshot_v1 as snapshot
DRIVER=Path(sys.argv.pop(1)).resolve()

def event(rows,name): return next(r for r in rows if r['event']==name)

class BudgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory()
        cls.out=Path(os.environ.get('HID_V1_EVIDENCE',cls.tmp.name))/'budget'
        cls.out.mkdir(parents=True,exist_ok=False)
        cls.cases=cls.out/'cases'
        r=subprocess.run([str(DRIVER),'--host-test',str(cls.cases)],capture_output=True,timeout=25)
        (cls.out/'native.stdout').write_bytes(r.stdout);(cls.out/'native.stderr').write_bytes(r.stderr)
        if r.returncode:raise AssertionError('native schedule generation failed; output preserved')
        cls.rows={};cls.diag={};cls.inspections={}
        for folder in cls.cases.iterdir():
            cls.rows[folder.name]=original.load(folder/'pnp-v2.jsonl')
            cls.diag[folder.name]=companion.read(folder/'rejection-v1.jsonl')
            if folder.name!='writer-after-first':cls.inspections[folder.name]=snapshot.inspect_streams(folder,host_test=True)
        (cls.out/'inspections.json').write_text(json.dumps(cls.inspections,indent=2)+'\n',encoding='utf-8')

    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def s(self,n):return event(self.rows[n],'snapshot')
    def d(self,n):return event(self.diag[n],'snapshot')

    def test_all_closed_streams_independently_validate_and_never_claim_recovery(self):
        self.assertEqual(len(self.rows),14)
        for n,r in self.inspections.items():
            self.assertFalse(r['snapshot_ready'],n)
            self.assertFalse(r['recovery_accepted'] or r['observer_collection_complete'],n)
            self.assertEqual(r['original_first_failure'],9 if 'overhead' in n or n=='original-before-companion' else 1,n)

    def test_slow_initial_enumeration_root_discovery_and_property_read_use_detail_budget(self):
        for n in ('slow-enumeration','slow-system-root','slow-qualified-root','slow-property','deadline-before-first'):
            with self.subTest(n=n):
                d=self.d(n);self.assertEqual((d['details'],d['omitted'],d['unknown_ancestry']),(0,50,50))
                self.assertFalse(d['detail_complete'] or d['attribution_complete'])
                self.assertEqual(event(self.diag[n],'first_failure')['reason'],'diagnostic_time_limit')
                self.assertFalse(self.s(n)['over_budget'])
                publication=event(self.diag[n],'snapshot_begin')
                self.assertGreaterEqual(publication['qpc']-publication['begin'],250000)

    def test_slow_parent_acquisition_causes_mid_walk_omission(self):
        d=self.d('slow-parent')
        self.assertEqual((d['details'],d['omitted']),(1,49))
        self.assertFalse(d['attribution_complete'])

    def test_forty_of_fifty_counts_match_known_safe_shape_not_original_raw_records(self):
        d=self.d('forty-of-fifty');s=self.s('forty-of-fifty')
        self.assertEqual((d['details'],d['omitted']),(40,10))
        self.assertEqual((d['node_indeterminate'],d['interface_indeterminate']),(27,23))
        reasons={r['reason']:r['count'] for r in d['reasons']}
        self.assertEqual(reasons,{'invalid_hardware_syntax':22,'missing_hardware_id':7,'unrecognized_form':21})
        self.assertEqual(reasons,{r['reason']:r['count'] for r in s['classification_failures']})
        self.assertFalse(d['detail_complete'] or d['attribution_complete'] or s['initial_ready'])
        self.assertEqual(d['unknown_ancestry'],10)
        self.assertFalse(s['over_budget'])

    def test_original_aggregate_counts_are_unchanged_by_diagnostic_omission(self):
        keys=('visited','intended','unmatched','indeterminate','hid_children','interface_indeterminate',
              'classification_failures','present_qualified_roots','active_usb','active_hid','initial_ready')
        for n in ('slow-enumeration','slow-property','slow-parent','forty-of-fifty'):
            for key in keys:self.assertEqual(self.s(n)[key],self.s('fast')[key],(n,key))
        self.assertEqual((self.d('fast')['details'],self.d('fast')['omitted']),(50,0))

    def test_deadline_after_last_attempt_has_no_final_25ms_check_in_frozen_companion(self):
        # Captures a real accounting limitation; the host test does not fix or hide it.
        n='deadline-after-all-details';d=self.d(n)
        self.assertGreater(d['end']-d['begin'],250000)
        self.assertEqual((d['details'],d['omitted']),(27,0))
        self.assertFalse(any(r['event']=='first_failure' for r in self.diag[n]))
        self.assertTrue(d['detail_complete'] and d['attribution_complete'])
        self.assertFalse(d['over_budget'] or d['original_ready'])

    def test_original_250ms_budget_and_both_failure_orders(self):
        n='companion-before-original-overhead'
        self.assertTrue(self.s(n)['over_budget'])
        self.assertEqual(event(self.rows[n],'first_failure')['reason'],9)
        self.assertLess(event(self.diag[n],'first_failure')['qpc'],event(self.rows[n],'first_failure')['qpc'])
        n='original-before-companion'
        self.assertTrue(self.s(n)['over_budget'])
        self.assertEqual(event(self.diag[n],'first_failure')['reason'],'scan_budget_exceeded')
        self.assertLess(event(self.rows[n],'first_failure')['qpc'],event(self.diag[n],'first_failure')['qpc'])
        self.assertEqual(self.inspections[n]['first_failure']['domain'],'original')
        self.assertEqual(self.inspections['forty-of-fifty']['first_failure']['domain'],'companion')

    def test_later_cleanup_or_storage_error_does_not_overwrite_first_failure(self):
        n='cleanup-after-first'
        self.assertEqual(event(self.rows[n],'first_failure')['reason'],1)
        self.assertEqual(event(self.rows[n],'cleanup')['code'],13)
        self.assertEqual(event(self.diag[n],'first_failure')['reason'],'diagnostic_time_limit')
        self.assertFalse(self.diag[n][-2]['original_cleanup_ok'])
        n='writer-after-first'
        self.assertEqual(event(self.diag[n],'first_failure')['reason'],'diagnostic_time_limit')
        self.assertEqual(sum(r['event']=='first_failure' for r in self.diag[n]),1)
        self.assertNotEqual(self.diag[n][-1]['event'],'summary')
        with self.assertRaises(ValueError):snapshot.inspect_streams(self.cases/n,host_test=True)
        self.assertEqual(event(self.rows[n],'first_failure')['reason'],1)
        self.assertFalse(original.validate(self.rows[n],allow_host_test=True,require_complete=False)['recovery_accepted'])

    def test_fake_qpc_is_repeatable_and_schedule_costs_are_monotonic(self):
        for file in ('pnp-v2.jsonl','rejection-v1.jsonl','schedule.json'):
            self.assertEqual((self.cases/'forty-of-fifty'/file).read_bytes(),
                             (self.cases/'forty-of-fifty-repeat'/file).read_bytes())
        for n in self.rows:
            p=json.loads((self.cases/n/'schedule.json').read_text())
            self.assertEqual((p['origin'],p['frequency'],p['clock_read_step_ticks']),('HOST TEST',10000000,1))
            self.assertFalse(p['live_evidence'])
            previous=p['clock_start']
            for cost in p['costs']:
                self.assertGreaterEqual(cost['begin'],previous)
                self.assertGreaterEqual(cost['end'],cost['begin']);previous=cost['end']
            for rows in (self.rows[n],self.diag[n]):
                self.assertTrue(all(a['qpc']<b['qpc'] for a,b in zip(rows,rows[1:])))

if __name__=='__main__':unittest.main()
