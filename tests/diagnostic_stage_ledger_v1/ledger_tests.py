# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
"""HOST TEST deterministic stages, conservation, corruption and privacy."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import diagnostic_stage_ledger_v1 as ledger
import pnp_coverage_v2 as original
DRIVER=Path(sys.argv.pop(1)).resolve()

class LedgerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory()
        cls.out=Path(os.environ.get('LEDGER_V1_EVIDENCE',cls.tmp.name))/'ledger'
        cls.out.mkdir(parents=True,exist_ok=False);cls.cases=cls.out/'cases'
        r=subprocess.run([str(DRIVER),'--host-test',str(cls.cases)],capture_output=True,timeout=25)
        (cls.out/'native.stdout').write_bytes(r.stdout);(cls.out/'native.stderr').write_bytes(r.stderr)
        if r.returncode:raise AssertionError('native ledger generator failed; output retained')
        cls.inspections={};cls.rows={}
        for case in cls.cases.iterdir():
            cls.rows[case.name]=ledger.read(case/'ledger-v1.jsonl')
            if case.name not in {'ledger-row-limit','writer-after-time-failure'}:
                cls.inspections[case.name]=ledger.inspect(case) if not case.name.startswith('clock-') else ledger.validate(cls.rows[case.name])
        (cls.out/'inspections.json').write_text(json.dumps(cls.inspections,indent=2)+'\n',encoding='utf-8')

    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def report(self,name):return self.inspections[name]
    def s(self,name):return self.report(name)['summary']

    def test_fast_complete_host_scope_and_independent_original_rejection(self):
        r=self.report('fast');s=r['summary']
        self.assertTrue(r['bound_to_original'] and r['diagnostic_complete'])
        self.assertEqual((s['retained'],s['omitted'],s['target'],s['other'],s['unknown']),(50,0,2,48,0))
        self.assertEqual(s['original_reason'],1);self.assertFalse(s['original_ready'] or r['recovery_accepted'])

    def test_all_requested_stages_have_nested_monotonic_brackets(self):
        stages=self.report('fast')['stages'];self.assertEqual({s['stage'] for s in stages},ledger.STAGES)
        self.assertTrue(any(s['parent'] for s in stages))
        for s in stages:self.assertEqual(s['elapsed_ticks'],s['end']-s['begin'])
        # Inclusive durations overlap: summing nested stages is not wall duration.
        self.assertGreater(sum(s['elapsed_ticks'] for s in stages),self.report('fast')['scope']['elapsed_ticks'])

    def test_slow_preparation_consumes_one_shared_budget_before_details(self):
        for name in ('slow-enumeration','slow-system-root','slow-target-discovery','slow-raw-property','before-first-detail'):
            with self.subTest(name=name):
                s=self.s(name);self.assertEqual((s['retained'],s['omitted'],s['unknown']),(0,50,50))
                self.assertEqual(s['diagnostic_reason'],'diagnostic_time_limit')
                self.assertFalse(s['detail_complete'] or s['diagnostic_complete'])

    def test_synchronous_late_return_is_recorded_and_no_new_optional_work_starts(self):
        r=self.report('slow-raw-property')
        late=[s for s in r['stages'] if s['stage']=='raw_property_acquisition' and s['optional'] and s['elapsed_ticks']>=260000]
        self.assertEqual(len(late),1);self.assertEqual(late[0]['remaining_ticks'],0)
        for name,report in self.inspections.items():
            if name.startswith('clock-'):continue
            start=next(r for r in self.rows[name] if r['event']=='scope_start')
            for s in report['stages']:
                if s['optional']:self.assertLess(s['begin'],start['deadline'])
            result=json.loads((self.cases/name/'host-result.json').read_text())
            self.assertEqual(result['optional_started_late'],0)
            self.assertLessEqual(result['source_calls'],32768)

    def test_slow_traversal_and_additional_parent_acquisition(self):
        self.assertEqual(self.s('slow-traversal')['retained'],0)
        self.assertEqual((self.s('slow-parent-acquisition')['retained'],self.s('slow-parent-acquisition')['omitted']),(1,49))

    def test_forty_retained_ten_omitted_and_original_reason_totals(self):
        s=self.s('forty-of-fifty')
        self.assertEqual((s['node'],s['interfaces'],s['retained'],s['omitted'],s['unknown']),(27,23,40,10,10))
        self.assertEqual({r['reason']:r['count'] for r in s['reasons']},{'invalid_hardware_syntax':22,'missing_hardware_id':7,'unrecognized_form':21})
        self.assertFalse(s['detail_complete'] or s['attribution_complete'] or s['diagnostic_complete'])
        self.assertEqual(self.report('forty-of-fifty')['first_domain'],'diagnostic')

    def test_original_aggregates_continue_after_diagnostic_expiry(self):
        for name in ('slow-enumeration','slow-system-root','slow-target-discovery','slow-raw-property','slow-traversal','forty-of-fifty','original-overhead'):
            for key in ('total','node','interfaces','reasons','original_ready'):
                self.assertEqual(self.s(name)[key],self.s('fast')[key],(name,key))
        # Caching a fabricated missing property when an optional read is skipped
        # would change these original reason totals; that is explicitly forbidden.

    def test_final_tail_and_final_publication_expiry_cannot_claim_completeness(self):
        for name in ('final-tail','late-publication'):
            s=self.s(name);self.assertEqual((s['retained'],s['omitted']),(50,0))
            self.assertEqual(s['diagnostic_reason'],'diagnostic_time_limit')
            self.assertFalse(s['detail_complete'] or s['diagnostic_complete'])
            self.assertEqual(self.report(name)['first_domain'],'original')

    def test_exact_deadline_is_exclusive_and_never_reset(self):
        self.assertTrue(self.s('boundary-below')['diagnostic_complete'])
        self.assertEqual(self.report('boundary-below')['scope']['elapsed_ticks'],249999)
        for name,ticks in [('boundary-exact',250000),('boundary-above',250001)]:
            self.assertEqual(self.report(name)['scope']['elapsed_ticks'],ticks)
            self.assertEqual(self.s(name)['diagnostic_reason'],'diagnostic_time_limit')
            self.assertFalse(self.s(name)['diagnostic_complete'])

    def test_original_250ms_overhead_and_independent_domains(self):
        r=self.report('original-overhead');s=r['summary']
        self.assertEqual(s['original_reason'],9);self.assertEqual(s['diagnostic_reason'],'diagnostic_time_limit')
        rows=original.load(self.cases/'original-overhead/pnp-v2.jsonl')
        self.assertTrue(next(x for x in rows if x['event']=='snapshot')['over_budget'])
        self.assertEqual(r['first_domain'],'diagnostic')
        self.assertEqual(self.report('final-tail')['first_domain'],'original')

    def test_unknown_ancestry_stays_potentially_target_related(self):
        for name in ('unknown-root','unknown-target-ancestry'):
            s=self.s(name);self.assertGreater(s['unknown'],0)
            self.assertFalse(s['attribution_complete'] or s['diagnostic_complete'])
            self.assertEqual(s['retained'],50)
        self.assertEqual(self.s('unknown-root')['other'],0)
        self.assertEqual(self.s('unknown-target-ancestry')['target'],0)

    def test_cleanup_and_writer_failure_do_not_replace_first(self):
        s=self.s('cleanup-after-time-failure')
        self.assertEqual(s['diagnostic_reason'],'diagnostic_time_limit');self.assertEqual(s['original_reason'],1)
        self.assertFalse(s['cleanup_ok'])
        self.assertEqual(self.s('cleanup-only-failure')['diagnostic_reason'],'cleanup_failure')
        rows=self.rows['writer-after-time-failure']
        first=[r for r in rows if r['event']=='first_failure' and r['domain']=='diagnostic']
        self.assertEqual(len(first),1);self.assertEqual(first[0]['reason'],'diagnostic_time_limit')
        with self.assertRaises(ValueError):ledger.inspect(self.cases/'writer-after-time-failure')

    def test_caps_and_partial_streams_are_not_validated_as_complete(self):
        with self.assertRaises(ValueError):ledger.inspect(self.cases/'ledger-row-limit')
        original.validate(original.load(self.cases/'ledger-row-limit/pnp-v2.jsonl'),allow_host_test=True,require_complete=False)
        raw=(self.cases/'fast/ledger-v1.jsonl').read_bytes()
        for name,data in [('missing',b''),('partial',raw[:-1]),('no-footer',b'\n'.join(raw.splitlines()[:-1])+b'\n'),('oversize',b'X'*1048577)]:
            path=self.out/(name+'.jsonl');path.write_bytes(data)
            with self.assertRaises(ValueError):ledger.validate(ledger.read(path))

    def test_clock_reversal_exception_and_overflow_are_explicit_unknown_durations(self):
        for name in ('clock-backward','clock-exception','clock-overflow'):
            r=self.report(name);self.assertFalse(r['bound_to_original'] or r['diagnostic_complete'])
            self.assertEqual(r['summary']['diagnostic_reason'],'clock_error')
            self.assertEqual(r['scope']['elapsed_ticks'],-1)
            self.assertFalse(r['scope']['clock_valid'])

    def test_closed_schema_boolean_integer_and_counter_tampering_fail(self):
        rows=self.rows['fast']
        for field,value in [('raw_id','PRIVATE'),('frequency',True),('diagnostic_ms',26)]:
            bad=copy.deepcopy(rows);bad[0][field]=value
            with self.assertRaises(ValueError):ledger.validate(bad)
        for field,value in [('retained',49),('unknown',1),('original_reason',7),('diagnostic_complete',False)]:
            bad=copy.deepcopy(rows);bad[-1][field]=value
            with self.assertRaises(ValueError):ledger.validate(bad)
        bad=copy.deepcopy(self.rows['final-tail']);bad=[r for r in bad if r['event']!='first_failure' or r['domain']!='diagnostic']
        for i,row in enumerate(bad):row['sequence']=i
        with self.assertRaises(ValueError):ledger.validate(bad)
        for position,field,value in [(0,'event',[]),(2,'id',True)]:
            bad=copy.deepcopy(rows);bad[position][field]=value
            with self.assertRaises(ValueError):ledger.validate(bad)
        bad=copy.deepcopy(rows);bad[0]=[]
        with self.assertRaises(ValueError):ledger.validate(bad)

    def test_deterministic_repetition_and_privacy(self):
        for name in ('ledger-v1.jsonl','pnp-v2.jsonl','host-result.json'):
            self.assertEqual((self.cases/'forty-of-fifty'/name).read_bytes(),(self.cases/'repeat-forty-of-fifty'/name).read_bytes())
        for path in self.cases.rglob('*.jsonl'):
            data=path.read_text()
            for forbidden in ('PRIVATE','SERIAL','VID_','PID_','054C','0CE6'):
                self.assertNotIn(forbidden,data)

    def test_duplicate_keys_nonfinite_and_frozen_source_boundary(self):
        for text in ('{"event":"header","event":"summary"}\n','{"n":NaN}\n'):
            path=self.out/'invalid-json.jsonl';path.write_text(text)
            with self.assertRaises(ValueError):ledger.read(path)
        pins=json.loads((ROOT/'config/pnp-snapshot-v1.json').read_text())['frozen_source_lf_sha256']
        for name,digest in pins.items():self.assertEqual(hashlib.sha256((ROOT/name).read_bytes().replace(b'\r\n',b'\n')).hexdigest(),digest,name)
        for flag in ('--live','--run-initial-snapshot','--observe'):
            self.assertEqual(subprocess.run([str(DRIVER),flag],capture_output=True,timeout=5).returncode,2)

if __name__=='__main__':unittest.main()
