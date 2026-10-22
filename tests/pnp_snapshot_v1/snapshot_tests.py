# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
"""HOST TEST only: raw fake properties, offline files and owned inert processes."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import pnp_snapshot_v1 as harness
import build_pnp_snapshot_v1 as builder
from boundary_cleanup_v2 import Members

HOST=Path(sys.argv.pop(1)).resolve()
INERT=sys.argv.pop(1)


class Clock:
    def __init__(self):self.now=0
    def __call__(self):return self.now
    def pause(self,seconds):self.now+=seconds


class FakeProcess:
    pid=42
    def __init__(self,job,exit_code):self.job=job;self.returncode=exit_code
    def poll(self):
        if self.job.contained and self.returncode is None:self.returncode=125
        return self.returncode


class FakeJob:
    def __init__(self,mode='normal'):
        self.mode=mode;self.contained=False;self.released=False;self.closed=False;self.handle=1
    def release(self,process):self.released=True
    def members(self):
        if self.mode=='unknown' and not self.contained:return Members(None,None,False,234)
        if self.mode=='child' and not self.contained:return Members(1,(43,),True)
        return Members(0,(),True) if self.released else Members(1,(42,),True)
    def close(self):
        self.closed=True;self.handle=None
        if self.mode=='close-error':raise OSError('HOST TEST close error')


class FakeAPI:
    def __init__(self,job,exit_code=0):self.job=job;self.exit_code=exit_code
    def spawn(self,*args):return FakeProcess(self.job,self.exit_code)
    def contain(self,job):job.contained=True


class SnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory()
        cls.base=Path(cls.tmp.name)
        cls.results={}
        for name in sorted(harness.SCENARIOS):
            folder=cls.base/name;folder.mkdir()
            result=subprocess.run([str(HOST),'--host-test',name,str(folder)],capture_output=True,timeout=5)
            if name in ('writer-fault','query-timeout'):
                cls.results[name]=None
            else:
                cls.results[name]=harness.inspect_streams(folder,host_test=True)
            cls.results[name+'-exit']=result.returncode
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def setUp(self):
        self.tmp_case=tempfile.TemporaryDirectory();self.folder=Path(self.tmp_case.name)
    def tearDown(self):self.tmp_case.cleanup()
    def rows(self,name,stream='pnp-v2.jsonl'):
        return [json.loads(x) for x in (self.base/name/stream).read_text().splitlines()]
    def pair(self,name='good'):
        for filename in ('pnp-v2.jsonl','rejection-v1.jsonl'):
            shutil.copyfile(self.base/name/filename,self.folder/filename)
    def fake_session(self,name='good',mode='normal',exit_code=None):
        self.pair(name)
        job=FakeJob(mode);clock=Clock()
        api=FakeAPI(job,self.results[name+'-exit'] if exit_code is None else exit_code)
        result=harness.supervise([str(HOST),'--host-test',name,str(self.folder)],self.folder,api,job,
                                 clock=clock,pause=clock.pause)
        self.assertTrue(job.closed)
        self.assertLessEqual(clock.now,harness.EXECUTION_SECONDS+harness.CLEANUP_SECONDS+.02)
        return result

    def test_complete_synthetic_snapshot_preserves_observer_incompleteness(self):
        r=self.results['good'];self.assertTrue(r['snapshot_ready'])
        self.assertTrue(r['companion']['diagnostic_complete'])
        self.assertFalse(r['original']['collection_complete'])
        self.assertFalse(r['recovery_accepted']);self.assertEqual(self.results['good-exit'],0)
        self.assertEqual(sum(x['event']=='snapshot' for x in self.rows('good')),1)
        self.assertFalse(any(x['event']=='registration' for x in self.rows('good')))
    def test_usb_parent_two_functions_no_hid_still_fails(self):
        r=self.results['missing-hid'];self.assertFalse(r['snapshot_ready'])
        self.assertEqual(r['original_first_failure'],1);self.assertEqual(self.results['missing-hid-exit'],1)
        s=next(x for x in self.rows('missing-hid') if x['event']=='snapshot')
        self.assertEqual((s['usb_parents'],s['intended'],s['hid_children'],s['active_hid']),(1,3,0,0))
        self.assertTrue(r['companion']['diagnostic_complete'])
    def test_full_own_hid_and_active_interfaces_required(self):
        s=next(x for x in self.rows('good') if x['event']=='snapshot')
        self.assertEqual((s['present_qualified_roots'],s['active_usb'],s['active_hid']),(1,1,1))
        self.assertTrue(any(x['event']=='devnode' and x['role']=='hid_child' and x['hardware']=='target_hid' for x in self.rows('good')))
    def test_inactive_history_does_not_add_present_ambiguity(self):
        s=next(x for x in self.rows('historical-root') if x['event']=='snapshot')
        self.assertEqual((s['installed_inactive_roots'],s['roots'],s['present_qualified_roots']),(1,1,1))
        self.assertTrue(s['initial_ready']);self.assertFalse(s['ambiguous'])
    def test_rejected_own_target_other_and_unknown_are_distinct(self):
        for name,expected in [('own-target','target'),('own-other','other_branch'),('own-unknown','unknown')]:
            details=[r for r in self.rows(name,'rejection-v1.jsonl') if r['event']=='rejection']
            self.assertTrue(details);self.assertEqual(details[0]['relation'],expected)
            self.assertFalse(self.results[name]['snapshot_ready'])
            self.assertEqual(details[0]['possible_target'],expected!='other_branch')
    def test_partial_vendor_usage_and_complete_pair_context_do_not_qualify(self):
        for name,relationship in [('partial','partial_only'),('full-partial','full_with_partial_context')]:
            d=next(r for r in self.rows(name,'rejection-v1.jsonl') if r['event']=='rejection')
            self.assertEqual(d['list_relationship'],relationship)
            self.assertEqual(d['original_property_reason'],'invalid_hardware_syntax')
            self.assertFalse(self.results[name]['snapshot_ready'])
    def test_malformed_empty_unsupported_properties(self):
        for name,reason in [('malformed','invalid_multisz_termination'),('empty','missing_hardware_id'),('unsupported','unrecognized_form')]:
            d=next(r for r in self.rows(name,'rejection-v1.jsonl') if r['event']=='rejection')
            self.assertEqual(d['original_property_reason'],reason)
            self.assertFalse(self.results[name]['snapshot_ready'])
    def test_exact_synthetic_aggregate_counts(self):
        s=next(x for x in self.rows('exact-counts') if x['event']=='snapshot')
        self.assertEqual((s['visited'],s['indeterminate'],s['interface_indeterminate']),(285,27,23))
        self.assertEqual({r['reason']:r['count'] for r in s['classification_failures']},
            dict(invalid_hardware_syntax=22,missing_hardware_id=7,unrecognized_form=21))
    def test_detail_limit_keeps_original_counts(self):
        s=next(r for r in self.rows('detail-cap','rejection-v1.jsonl') if r['event']=='snapshot')
        self.assertEqual(s['indeterminate'],80);self.assertEqual(s['details'],64)
        self.assertEqual(s['omitted'],16);self.assertFalse(s['detail_complete'])
        self.assertEqual(self.results['detail-cap']['original_first_failure'],1)
    def test_query_deadline_never_promotes_partial_snapshot(self):
        self.assertEqual(self.results['query-timeout-exit'],1)
        with self.assertRaises(ValueError):harness.inspect_streams(self.base/'query-timeout',host_test=True)
        f=harness.native_failure_candidate(self.base/'query-timeout')
        self.assertEqual(f['domain'],'original');self.assertFalse(f['evidence_validated'])
    def test_missing_partial_and_corrupt_streams_are_separate(self):
        for stream,reason in [('pnp-v2.jsonl','original_stream_invalid'),('rejection-v1.jsonl','companion_stream_invalid')]:
            for fault in ('missing','truncated','corrupt'):
                self.pair()
                p=self.folder/stream
                if fault=='missing':p.unlink()
                elif fault=='truncated':p.write_bytes(p.read_bytes()[:-1])
                else:p.write_bytes(b'{}\n')
                with self.assertRaisesRegex(ValueError,reason):harness.inspect_streams(self.folder,host_test=True)
    def test_host_origin_requires_explicit_reader_option(self):
        with self.assertRaises(ValueError):harness.inspect_streams(self.base/'good')
    def test_one_snapshot_and_readiness_forgery_rejected(self):
        self.pair();p=self.folder/'pnp-v2.jsonl';rows=self.rows('good')
        next(x for x in rows if x['event']=='snapshot')['initial_ready']=False
        p.write_text(''.join(json.dumps(r)+'\n' for r in rows))
        with self.assertRaises(ValueError):
            harness.inspect_streams(self.folder,host_test=True)
    def test_privacy_and_no_notification_or_device_dependencies(self):
        for folder in (self.base/n for n in harness.SCENARIOS):
            for p in folder.glob('*.jsonl'):
                raw=p.read_text()
                self.assertNotIn('HOST-PRIVATE-SERIAL',raw);self.assertNotIn('PRIVATE-OPAQUE-SERIAL',raw)
                self.assertNotIn('DEVINST',raw)
        cmake=(ROOT/'tests/pnp_snapshot_v1/CMakeLists.txt').read_text()
        self.assertIn('pnp-snapshot-host-v1 PRIVATE pnp-snapshot-core-v1',cmake)
        self.assertNotIn('SDL',cmake)
    def test_fake_normal_full_tree_and_root_exit_accounting(self):
        r=self.fake_session();self.assertTrue(r['cleanup']['fully_certified'])
        self.assertIsNone(r['first_failure']);self.assertEqual(r['cleanup']['root_exit_code'],0)
    def test_original_failure_with_valid_companion_remains_failed(self):
        r=self.fake_session('missing-hid')
        self.assertEqual((r['first_failure']['domain'],r['first_failure']['reason']),('original',1))
        self.assertTrue(r['inspection']['companion']['diagnostic_complete'])
        self.assertTrue(r['cleanup']['fully_certified'])
    def test_unexpected_exit_not_success(self):
        r=self.fake_session(exit_code=42)
        self.assertEqual(r['first_failure']['reason'],'unexpected_exit_code')
    def test_root_exit_does_not_prove_child_exit(self):
        r=self.fake_session(mode='child')
        self.assertEqual(r['first_failure']['reason'],'unexpected_child_lifetime')
        self.assertTrue(r['cleanup']['forced_containment']);self.assertFalse(r['cleanup']['fully_certified'])
    def test_unknown_membership_requires_containment(self):
        r=self.fake_session(mode='unknown')
        self.assertEqual(r['first_failure']['reason'],'job_membership_unknown')
        self.assertTrue(r['cleanup']['membership_unknown_seen']);self.assertFalse(r['cleanup']['fully_certified'])
    def test_native_first_failure_survives_writer_and_close_errors(self):
        r=self.fake_session('writer-fault',mode='close-error')
        self.assertEqual((r['first_failure']['domain'],r['first_failure']['reason']),('original',1))
        self.assertFalse(r['first_failure']['evidence_validated'])
        self.assertEqual(r['evidence_errors'],['companion_stream_invalid'])
        self.assertIn('job_close_failed',r['cleanup']['errors'])
    def test_native_cleanup_error_does_not_replace_first_failure(self):
        r=self.fake_session('cleanup-fault')
        self.assertEqual(r['first_failure']['reason'],1)
        self.assertFalse(r['inspection']['original_cleanup_ok'])
    def test_stale_native_paths_do_not_truncate(self):
        self.pair();before=(self.folder/'pnp-v2.jsonl').read_bytes()
        r=subprocess.run([str(HOST),'--host-test','good',str(self.folder)],capture_output=True,timeout=5)
        self.assertNotEqual(r.returncode,0);self.assertEqual((self.folder/'pnp-v2.jsonl').read_bytes(),before)
    def test_stale_companion_prevents_snapshot_queries(self):
        (self.folder/'rejection-v1.jsonl').write_bytes(b'preserve me')
        r=subprocess.run([str(HOST),'--host-test','good',str(self.folder)],capture_output=True,timeout=5)
        self.assertNotEqual(r.returncode,0)
        self.assertEqual((self.folder/'rejection-v1.jsonl').read_bytes(),b'preserve me')
        self.assertEqual(len((self.folder/'pnp-v2.jsonl').read_text().splitlines()),1)
    def test_journal_failure_does_not_certify_evidence(self):
        real=harness.Journal.append
        def broken(journal,event,**fields):
            if event=='summary':journal.failed=True;return False
            return real(journal,event,**fields)
        with patch.object(harness.Journal,'append',broken):r=self.fake_session()
        self.assertFalse(r['journal_ok'])
        self.assertEqual(r['first_failure']['reason'],'journal_write_failed')
    def test_no_default_authorization_or_live_host_bundle_override(self):
        with self.assertRaisesRegex(ValueError,'explicit_authorization_required'):
            harness.run('missing','0'*64,self.folder/'unused')
        with self.assertRaisesRegex(ValueError,'explicit_authorization_required'):
            harness.run('missing','0'*64,self.folder/'unused',authorize=True,host_scenario='good')


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve()
        (self.root/'worker').write_bytes(b'HOST TEST inert binary identity')
        self.bundle=dict(schema=harness.SCHEMA,origin='HOST TEST',source_commit='a'*40,
            baseline='c449a26c288750eaf40c49a41a3a4ef1e635b752',files={'worker':dict(sha256=harness.digest(self.root/'worker'),bytes=(self.root/'worker').stat().st_size)},
            sources=['worker'],executables=dict(host='worker',windows=None,original_pnp=None),
            toolchain=None,protected_inputs=[],policies=harness.POLICIES.copy())
        self.path=self.root/'bundle.json'
    def tearDown(self):self.tmp.cleanup()
    def verify(self):
        self.path.write_text(json.dumps(self.bundle))
        return harness.verify_bundle(self.path,harness.digest(self.path),allow_host_test=True,root=self.root)
    def test_read_only_bundle_verification(self):
        self.verify();before={p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in self.root.iterdir()}
        harness.verify_bundle(self.path,harness.digest(self.path),allow_host_test=True,root=self.root)
        self.assertEqual(before,{p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in self.root.iterdir()})
    def test_source_binary_and_bundle_hash_mismatches(self):
        self.verify();(self.root/'worker').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'input_hash_mismatch'):harness.verify_bundle(self.path,harness.digest(self.path),allow_host_test=True,root=self.root)
        with self.assertRaisesRegex(ValueError,'bundle_hash_mismatch'):harness.verify_bundle(self.path,'0'*64,allow_host_test=True,root=self.root)
    def test_host_bundle_cannot_pass_production_verifier(self):
        self.verify()
        with self.assertRaisesRegex(ValueError,'bundle_origin'):harness.verify_bundle(self.path,harness.digest(self.path),root=self.root)
    def test_malformed_bundle_and_path_escape_rejected(self):
        for path in ('../worker','/worker','C:/worker','a\\worker','a//b'):
            self.bundle['files']={path:dict(sha256='a'*64,bytes=1)}
            with self.assertRaises(ValueError):self.verify()
    def test_policy_and_preservation_metadata_cannot_be_relaxed(self):
        self.bundle['policies']['recovery_accepted']=True
        with self.assertRaisesRegex(ValueError,'policy_changed'):self.verify()
        self.bundle['policies']=harness.POLICIES.copy()
        self.bundle['files']['worker']['mtime_ns']='0'
        with self.assertRaisesRegex(ValueError,'preservation_mtime_mismatch'):self.verify()
    def test_frozen_sources_match_on_checkout(self):
        config=json.loads((ROOT/'config/pnp-snapshot-v1.json').read_text())
        for name,expected in config['frozen_source_lf_sha256'].items():
            self.assertEqual(hashlib.sha256((ROOT/name).read_bytes().replace(b'\r\n',b'\n')).hexdigest(),expected,name)


@unittest.skipUnless(os.name=='nt','Windows inert ownership integration')
class WindowsOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.folder=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def test_real_job_owned_synthetic_snapshot(self):
        from coordinator_windows_v1 import ProcessAPI,WindowsJob
        api=ProcessAPI();job=WindowsJob()
        r=harness.supervise([str(HOST),'--host-test','missing-hid',str(self.folder)],self.folder,api,job)
        self.assertTrue(r['cleanup']['fully_certified'],r)
        self.assertEqual((r['first_failure']['domain'],r['first_failure']['reason']),('original',1))
        self.assertFalse(r['inspection']['snapshot_ready'])
    def test_real_child_process_lifetime_is_contained(self):
        from coordinator_windows_v1 import ProcessAPI,WindowsJob
        api=ProcessAPI();job=WindowsJob()
        r=harness.supervise([INERT,'tree',str(self.folder/'entered'),str(self.folder/'stop')],self.folder,api,job)
        self.assertFalse(r['cleanup']['fully_certified'],r)
        self.assertTrue(r['cleanup']['forced_containment'],r)
        self.assertTrue(r['cleanup']['job_empty_before_close'],r)
    def test_full_attestation_host_run_and_stale_output(self):
        base=ROOT/'build';base.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base) as tmp:
            folder=Path(tmp).resolve();binary=folder/HOST.name;shutil.copyfile(HOST,binary)
            name=binary.relative_to(ROOT).as_posix()
            bundle=dict(schema=harness.SCHEMA,origin='HOST TEST',source_commit='a'*40,
                baseline='c449a26c288750eaf40c49a41a3a4ef1e635b752',files={name:dict(sha256=harness.digest(binary),bytes=binary.stat().st_size)},
                sources=[name],executables=dict(host=name,windows=None,original_pnp=None),toolchain=None,
                protected_inputs=[],policies=harness.POLICIES)
            path=folder/'bundle.json';path.write_text(json.dumps(bundle));digest=harness.digest(path)
            result=harness.run(path,digest,folder/'session',host_scenario='good')
            self.assertIsNone(result['first_failure'],result);self.assertTrue(result['cleanup']['fully_certified'],result)
            before=(folder/'session/pnp-v2.jsonl').read_bytes()
            with self.assertRaises(FileExistsError):harness.run(path,digest,folder/'session',host_scenario='good')
            self.assertEqual((folder/'session/pnp-v2.jsonl').read_bytes(),before)
            binary.write_bytes(b'tampered')
            with self.assertRaisesRegex(ValueError,'input_hash_mismatch'):
                harness.run(path,digest,folder/'must-not-exist',host_scenario='good')
            self.assertFalse((folder/'must-not-exist').exists())


if __name__=='__main__':unittest.main()
