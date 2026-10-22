# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
"""Generated HOST-ONLY cases. No SDL init, Windows PnP registration or guest/input."""
import ast
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'tests')]
import arrival_diagnostics_v1 as diag
import build_arrival_probe_v1 as build
from live_v2_diagnostics import FirstFailure
from live_av_v2_tests import samples

def device(ident=1,**fields):
    return dict(dict(instance_id=ident,vendor=1356,product=3302,identity_redacted=False,real_type=6,
                     virtual=False,is_gamepad=True),**fields)
def fixture(*,windows=True,discovery=True,reopen=True):
    """Synthetic trace, explicitly host-test; cannot qualify as hardware evidence."""
    rows=[]
    def add(event,**fields):
        rows.append(dict(schema=diag.SCHEMA,sequence=len(rows),qpc=1000+len(rows)*10,event=event,**fields))
        if event=='raw_sdl_event':
            reason={0x605:'joystick_only',0x606:'joystick_only',0x653:'enumeration_required',0x654:'selected_removal'}[fields['type']]
            add('sdl_event_assessment',instance_id=fields['instance_id'],reason=reason)
    add('header',origin='host-test',process_id=123,qpc_frequency=1000,max_bytes=diag.MAX_BYTES,max_records=diag.MAX_RECORDS)
    add('windows_registration',interface='usb',code=0);add('windows_registration',interface='hid',code=0)
    add('windows_presence',interface='usb',tokens=[1],qpc_begin=1020,qpc_end=1025)
    add('sdl_init',ok=True);add('sdl_clock_anchor',qpc_begin=1040,qpc_end=1045,sdl_ns=7)
    add('sdl_gamepads_query',devices=[device()]);add('candidate_assessment',instance_id=1,reason='candidate')
    add('sdl_open_attempt',instance_id=1);add('sdl_open_result',instance_id=1,ok=True,wired=True)
    add('poll_heartbeat')
    add('raw_sdl_event',type=0x654,instance_id=1,sdl_timestamp_ns=100)
    if windows:add('windows_notification',interface='hid',action='arrival',token=2,received_qpc=1115)
    if discovery:
        add('raw_sdl_event',type=0x605,instance_id=2,sdl_timestamp_ns=200)
        add('raw_sdl_event',type=0x653,instance_id=2,sdl_timestamp_ns=210)
        add('sdl_inventory',qpc_begin=1100,qpc_end=1110,joysticks=[device(2)],gamepads=[device(2)])
        add('sdl_gamepads_query',devices=[device(2)])
        add('candidate_assessment',instance_id=2,reason='candidate')
        if reopen:add('sdl_open_attempt',instance_id=2);add('sdl_open_result',instance_id=2,ok=True,wired=True)
    add('poll_heartbeat');add('windows_unregistration',interface='usb',code=0);add('windows_unregistration',interface='hid',code=0)
    add('cleanup',ok=True);add('summary',status='passed',records=len(rows)+1)
    return rows
def strict(rows):
    opens=[r for r in rows if r['event']=='sdl_open_result']
    return [dict(event='hotplug_opened',qpc=r['qpc']+1,qpc_frequency=1000,instance_id=r['instance_id'],
                 vendor=1356,product=3302,real_type=6,virtual=False,sole=True,connection='wired') for r in opens]+[
            dict(event='hotplug_removed',qpc=1110)]
def witnesses(path,source=None):
    source=samples() if source is None else source
    clock=lambda:10.0
    out=diag.GuestTrace(path,clock=clock,wall=lambda:123,host_test=True)
    out.observe(source,9.0,9.5);out.close()
    return diag.load(path),source
def check(rows):return diag.validate_native(rows,allow_host_test=True)

class ArrivalTests(unittest.TestCase):
    def test_positive_versioned_stream_and_no_acceptance(self):
        native=fixture();result=check(native)
        self.assertEqual(len(result['open_results']),2);self.assertFalse(result['recovery_accepted'])
        with tempfile.TemporaryDirectory() as t:
            guest,s=witnesses(Path(t)/'guest')
            joined=diag.boundaries(native,guest,s,strict(native),allow_host_test=True)
            self.assertTrue(joined['boundary_coverage_complete']);self.assertFalse(joined['recovery_accepted'])
    def test_host_records_rejected_for_hardware(self):
        with self.assertRaisesRegex(ValueError,'not hardware'):diag.validate_native(fixture())
        with tempfile.TemporaryDirectory() as t:
            guest,s=witnesses(Path(t)/'guest')
            with self.assertRaisesRegex(ValueError,'not hardware'):diag.validate_guest(guest,s)
    def test_missing_windows_arrival_not_manufactured(self):
        native=fixture(windows=False)
        with tempfile.TemporaryDirectory() as t:
            guest,s=witnesses(Path(t)/'guest');r=diag.boundaries(native,guest,s,strict(native),allow_host_test=True)
            self.assertFalse(r['windows_arrival_observed']);self.assertFalse(r['boundary_coverage_complete'])
    def test_windows_arrival_without_sdl(self):
        native=fixture(discovery=False)
        with tempfile.TemporaryDirectory() as t:
            guest,s=witnesses(Path(t)/'guest');r=diag.boundaries(native,guest,s,strict(native),allow_host_test=True)
            self.assertTrue(r['windows_arrival_observed']);self.assertEqual(r['raw_sdl_gamepad_added'],[])
            self.assertFalse(r['boundary_coverage_complete'])
    def test_sdl_discovery_without_guest_recovery(self):
        native=fixture()
        with tempfile.TemporaryDirectory() as t:
            guest,s=witnesses(Path(t)/'guest',samples()[:4]);r=diag.boundaries(native,guest,s,strict(native),allow_host_test=True)
            self.assertEqual(r['strict_opened_episodes'],2);self.assertFalse(r['guest_connected_after_disconnect'])
            self.assertFalse(r['boundary_coverage_complete'])
    def test_raw_sdl_without_open_is_distinct(self):
        n=fixture(reopen=False);r=check(n)
        self.assertEqual(len(r['open_results']),1);self.assertTrue(any(e['type']==0x653 for e in r['raw_sdl_events']))
    def test_wrong_virtual_multiple_and_stale_candidate_rejections(self):
        cases=[([device(2,virtual=True)],'virtual_device'),([device(2,vendor=0,product=0,identity_redacted=True)],'wrong_device'),
               ([device(2),device(3)],'device_count'),([device(1)],'stale_instance'),([device(2,real_type=0)],'wrong_device')]
        for inventory,reason in cases:
            with self.subTest(reason=reason):self.assertEqual(diag.candidate(inventory,1,2),reason)
        for fields in (dict(vendor=1),dict(identity_redacted=True),dict(virtual=1),dict(product=False)):
            with self.subTest(fields=fields),self.assertRaises(ValueError):diag.devices([device(**fields)])
    def test_candidate_cannot_overrule_real_identity(self):
        n=fixture();next(r for r in n if r['event']=='candidate_assessment')['reason']='wrong_device'
        with self.assertRaisesRegex(ValueError,'Conflicting'):check(n)
    def test_open_without_candidate_or_fresh_raw_event_rejected(self):
        for change in ('candidate','id','event'):
            n=fixture()
            if change=='candidate':next(r for r in n if r['event']=='candidate_assessment')['reason']='virtual_device'
            elif change=='id':[r for r in n if r['event']=='sdl_open_result'][-1]['instance_id']=1
            else:
                r=next(r for r in n if r['event']=='raw_sdl_event' and r['type']==0x653);r['type']=0x605
            with self.subTest(change=change),self.assertRaises(ValueError):check(n)
    def test_order_and_query_brackets(self):
        for change in ('qpc','received','query','sequence','unknown'):
            n=fixture()
            if change=='qpc':n[-1]['qpc']=1
            elif change=='received':next(r for r in n if r['event']=='windows_notification')['received_qpc']=999999
            elif change=='query':next(r for r in n if r['event']=='sdl_inventory')['qpc_end']=999999
            elif change=='sequence':n[1]['sequence']=False
            else:n[1]['private_path']='forbidden'
            with self.subTest(change=change),self.assertRaises(ValueError):check(n)
    def test_missing_corrupt_truncated_duplicate_nonfinite_and_size(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'evidence'
            with self.assertRaises(FileNotFoundError):diag.load(p)
            for raw in (b'',b'{}',b'no json\n',b'[]\n',b'{"a":1,"a":2}\n',b'{"a":NaN}\n'):
                p.write_bytes(raw)
                with self.subTest(raw=raw),self.assertRaises((ValueError,json.JSONDecodeError)):diag.load(p)
            p.write_bytes(b'{}\n'*10)
            with self.assertRaises(ValueError):diag.load(p,5)
            p.write_text(json.dumps(dict(schema=diag.SCHEMA,max_bytes=2))+'\n')
            with self.assertRaises(ValueError):diag.load(p)
    def test_notification_failure_and_first_failure_preserved(self):
        n=fixture();n=n[:-2]
        for event,fields in [('windows_callback_error',dict(code=1)),('first_failure',dict(reason='callback_invalid')),
                              ('cleanup',dict(ok=False)),('summary',dict(status='failed',records=len(n)+4))]:
            n.append(dict(schema=diag.SCHEMA,sequence=len(n),qpc=1000+len(n)*10,event=event,**fields))
        r=diag.validate_native(n,allow_host_test=True,require_complete=False)
        self.assertEqual(r['first_failure'][0]['reason'],'callback_invalid');self.assertFalse(r['collection_complete'])
        with self.assertRaises(ValueError):check(n)
        n[-1]['status']='passed'
        with self.assertRaises(ValueError):diag.validate_native(n,allow_host_test=True,require_complete=False)
    def test_heartbeat_gap_is_incomplete(self):
        n=fixture();last=max(i for i,r in enumerate(n) if r['event']=='poll_heartbeat')
        for r in n[last:]:r['qpc']+=3000
        with self.assertRaisesRegex(ValueError,'incomplete'):check(n)
    def test_guest_append_raw_values_and_exact_audit_join(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'guest';clock=lambda:10.
            trace=diag.GuestTrace(p,clock=clock,wall=lambda:123,host_test=True)
            trace.observe(samples()[:4],9,9.5);prefix=p.read_bytes()
            trace.observe(samples(),9,9.5);trace.close();self.assertTrue(p.read_bytes().startswith(prefix))
            rows=diag.load(p);self.assertEqual(diag.validate_guest(rows,samples(),allow_host_test=True)['status'],'passed')
            witness=next(r for r in rows if r['event']=='guest_audit_observed');witness['sample']['timestamp']=999
            with self.assertRaises(ValueError):diag.validate_guest(rows,samples(),allow_host_test=True)
    def test_guest_failure_cleanup_and_exhaustion(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'guest';trace=diag.GuestTrace(p,clock=lambda:10.,wall=lambda:123,max_records=5,host_test=True)
            trace.observe(samples()[:1],9,9.5)
            error=ValueError('original_error')
            with self.assertRaisesRegex(ValueError,'budget'):trace.observe(samples(),9,9.5)
            trace.fail(error);trace.fail(RuntimeError('later_error'));trace.close()
            rows=diag.load(p)
            self.assertEqual([r['message'] for r in rows if r['event']=='first_failure'],['original_error'])
            self.assertEqual(diag.validate_guest(rows,samples(),allow_host_test=True)['status'],'failed')
    def test_guest_io_failure_is_not_suppressed(self):
        with tempfile.TemporaryDirectory() as t:
            trace=diag.GuestTrace(Path(t)/'guest',clock=lambda:10.,wall=lambda:123,host_test=True)
            with patch.object(trace.file,'write',side_effect=OSError('append denied')):
                with self.assertRaisesRegex(OSError,'append denied'):trace.observe(samples(),9,9.5)
            trace.fail(OSError('append denied'));trace.close()
    def test_guest_short_write_is_explicit(self):
        with tempfile.TemporaryDirectory() as t:
            trace=diag.GuestTrace(Path(t)/'guest',clock=lambda:10.,wall=lambda:123,host_test=True)
            with patch.object(trace.file,'write',return_value=0):
                with self.assertRaisesRegex(OSError,'Incomplete'):trace.observe(samples(),9,9.5)
            trace.fail(OSError('short append'));trace.close()
    def test_actual_opt_in_cleanup_preserves_first_failure_and_legacy_raises(self):
        tree=ast.parse((ROOT/'tests/live_av_v2_guest_tests.py').read_text())
        physical=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='run_physical')
        callback=next(n for n in physical.body if isinstance(n,ast.FunctionDef) and n.name=='cleanup_step')
        fault=FirstFailure();original=ValueError('first monitor failure');fault.capture(original,'host-test')
        context=dict(arrival_mode=True,arrival_fault=fault,result={})
        exec(compile(ast.Module(body=[callback],type_ignores=[]),'actual_cleanup_callback','exec'),context)
        def cleanup_error():raise OSError('later cleanup failure')
        context['cleanup_step']('observer',cleanup_error)
        seen=[];context['cleanup_step']('guide',lambda:seen.append(True))
        self.assertIs(fault.error,original);self.assertEqual(seen,[True])
        self.assertEqual(context['result']['arrival_cleanup_errors'][0]['step'],'observer')
        first_close=OSError('first guest trace close failure')
        def close_error():raise first_close
        context['arrival_fault']=FirstFailure();context['result']={}
        context['cleanup_step']('guest_trace',close_error)
        context['cleanup_step']('guide',cleanup_error)
        self.assertIs(context['arrival_fault'].error,first_close)
        self.assertEqual([r['step'] for r in context['result']['arrival_cleanup_errors']],['guest_trace','guide'])
        context['arrival_mode']=False
        with self.assertRaisesRegex(OSError,'later cleanup'):context['cleanup_step']('observer',cleanup_error)
    def test_registration_failure_missing_lifecycle_and_native_timestamps(self):
        for change in ('registration','missing_close','raw_time','token_class'):
            n=fixture()
            if change=='registration':n[1]['code']=13
            elif change=='missing_close':n.pop()
            elif change=='raw_time':[r for r in n if r['event']=='raw_sdl_event'][-1]['sdl_timestamp_ns']=1
            else:
                next(r for r in n if r['event']=='windows_notification')['token']=1
            with self.subTest(change=change),self.assertRaises(ValueError):check(n)
    def test_late_record_and_nonfinite_witness_brackets(self):
        n=fixture();n[-1]['event']='poll_heartbeat';n[-1].pop('status');n[-1].pop('records')
        with self.assertRaisesRegex(ValueError,'after diagnostic cleanup'):check(n)
        with tempfile.TemporaryDirectory() as t:
            guest,s=witnesses(Path(t)/'guest');guest[1]['read_begin_qpc']=True
            with self.assertRaises(ValueError):diag.validate_guest(guest,s,allow_host_test=True)
    def test_guest_malformed_clock_missing_close_or_unknown_field(self):
        with tempfile.TemporaryDirectory() as t:
            rows,s=witnesses(Path(t)/'guest')
            for change in ('clock','missing','field','status'):
                x=copy.deepcopy(rows)
                if change=='clock':x[1]['read_end_qpc']=100
                elif change=='missing':x.pop()
                elif change=='field':x[1]['private_device_path']='forbidden'
                else:x[-1]['status']='failed'
                with self.subTest(change=change),self.assertRaises(ValueError):diag.validate_guest(x,s,allow_host_test=True)
    def test_strict_stream_cannot_be_manufactured_from_diagnostics(self):
        n=fixture()
        with tempfile.TemporaryDirectory() as t:
            guest,s=witnesses(Path(t)/'guest')
            for change in ('clock','id','count'):
                original=strict(n)
                if change=='clock':original[0]['qpc_frequency']=999
                elif change=='id':original[-2]['instance_id']=3
                else:original.pop(0)
                with self.subTest(change=change),self.assertRaises(ValueError):diag.boundaries(n,guest,s,original,allow_host_test=True)
    def test_build_attestation_rejects_mismatch(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);engine=root/'engine';engine.write_bytes(b'host-only-engine')
            lib=root/'externals/sdl3/SDL3-static.lib';lib.parent.mkdir(parents=True);lib.write_bytes(b'host-only-library')
            probe=root/'probe';probe.write_bytes(b'host-only-probe')
            sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
            metadata=dict(schema='arrival-build-v1',source_lf_sha256=build.source_hashes(),probe_sha256=sha(probe),
                          engine_sha256=sha(engine),sdl_static_library_sha256=sha(lib),build_script_sha256=sha(Path(build.__file__)))
            p=root/'arrival-build-v1.json';p.write_text(json.dumps(metadata));self.assertEqual(build.verify_probe(probe,engine),metadata)
            for field in ('source_lf_sha256','probe_sha256','engine_sha256','sdl_static_library_sha256','build_script_sha256'):
                wrong=dict(metadata);wrong[field]={} if field=='source_lf_sha256' else '0'*64;p.write_text(json.dumps(wrong))
                with self.subTest(field=field),self.assertRaises(ValueError):build.verify_probe(probe,engine)
    def test_historical_observer_and_acceptance_sources_unchanged(self):
        expected={'tests/dualsense_sdl_probe.cpp':'1c9463f8987cee4a3310b8f5268979d772f7e9e2c64be46612dded8746daaa30'}
        for name,value in expected.items():self.assertEqual(hashlib.sha256((ROOT/name).read_bytes().replace(b'\r\n',b'\n')).hexdigest(),value)
        source=(ROOT/'tests/arrival_probe_v1.cpp').read_text();self.assertIn('#include "dualsense_sdl_probe.cpp"',source)
        tree=ast.parse((ROOT/'tests/live_av_v2_guest_tests.py').read_text())
        physical=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='run_physical')
        self.assertIn('ev.verify_physical',ast.unparse(physical));self.assertIn('ev.verify_confirmations',ast.unparse(physical))
        self.assertIn('if arrival_mode:',ast.unparse(physical))

if __name__=='__main__':unittest.main()
