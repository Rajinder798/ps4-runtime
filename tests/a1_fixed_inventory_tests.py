# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
"""HOST-only Option A fixtures. No processes, COM, endpoints, input or audio."""
import argparse
import contextlib
import copy
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'tools'), str(ROOT/'tests')]
import fixed_render_endpoint as policy
import muted_endpoint as endpoint_module
import live_av_v2_guest_tests as driver

EPOCH = 1_700_000_000_000_000_000


def inventory():
    return dict(schema_version=1, scope='all-active-render', inventory_policy='fixed',
        endpoint_identities=['FAKE-A', 'FAKE-B'],
        default_role_identities=dict(console='FAKE-A', multimedia='FAKE-A', communications='FAKE-A'))


def records(*, complete=True, began=EPOCH):
    rows = [dict(schema_version=2, event='identity', token=i, identity=name)
            for i, name in enumerate(('FAKE-A', 'FAKE-B'))]
    for n, offset in enumerate((10, 50)):
        rows.append(dict(schema_version=2, event='sample', inventory_policy='fixed',
            elapsed_ms=n*40, sample_started_unix_ns=began+offset*1_000_000,
            unix_ns=began+(offset+1)*1_000_000, sample_span_ms=1,
            default_tokens=[0,0,0], endpoints=[dict(token=i, active=True, muted=True, volume=.5+i*.25) for i in range(2)]))
    if complete:
        rows.append(dict(schema_version=2, event='summary', inventory_policy='fixed', status='passed', samples=2))
    return rows


def write_rows(path, rows):
    path.write_text(''.join(json.dumps(row)+'\n' for row in rows), encoding='utf-8')


class A1FixedTests(unittest.TestCase):
    def workspace(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);return Path(t.name)

    def validate(self, rows, **kwargs):
        path=self.workspace()/'report';write_rows(path,rows)
        return policy.validate_fixed_report(path,inventory(),started_ns=EPOCH,
            now_ns=kwargs.get('now_ns',EPOCH+60_000_000))

    def reject(self, rows, **kwargs):
        with self.assertRaises((RuntimeError,ValueError,KeyError,TypeError)):
            self.validate(rows,**kwargs)

    def test_stable_muted_inventory_all_three_roles_and_explicit_scope(self):
        result=self.validate(records())
        self.assertEqual((result['status'],result['schema_version'],result['inventory_policy']),('passed',2,'fixed'))
        self.assertEqual(result['inventory'],['FAKE-A','FAKE-B'])
        self.assertEqual(result['default_role_identities'],inventory()['default_role_identities'])
        self.assertIn('no instantaneous/acoustic',result['observation'])

    def test_each_unmuted_endpoint_fails(self):
        for index in (0,1):
            rows=records();rows[3]['endpoints'][index]['muted']=False
            with self.subTest(endpoint=index):self.reject(rows)

    def test_muted_addition_is_not_an_approved_identity(self):
        rows=records();rows.insert(3,dict(schema_version=2,event='identity',token=2,identity='UNEXPECTED'))
        rows[4]['endpoints'].append(dict(token=2,active=True,muted=True,volume=.5));self.reject(rows)

    def test_expected_identity_missing_in_first_complete_sample_fails(self):
        rows=records();rows.pop(1);rows[1]['endpoints'].pop();self.reject(rows)

    def test_removal_or_unavailable_endpoint_fails(self):
        rows=records();rows[3]['endpoints'].pop();self.reject(rows)
        rows=records();rows[3]['endpoints'][1]['active']=False;self.reject(rows)

    def test_each_default_playback_role_is_pinned(self):
        for role in range(3):
            rows=records();rows[3]['default_tokens'][role]=1
            with self.subTest(role=role):self.reject(rows)

    def test_missing_role_endpoint_or_mute_metadata_fails(self):
        for key in ('default_tokens','endpoints','sample_started_unix_ns','unix_ns','sample_span_ms','inventory_policy'):
            rows=records();rows[3].pop(key)
            with self.subTest(key=key):self.reject(rows)
        for key in ('active','muted','volume','token'):
            rows=records();rows[3]['endpoints'][0].pop(key)
            with self.subTest(endpoint_key=key):self.reject(rows)

    def test_schema1_and_dynamic_schema2_are_not_option_a(self):
        self.reject([dict(elapsed_ms=0,muted=True,volume=.5,same_endpoint=True),dict(status='passed',samples=1)])
        rows=records()
        for row in rows:
            row.pop('inventory_policy',None);row.pop('sample_started_unix_ns',None);row.pop('unix_ns',None);row.pop('sample_span_ms',None)
        self.reject(rows)

    def test_stale_future_replayed_and_overlong_observation_fail(self):
        self.reject(records(),now_ns=EPOCH+1_000_000_000)
        self.reject(records(),now_ns=EPOCH+40_000_000)
        rows=records();rows[3]['elapsed_ms']=rows[2]['elapsed_ms'];self.reject(rows)
        rows=records();rows[3]['sample_started_unix_ns']=EPOCH-1;self.reject(rows)
        rows=records();rows[3]['sample_span_ms']=201;self.reject(rows)
        rows=records();rows[3]['unix_ns']=rows[3]['sample_started_unix_ns']+201_000_000;self.reject(rows)

    def test_observation_gap_fails_even_when_latest_sample_is_fresh(self):
        rows=records();rows[3].update(sample_started_unix_ns=EPOCH+211_000_000,unix_ns=EPOCH+212_000_000,elapsed_ms=201)
        self.reject(rows,now_ns=EPOCH+220_000_000)

    def test_footer_failure_count_trailing_rows_and_no_footer_fail(self):
        self.reject(records(complete=False))
        for key,value in [('status','failed'),('samples',1),('samples',True),('schema_version',True)]:
            rows=records();rows[-1][key]=value
            with self.subTest(key=key,value=value):self.reject(rows)
        rows=records();rows.append(copy.deepcopy(rows[-1]));self.reject(rows)

    def test_failed_native_event_never_accepted_and_hresult_retained(self):
        rows=records(complete=False);rows.append(dict(schema_version=2,event='failure',code_domain='HRESULT',code=-2147467259))
        path=self.workspace()/'report';write_rows(path,rows)
        with self.assertRaises(RuntimeError) as caught:
            policy.FixedRenderEvidence(inventory()).update(path,now_ns=EPOCH+60_000_000)
        self.assertEqual(caught.exception.hresult,-2147467259)

    def test_duplicate_tokens_identities_and_unknown_defaults_fail(self):
        rows=records();rows[3]['endpoints'][1]['token']=0;self.reject(rows)
        rows=records();rows[1]['identity']='FAKE-A';self.reject(rows)
        rows=records();rows[3]['default_tokens']=[0,0,999];self.reject(rows)
        rows=records();rows[3]['endpoints'][0]['token']=True;self.reject(rows)

    def test_volume_drift_nonfinite_out_of_range_and_bool_fail(self):
        for value in (.25,float('nan'),float('inf'),-1,2,True,None):
            rows=records();rows[3]['endpoints'][0]['volume']=value
            with self.subTest(value=str(value)):self.reject(rows)

    def test_duplicate_json_and_incomplete_utf8_or_record_fail(self):
        path=self.workspace()/'report';raw=''.join(json.dumps(x)+'\n' for x in records())
        for data in (raw.replace('"muted": true','"muted": false, "muted": true',1).encode(),raw[:-1].encode(),raw.encode()+b'\xff\n'):
            path.write_bytes(data)
            with self.assertRaises((ValueError,RuntimeError,UnicodeError)):
                policy.validate_fixed_report(path,inventory(),now_ns=EPOCH+60_000_000)

    def test_file_truncation_and_sticky_original_exception(self):
        path=self.workspace()/'report';write_rows(path,records(complete=False));reader=policy.FixedRenderEvidence(inventory())
        reader.update(path,now_ns=EPOCH+60_000_000);path.write_bytes(b'')
        with self.assertRaises(RuntimeError) as caught:reader.update(path,now_ns=EPOCH+60_000_000)
        write_rows(path,records())
        with self.assertRaises(RuntimeError) as again:reader.update(path,final=True,now_ns=EPOCH+60_000_000)
        self.assertIs(again.exception,caught.exception)

    def test_expected_manifest_is_bounded_and_requires_every_role(self):
        for mutate in (lambda x:x.pop('default_role_identities'),lambda x:x['default_role_identities'].pop('console'),
                       lambda x:x['endpoint_identities'].append('FAKE-A'),lambda x:x.update(schema_version=True),
                       lambda x:x['default_role_identities'].update(console='UNKNOWN'),lambda x:x.update(extra=True)):
            value=inventory();mutate(value)
            with self.assertRaises(ValueError):policy.normalize_inventory(value)
        path=self.workspace()/'inventory';path.write_bytes(b'x'*(policy.MANIFEST_BYTES+1))
        with self.assertRaises(ValueError):policy.load_fixed_inventory(path)

    def test_report_size_is_checked_before_reading_payload(self):
        path=self.workspace()/'report'
        with path.open('wb') as stream:stream.truncate(policy.REPORT_BYTES+1)
        with self.assertRaisesRegex(RuntimeError,'bounded size'):
            policy.FixedRenderEvidence(inventory()).update(path)

    def test_caller_cannot_mutate_expected_approval_during_observation(self):
        value=inventory();reader=policy.FixedRenderEvidence(value);value['endpoint_identities'].append('NEW')
        value['default_role_identities']['console']='NEW'
        path=self.workspace()/'report';write_rows(path,records())
        self.assertEqual(reader.update(path,final=True,now_ns=EPOCH+60_000_000)['inventory'],['FAKE-A','FAKE-B'])

    def fake_observer(self, *, legacy=False, kill_failure=False):
        root=self.workspace();clock=[EPOCH];commands=[];children=[]
        class Child:
            returncode=None
            def __init__(self):self.waits=0;self.kills=0
            def poll(self):return self.returncode
            def wait(self,timeout):
                self.waits+=1
                if not legacy:
                    with Path(commands[0][2]).open('a',encoding='utf-8') as f:f.write(json.dumps(records()[-1])+'\n')
                self.returncode=0;clock[0]=EPOCH+70_000_000;return 0
            def kill(self):self.kills+=1;self.returncode=-9
        def popen(command,**kwargs):
            commands.append(command);child=Child();children.append(child)
            rows=([dict(elapsed_ms=n*25,muted=True,volume=.5,same_endpoint=True) for n in range(2)]
                  if legacy else records(complete=False))
            write_rows(Path(command[2]),rows);Path(command[4]).write_text('inert ready',encoding='utf-8');clock[0]=EPOCH+60_000_000
            return child
        return root,clock,commands,children,popen

    def test_actual_wrapper_uses_fixed_command_and_confirms_final_evidence(self):
        root,clock,commands,children,popen=self.fake_observer()
        with patch.object(endpoint_module.subprocess,'Popen',side_effect=popen),patch.object(policy.time,'time_ns',side_effect=lambda:clock[0]):
            with policy.FixedMutedEndpoint(root/'inert',root,all_render=True,fixed_inventory=inventory()) as endpoint:
                digest=endpoint.require_fixed_inventory();self.assertEqual(len(digest),64)
            self.assertTrue(endpoint.cleanup_confirmed);self.assertEqual(endpoint.fixed_summary['status'],'passed')
        self.assertEqual(commands[0][1],'--watch-all-render-fixed');self.assertEqual(children[0].waits,1)

    def test_actual_wrapper_rejects_legacy_before_body_and_cleans_up(self):
        root,clock,commands,children,popen=self.fake_observer(legacy=True)
        with patch.object(endpoint_module.subprocess,'Popen',side_effect=popen),patch.object(policy.time,'time_ns',side_effect=lambda:clock[0]):
            endpoint=policy.FixedMutedEndpoint(root/'inert',root,all_render=True,fixed_inventory=inventory())
            with self.assertRaises(RuntimeError):
                with endpoint:self.fail('Legacy report reached body')
            self.assertTrue(endpoint.cleanup_confirmed);self.assertTrue(endpoint.errors.closed)
        self.assertEqual(children[0].waits,1)

    def test_actual_wrapper_failure_is_sticky_even_if_caller_catches_it(self):
        root,clock,commands,children,popen=self.fake_observer()
        with patch.object(endpoint_module.subprocess,'Popen',side_effect=popen),patch.object(policy.time,'time_ns',side_effect=lambda:clock[0]):
            endpoint=policy.FixedMutedEndpoint(root/'inert',root,all_render=True,fixed_inventory=inventory());endpoint.__enter__()
            clock[0]=EPOCH+500_000_000
            with self.assertRaises(RuntimeError) as first:endpoint.check()
            clock[0]=EPOCH+60_000_000
            with self.assertRaises(RuntimeError) as again:endpoint.check()
            self.assertIs(again.exception,first.exception)
            with self.assertRaises(RuntimeError) as terminal:endpoint.__exit__(None,None,None)
            self.assertIs(terminal.exception,first.exception);self.assertTrue(endpoint.errors.closed)

    def test_legacy_wrapper_cannot_be_used_as_option_a_guard(self):
        endpoint=object.__new__(endpoint_module.MutedEndpoint);endpoint.all_render=False
        with self.assertRaisesRegex(RuntimeError,'Option A'):policy.require_fixed_guard(endpoint)

    def test_wrapper_missing_inventory_rejected_before_any_process(self):
        with patch.object(endpoint_module.subprocess,'Popen') as launched:
            with self.assertRaises(ValueError):
                policy.FixedMutedEndpoint(Path('inert'),self.workspace(),all_render=False,fixed_inventory=inventory())
        launched.assert_not_called()

    def test_wrapper_preserves_original_body_exception_and_cleanup_second(self):
        root,clock,commands,children,popen=self.fake_observer();primary=OSError(5,'FIRST');primary.winerror=1400
        primary.__cause__=LookupError('cause')
        with patch.object(endpoint_module.subprocess,'Popen',side_effect=popen),patch.object(policy.time,'time_ns',side_effect=lambda:clock[0]):
            endpoint=policy.FixedMutedEndpoint(root/'inert',root,all_render=True,fixed_inventory=inventory())
            with self.assertRaises(OSError) as caught:
                with endpoint:
                    endpoint.errors.close();endpoint.errors=Mock();endpoint.errors.close.side_effect=OSError(28,'SECOND')
                    raise primary
        self.assertIs(caught.exception,primary);self.assertEqual(endpoint.cleanup_failures[-1]['errno'],28)
        self.assertTrue(endpoint.cleanup_confirmed)

    def args(self,root,manifest):
        return argparse.Namespace(**{n:root/n for n in ('engine','engine_report','fixture','supervisor')},
            muted_endpoint_observer=root/'inert-helper',output=root/'output',case='no-input-close',cross_key='n',
            physical_scenario=None,sdl_observer=None,physical_test_authorized=False,disconnect_authorized=False,
            reconnect_authorized=False,hotplug_endpoint_protocol_authorized=False,endpoint_inventory=manifest)

    def test_actual_main_fixed_success_is_explicit_and_has_no_false_physical_claim(self):
        root,clock,commands,children,popen=self.fake_observer();manifest=root/'inventory';manifest.write_text(json.dumps(inventory()),encoding='utf-8')
        args=self.args(root,manifest)
        with patch.object(driver.argparse.ArgumentParser,'parse_args',return_value=args),patch.object(driver.sys,'platform','win32'), \
             patch.object(driver.subprocess,'Popen',side_effect=popen),patch.object(policy.time,'time_ns',side_effect=lambda:clock[0]), \
             patch.object(driver,'run_case',return_value=dict(status='passed',inert=True)) as case,contextlib.redirect_stdout(io.StringIO()):
            driver.main()
        result=json.loads((args.output/'summary.json').read_text(encoding='utf-8'))
        self.assertEqual(result['status'],'passed');self.assertTrue(result['endpoint_cleanup_confirmed'])
        self.assertEqual(result['endpoint']['inventory_policy'],'fixed');self.assertFalse(result['physical_input_tested']);case.assert_called_once()

    def test_actual_main_requires_inventory_before_outputs_or_process(self):
        root=self.workspace();args=self.args(root,None)
        with patch.object(driver.argparse.ArgumentParser,'parse_args',return_value=args),patch.object(driver.sys,'platform','win32'), \
             patch.object(driver.subprocess,'Popen') as launch,contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):driver.main()
        launch.assert_not_called();self.assertFalse(args.output.exists())

    def test_actual_main_rejects_bad_inventory_before_outputs_or_process(self):
        root=self.workspace();manifest=root/'inventory';manifest.write_text('{}',encoding='utf-8');args=self.args(root,manifest)
        with patch.object(driver.argparse.ArgumentParser,'parse_args',return_value=args),patch.object(driver.sys,'platform','win32'),patch.object(driver.subprocess,'Popen') as launch:
            with self.assertRaises(ValueError):driver.main()
        launch.assert_not_called();self.assertFalse(args.output.exists())

    def test_actual_case_guard_failure_keeps_first_and_contains_worker_after_stop_error(self):
        root=self.workspace();primary=OSError(5,'original guard');primary.winerror=1400;cause=LookupError('cause');primary.__cause__=cause
        child=Mock(returncode=None,pid=444);child.poll.side_effect=lambda:child.returncode
        child.wait.side_effect=lambda timeout: (_ for _ in ()).throw(subprocess.TimeoutExpired('inert',timeout)) if child.returncode is None else child.returncode
        child.kill.side_effect=lambda:setattr(child,'returncode',-9)
        endpoint=Mock();endpoint.require_fixed_inventory.return_value='a'*64;endpoint.check.side_effect=primary
        args=self.args(root,None)
        def start(*a,**k):(root/'case/session').mkdir(parents=True);return child
        real_touch=Path.touch
        def touch(path,*a,**k):
            if path.name=='stop.request':raise OSError(13,'denied')
            return real_touch(path,*a,**k)
        with patch.object(driver.subprocess,'Popen',side_effect=start),patch.object(Path,'touch',touch):
            with self.assertRaises(OSError) as caught:driver.run_case(args,root,'case',endpoint)
        self.assertIs(caught.exception,primary);self.assertIs(caught.exception.__cause__,cause)
        self.assertEqual(child.wait.call_count,2);child.kill.assert_called_once()
        result=json.loads((root/'case-result.json').read_text(encoding='utf-8'));self.assertEqual(result['status'],'failed')
        self.assertTrue(result['cleanup']['worker_exit_confirmed']);self.assertEqual(result['first_failure']['winerror'],1400)

    def test_actual_case_legacy_guard_fails_before_worker(self):
        root=self.workspace();endpoint=object.__new__(endpoint_module.MutedEndpoint);endpoint.all_render=False
        with patch.object(driver.subprocess,'Popen') as launched:
            with self.assertRaisesRegex(RuntimeError,'Option A'):driver.run_case(self.args(root,None),root,'case',endpoint)
        launched.assert_not_called();self.assertEqual(json.loads((root/'case-result.json').read_text(encoding='utf-8'))['status'],'failed')

    def test_process_control_exceptions_are_not_converted_to_success(self):
        for signal in (KeyboardInterrupt('inert'),SystemExit(77)):
            root,clock,commands,children,popen=self.fake_observer()
            with patch.object(endpoint_module.subprocess,'Popen',side_effect=popen),patch.object(policy.time,'time_ns',side_effect=lambda:clock[0]):
                endpoint=policy.FixedMutedEndpoint(root/'inert',root,all_render=True,fixed_inventory=inventory())
                with self.assertRaises(type(signal)) as caught:
                    with endpoint:raise signal
            self.assertIs(caught.exception,signal);self.assertTrue(endpoint.cleanup_confirmed)

    def test_distinct_role_identities_and_endpoint_order_are_supported(self):
        expected=inventory();expected['default_role_identities'].update(multimedia='FAKE-B',communications='FAKE-B')
        rows=records()
        for row in rows:
            if row.get('event')=='sample':
                row['default_tokens']=[0,1,1];row['endpoints'].reverse()
        path=self.workspace()/'report';write_rows(path,rows)
        result=policy.validate_fixed_report(path,expected,started_ns=EPOCH,now_ns=EPOCH+60_000_000)
        self.assertEqual(result['default_role_identities'],expected['default_role_identities'])

    def test_launch_failure_closes_stderr_and_preserves_original_and_secondary(self):
        primary=OSError(2,'inert launch failure');secondary=OSError(28,'close failed');stream=Mock();stream.close.side_effect=secondary
        real_open=Path.open
        def opened(path,*args,**kwargs):return stream if path.name=='endpoint-stderr.txt' else real_open(path,*args,**kwargs)
        with patch.object(Path,'open',opened),patch.object(policy.subprocess,'Popen',side_effect=primary):
            with self.assertRaises(OSError) as caught:
                policy.FixedMutedEndpoint(Path('inert'),self.workspace(),fixed_inventory=inventory())
        self.assertIs(caught.exception,primary);stream.close.assert_called_once()
        self.assertEqual(primary.endpoint_cleanup_failures[0]['errno'],28)

    def test_actual_main_retains_first_and_bounded_endpoint_cleanup_second(self):
        root,clock,commands,children,popen=self.fake_observer();manifest=root/'inventory';manifest.write_text(json.dumps(inventory()),encoding='utf-8')
        args=self.args(root,manifest);primary=OSError(5,'FIRST');primary.winerror=1400;cause=LookupError('cause');primary.__cause__=cause
        original=driver.MutedEndpoint
        def guard(*a,**kw):
            value=original(*a,**kw);value.errors.close();value.errors=Mock();value.errors.close.side_effect=OSError(28,'SECOND');return value
        with patch.object(driver.argparse.ArgumentParser,'parse_args',return_value=args),patch.object(driver.sys,'platform','win32'), \
             patch.object(driver.subprocess,'Popen',side_effect=popen),patch.object(policy.time,'time_ns',side_effect=lambda:clock[0]), \
             patch.object(driver,'MutedEndpoint',side_effect=guard),patch.object(driver,'run_case',side_effect=primary):
            with self.assertRaises(OSError) as caught:driver.main()
        self.assertIs(caught.exception,primary);self.assertIs(caught.exception.__cause__,cause)
        result=json.loads((args.output/'summary.json').read_text(encoding='utf-8'));self.assertEqual(result['status'],'failed')
        self.assertEqual(result['first_failure']['winerror'],1400)
        self.assertEqual(result['supervision_diagnostics']['secondary_failures'][0]['errno'],28)

    def test_actual_main_both_publication_sinks_fail_without_replacing_first(self):
        root,clock,commands,children,popen=self.fake_observer();manifest=root/'inventory';manifest.write_text(json.dumps(inventory()),encoding='utf-8')
        args=self.args(root,manifest);primary=OSError(5,'FIRST');primary.__cause__=LookupError('cause')
        real_open=Path.open;real_emit=driver.Diagnostics.emit
        def opened(path,*a,**kw):
            if path==args.output/'summary.json':raise PermissionError(13,'inert final result denied')
            return real_open(path,*a,**kw)
        def emitted(obj,event,**fields):
            if event=='final_result_write_failure':raise RuntimeError('inert fallback append failure')
            return real_emit(obj,event,**fields)
        with patch.object(driver.argparse.ArgumentParser,'parse_args',return_value=args),patch.object(driver.sys,'platform','win32'), \
             patch.object(driver.subprocess,'Popen',side_effect=popen),patch.object(policy.time,'time_ns',side_effect=lambda:clock[0]), \
             patch.object(driver,'run_case',side_effect=primary),patch.object(Path,'open',opened),patch.object(driver.Diagnostics,'emit',emitted):
            with self.assertRaises(OSError) as caught:driver.main()
        self.assertIs(caught.exception,primary);self.assertTrue(primary.secondary_persistence_unsuccessful)
        self.assertEqual(primary.result_publication_failure['errno'],13)
        self.assertEqual(primary.secondary_publication_failure['type'],'RuntimeError');self.assertFalse((args.output/'summary.json').exists())

    def test_actual_main_result_loss_retains_cleanup_second_in_fallback(self):
        root,clock,commands,children,popen=self.fake_observer();manifest=root/'inventory';manifest.write_text(json.dumps(inventory()),encoding='utf-8')
        args=self.args(root,manifest);primary=RuntimeError('FIRST observer');primary.observer_exit_code=9
        cause=LookupError('cause');primary.__cause__=cause;original=driver.MutedEndpoint;real_open=Path.open
        def guard(*a,**kw):
            value=original(*a,**kw);value.errors.close();value.errors=Mock();value.errors.close.side_effect=OSError(28,'SECOND');return value
        def opened(path,*a,**kw):
            if path==args.output/'summary.json':raise PermissionError(13,'inert result denied')
            return real_open(path,*a,**kw)
        with patch.object(driver.argparse.ArgumentParser,'parse_args',return_value=args),patch.object(driver.sys,'platform','win32'), \
             patch.object(driver.subprocess,'Popen',side_effect=popen),patch.object(policy.time,'time_ns',side_effect=lambda:clock[0]), \
             patch.object(driver,'MutedEndpoint',side_effect=guard),patch.object(driver,'run_case',side_effect=primary),patch.object(Path,'open',opened):
            with self.assertRaises(RuntimeError) as caught:driver.main()
        self.assertIs(caught.exception,primary);self.assertIs(primary.__cause__,cause)
        markers=[json.loads(x) for x in (args.output/'acceptance-diagnostics.jsonl').read_text(encoding='utf-8').splitlines()]
        marker=next(x for x in markers if x['event']=='final_result_write_failure')
        self.assertEqual(marker['supervision_diagnostics']['secondary_failures'][0]['errno'],28)
        self.assertEqual(marker['acceptance_failure_details']['observer_exit_code'],9)
        self.assertTrue(marker['secondary_persistence_unsuccessful']);self.assertFalse((args.output/'summary.json').exists())

    def test_actual_case_result_loss_retains_cleanup_second_in_fallback(self):
        root=self.workspace();primary=OSError(5,'FIRST');primary.winerror=1400;cause=LookupError('cause');primary.__cause__=cause
        child=Mock(returncode=None,pid=444);child.poll.side_effect=lambda:child.returncode
        child.wait.side_effect=lambda timeout: (_ for _ in ()).throw(subprocess.TimeoutExpired('inert',timeout)) if child.returncode is None else child.returncode
        child.kill.side_effect=lambda:setattr(child,'returncode',-9)
        endpoint=Mock();endpoint.require_fixed_inventory.return_value='a'*64;endpoint.check.side_effect=primary
        real_touch=Path.touch;real_open=Path.open
        def start(*a,**k):(root/'case/session').mkdir(parents=True);return child
        def touch(path,*a,**k):
            if path.name=='stop.request':raise OSError(13,'SECOND stop denied')
            return real_touch(path,*a,**k)
        def opened(path,*a,**kw):
            if path==root/'case-result.json':raise OSError(28,'inert result unavailable')
            return real_open(path,*a,**kw)
        with patch.object(driver.subprocess,'Popen',side_effect=start),patch.object(Path,'touch',touch),patch.object(Path,'open',opened):
            with self.assertRaises(OSError) as caught:driver.run_case(self.args(root,None),root,'case',endpoint)
        self.assertIs(caught.exception,primary);self.assertIs(primary.__cause__,cause)
        self.assertEqual(child.wait.call_count,2);child.kill.assert_called_once()
        markers=[json.loads(x) for x in (root/'case-window.jsonl').read_text(encoding='utf-8').splitlines()]
        marker=next(x for x in markers if x['event']=='final_result_write_failure')
        self.assertEqual(marker['supervision_diagnostics']['secondary_failures'][0]['errno'],13)
        self.assertEqual(marker['acceptance_failure_details']['winerror'],1400)
        self.assertFalse((root/'case-result.json').exists())

    def test_acceptance_failure_descriptor_is_bounded_and_excludes_raw_payload(self):
        for invalid in (True,2**80,'9'):
            error=RuntimeError('FIRST');error.observer_exit_code=invalid;error.observer_failure={'private':'raw endpoint data'}
            result=policy.bounded_acceptance_failure(error,'guard')
            self.assertTrue(result['metadata_unavailable']);self.assertNotIn('observer_exit_code',result)
            self.assertNotIn('observer_failure',result)
        error=OSError(5,'FIRST');error.hresult=-2147467259;error.observer_exit_code=9
        result=policy.bounded_acceptance_failure(error,'guard')
        self.assertEqual(result['hresult'],-2147467259);self.assertEqual(result['observer_exit_code'],9)

    def test_legacy_physical_reader_remains_per_seen_default_only(self):
        import hotplug_endpoint
        rows=[dict(schema_version=1,event='sample',elapsed_ms=n*25,default_token=0,default_changed=False,
                   endpoints=[dict(token=0,available=True,device_state=1,muted=True,volume=.5,same_device_volume=True)]) for n in range(2)]
        rows.append(dict(schema_version=1,event='summary',status='passed',samples=2,default_changes=0,endpoint_identities=1))
        result=hotplug_endpoint.validate_rows(rows)
        self.assertIn('unrelated endpoints are not qualified',result['observation'])
        self.assertNotIn('inventory_policy',result)
        path=self.workspace()/'legacy';write_rows(path,rows)
        with self.assertRaises(RuntimeError):policy.validate_fixed_report(path,inventory(),now_ns=EPOCH+60_000_000)

    def test_observer_exit_remains_first_when_failure_metadata_exists_query_fails(self):
        endpoint=object.__new__(policy.FixedMutedEndpoint);endpoint._fixed_first=None;endpoint.cleanup_failures=[]
        endpoint.child=Mock(returncode=9);endpoint.child.poll.return_value=9;endpoint.report=self.workspace()/'report'
        with patch.object(Path,'exists',side_effect=PermissionError(13,'inert metadata query denied')):
            with self.assertRaises(RuntimeError) as caught:endpoint.check()
        self.assertEqual(caught.exception.observer_exit_code,9)
        self.assertEqual(caught.exception.endpoint_metadata_error,'PermissionError')
        self.assertIs(endpoint._fixed_first,caught.exception)
        self.assertEqual(endpoint.cleanup_failures[0]['errno'],13)
        self.assertEqual(endpoint.cleanup_failures[0]['phase'],'endpoint_failure_metadata')

    def test_missing_or_malformed_inventory_proof_blocks_worker(self):
        for value in (None,True,{},'','g'*64,'a'*63):
            root=self.workspace();endpoint=Mock();endpoint.require_fixed_inventory.return_value=value
            with patch.object(driver.subprocess,'Popen') as launched:
                with self.assertRaisesRegex(RuntimeError,'proof'):
                    driver.run_case(self.args(root,None),root,'case',endpoint)
            launched.assert_not_called()
            self.assertEqual(json.loads((root/'case-result.json').read_text(encoding='utf-8'))['status'],'failed')

    def test_fixed_adapter_never_truncates_existing_stderr(self):
        root=self.workspace();path=root/'endpoint-stderr.txt';path.write_bytes(b'preserve inert evidence')
        with patch.object(policy.subprocess,'Popen') as launched:
            with self.assertRaises(FileExistsError):
                policy.FixedMutedEndpoint(root/'inert',root,fixed_inventory=inventory())
        launched.assert_not_called();self.assertEqual(path.read_bytes(),b'preserve inert evidence')


if __name__=='__main__':unittest.main()
