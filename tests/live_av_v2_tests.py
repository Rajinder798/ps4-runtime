# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
"""Generated host evidence only. No controller, guest or audio endpoint access."""
import ast
import copy
import json
import hashlib
import shutil
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'tools'), str(ROOT/'tests')]
import live_av_v2_evidence as ev
import live_av_v2_contract as contract
import run_live_v2_session as session
import run_homebrew_startup as startup
from videoout_tests import png, unfiltered


def samples():
    rows = []
    for i, (connected, buttons) in enumerate(((1,0),(1,ev.CROSS),(0,ev.CROSS),(0,0),(1,0),(1,ev.CROSS),(1,0))):
        rows.append(dict(sequence=i, handle=1, rc=0, audio_command=int(connected and bool(buttons)),
            observed_us=100000+i*100000, timestamp=100+i if connected else 0, flip=i+1,
            audio_blocks=i*2, raw_buttons=buttons, effective_buttons=buttons if connected else 0,
            raw_axes=[128]*4 if connected else [0]*4, effective_axes=[128]*4,
            connected=connected, count=1 if connected else 0, raw_triggers=[0,0],
            effective_triggers=[0,0], payload_valid=1, state=ev.CONNECTED if connected else ev.DISCONNECTED))
    return rows


def events(rows=None):
    rows = samples() if rows is None else rows
    result = [dict(schema_version=1, elapsed_us=0, event='configured', strict_imports=True),
        dict(schema_version=1, elapsed_us=1, event='imports_checked', phase='entry', unresolved_count=0),
        dict(schema_version=1, elapsed_us=2, event='guest_entry')]
    texts = ['live-av-v2: begin schema=2', 'live-av-v2: ready schema=2']
    for s in rows:
        texts.append('live-av-v2: sample={sequence} handle={handle} rc={rc} command={audio_command} '
            'observed={observed_us} timestamp={timestamp} flip={flip} audio_blocks={audio_blocks} '
            'raw_buttons={raw_buttons} effective_buttons={effective_buttons} raw_axes={ra} '
            'effective_axes={ea} connected={connected} count={count} raw_triggers={rt} '
            'effective_triggers={et} valid={payload_valid} state={state}'.format(**s,
                ra=','.join(map(str,s['raw_axes'])), ea=','.join(map(str,s['effective_axes'])),
                rt=','.join(map(str,s['raw_triggers'])), et=','.join(map(str,s['effective_triggers']))))
    return result+[dict(schema_version=1,elapsed_us=3+i,event='guest_output',text=t) for i,t in enumerate(texts)]


def transport():
    return dict(reason='exited',exit_code=0,forced_termination=False,active_before_cleanup=0,
        tree_cleanup=True,root_exit_verified=True,owner_watch_verified=True,lifetime='until_exit',root_pid=123)


class V2Tests(unittest.TestCase):
    @staticmethod
    def physical_recorder(root):
        # Compile the actual nested callback in isolation. No GUI, native hook,
        # process or guest boundary is entered by these recorder regressions.
        path=ROOT/'tests/live_av_v2_guest_tests.py'
        tree=ast.parse(path.read_text(encoding='utf-8'))
        physical=next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='run_physical')
        emit=next(node for node in physical.body if isinstance(node,ast.FunctionDef) and node.name=='emit')
        namespace=dict(root=root,json=json,time=SimpleNamespace(perf_counter=lambda:123.5))
        exec(compile(ast.Module(body=[emit],type_ignores=[]),str(path),'exec'),namespace)
        return namespace['emit']

    def test_physical_recorder_preserves_diagnostic_timestamps_and_appends(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);emit=self.physical_recorder(root)
            source=dict(qpc_seconds=111.25,unix_ns=1792600000000000000,scoped_pid=10,window_handle=20)
            before=copy.deepcopy(source)
            for name in ('owned_window_diagnostics_started','owned_window_identity_snapshot',
                         'owned_window_state','owned_window_identity_failure','owned_window_diagnostics_closed'):
                prefix=(root/'window.jsonl').read_bytes() if (root/'window.jsonl').exists() else b''
                emit(name,**source)
                self.assertTrue((root/'window.jsonl').read_bytes().startswith(prefix))
                record=json.loads((root/'window.jsonl').read_text().splitlines()[-1])
                self.assertEqual(record,dict(source,event=name))
            emit('owner_metadata_pending')
            record=json.loads((root/'window.jsonl').read_text().splitlines()[-1])
            self.assertEqual(record,dict(event='owner_metadata_pending',qpc_seconds=123.5))
            self.assertEqual(source,before)
            self.assertEqual(len((root/'window.jsonl').read_text().splitlines()),6)

    def test_physical_recorder_cleanup_does_not_mask_failure_and_io_is_explicit(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);emit=self.physical_recorder(root)
            original=RuntimeError('original diagnostic startup failure')
            try:
                try:raise original
                finally:emit('owned_window_diagnostics_closed',qpc_seconds=111.25,unix_ns=123)
            except RuntimeError as error:self.assertIs(error,original)
            else:self.fail('Original error was hidden by cleanup')
            prefix=(root/'window.jsonl').read_bytes()
            with patch.object(Path,'open',side_effect=PermissionError('host-only append failure')),\
                self.assertRaisesRegex(PermissionError,'append failure'):
                emit('owned_window_diagnostics_started',qpc_seconds=111.25)
            self.assertEqual((root/'window.jsonl').read_bytes(),prefix)
            with self.assertRaises(TypeError):
                emit('non_json_diagnostic',qpc_seconds=111.25,invalid=object())
            self.assertEqual((root/'window.jsonl').read_bytes(),prefix)

    def test_raw_effective_journal_and_distinct_schema(self):
        s=samples(); self.assertTrue(ev.progress(events())['running_observed'])
        raw=ev.HEADER+b''.join(map(ev.pack_record,s))
        self.assertEqual(ev.verify_records(raw,s)['bytes_verified'],16+72*7)
        self.assertEqual(s[2]['raw_buttons'],ev.CROSS)
        self.assertEqual(s[2]['effective_buttons'],0)
        for bad in (raw[:-1], b'PADHP1\0\0'+raw[8:], raw[:8]+struct.pack('<I',1)+raw[12:],raw+b'\0'):
            with self.assertRaises(ValueError):ev.verify_records(bad,s)

    def test_api_invalid_stale_backwards_and_reopened_handle_rejection(self):
        for case in ('api','positive-api','zero','stale','backwards','handle','effective','valid','flip','time','blocks','sequence'):
            s=samples()
            if case=='api':s[2]['rc']=-1
            elif case=='positive-api':s[2]['rc']=1
            elif case=='zero':s[4]['timestamp']=0
            elif case=='stale':s[4]['timestamp']=s[1]['timestamp']
            elif case=='backwards':s[1]['timestamp']=99
            elif case=='handle':s[4]['handle']=2
            elif case=='effective':s[2]['effective_buttons']=ev.CROSS
            elif case=='valid':s[2]['payload_valid']=0
            elif case=='flip':s[2]['flip']=0
            elif case=='time':s[2]['observed_us']=1
            elif case=='blocks':s[4]['audio_blocks']=0
            else:s[3]['sequence']=2
            with self.subTest(case=case),self.assertRaises(ValueError):ev.validate_samples(s)

    def test_actual_error_bytes_preserved_but_never_success(self):
        s=samples()[:3];s[-1].update(rc=-1,payload_valid=0,state=ev.API_ERROR,flip=0)
        self.assertTrue(ev.validate_samples(s)['fatal_report'])
        self.assertTrue(ev.progress(events(s),allow_failure=True)['failure'])
        with self.assertRaises(ValueError):ev.progress(events(s))
        ev.verify_records(ev.HEADER+b''.join(map(ev.pack_record,s)),s)
        with self.assertRaises(ValueError):ev.expected_pixels([0,1,2,3],s[-1])

    def test_full_pixel_wrong_missing_stale_and_corrupt_rejection(self):
        s=samples();palette=[0,1,2,3]
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'image.png'
            with self.assertRaises(ValueError):ev.verify_image(p,palette,s[0])
            p.write_bytes(png(unfiltered(ev.expected_pixels(palette,s[2]))))
            self.assertEqual(ev.verify_image(p,palette,s[2])['pixels_verified'],230400)
            for row,colors in ((s[0],palette),(s[2],[1,2,3,4])):
                with self.assertRaises(ValueError):ev.verify_image(p,colors,row)
            p.write_bytes(p.read_bytes()[:-5])
            with self.assertRaises(ValueError):ev.verify_image(p,palette,s[2])

    def test_exhaustion_and_no_fixed_research_record_limit(self):
        s=[]
        for i in range(4097):
            r=copy.deepcopy(samples()[0]);r.update(sequence=i,flip=i+1,observed_us=1+i*16000,timestamp=1+i,audio_blocks=i)
            s.append(r)
        ev.validate_samples(s)
        self.assertEqual(16+72*ev.MAX_RECORDS,4194304-(4194304-16)%72)
        self.assertLessEqual(16+72*ev.MAX_RECORDS,ev.MAX_JOURNAL_BYTES)
        with self.assertRaises(ValueError):ev.verify_records(b'x'*(ev.MAX_JOURNAL_BYTES+1),s)
        self.assertEqual(72*60*60,259200) # bytes/minute at hypothetical 60 records/sec, not measured FPS
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'audit';p.write_bytes(b'x'*(startup.MAX_AUDIT_BYTES+1))
            with self.assertRaises(ValueError):startup.read_events(p)

    def test_audit_log_capacity_and_evidence_coupling_boundary(self):
        sample_row = samples()[:1]
        sample_event = events(sample_row)[-1]
        line_bytes = len((json.dumps(sample_event) + '\n').encode('utf-8'))
        self.assertGreater(line_bytes, 300)
        self.assertLess(line_bytes, 400)
        max_audit_samples = startup.MAX_AUDIT_BYTES // line_bytes
        self.assertGreater(max_audit_samples, 10000)
        self.assertLess(max_audit_samples, 14000)
        saturation_seconds = max_audit_samples / 60.0
        self.assertGreater(saturation_seconds, 180.0)
        self.assertLess(saturation_seconds, 240.0)
        journal_seconds = ev.MAX_RECORDS / 60.0
        self.assertGreater(journal_seconds, 900.0)
        self.assertGreater(ev.MAX_RECORDS, max_audit_samples * 4)
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / 'startup-audit.jsonl'
            p.write_bytes(b'{"schema_version":1}\n' * (startup.MAX_AUDIT_BYTES // 20 + 1))
            self.assertGreater(p.stat().st_size, startup.MAX_AUDIT_BYTES)
            with self.assertRaisesRegex(ValueError, 'Strict audit exceeds size limit'):
                startup.read_events(p)
        full_samples = [copy.deepcopy(samples()[0]) for _ in range(20)]
        for i, s in enumerate(full_samples):
            s.update(sequence=i, flip=i + 1, observed_us=100000 + i * 16000, timestamp=100 + i, audio_blocks=i)
        ev.validate_samples(full_samples)
        sparse_samples = [s for s in full_samples if s['sequence'] % 2 == 0]
        with self.assertRaisesRegex(ValueError, 'Hotplug schema, range, payload validity or sequence mismatch'):
            ev.validate_samples(sparse_samples)
        raw_full_journal = ev.HEADER + b''.join(map(ev.pack_record, full_samples))
        renumbered_sparse = copy.deepcopy(sparse_samples)
        for i, s in enumerate(renumbered_sparse):
            s.update(sequence=i, flip=i + 1)
        ev.validate_samples(renumbered_sparse)
        with self.assertRaisesRegex(ValueError, 'Hotplug guest binary/header/reserved bytes and strict audit disagree'):
            ev.verify_records(raw_full_journal, renumbered_sparse)

    def test_continuity_and_disconnected_progress(self):
        s=samples();s[3]['observed_us']=s[2]['observed_us']+5000000
        ev.verify_disconnected_progress(s[2],s[3])
        for field,value in (('observed_us',s[2]['observed_us']+4999999),('flip',s[2]['flip']),('audio_blocks',s[2]['audio_blocks']),('state',ev.CONNECTED)):
            r=dict(s[3]);r[field]=value
            with self.assertRaises(ValueError):ev.verify_disconnected_progress(s[2],r)
        ev.verify_continuity(samples())
        with self.assertRaises(ValueError):ev.verify_continuity(s)

    def test_strict_transport_never_converts_forced_cleanup_to_success(self):
        ev.verify_transport(transport())
        for field,value in (('reason','owner_exited'),('exit_code',1),('forced_termination',True),
            ('active_before_cleanup',1),('tree_cleanup',False),('root_exit_verified',False),
            ('owner_watch_verified',False),('lifetime','bounded'),('root_pid',0)):
            r=transport();r[field]=value
            with self.assertRaises(ValueError):ev.verify_transport(r)

    def test_real_runner_with_inert_host_boundaries_and_binary_journal(self):
        # Executes actual runner coordination; the fake supervisor never launches anything.
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);out=root/'out';out.mkdir()
            paths={k:root/k for k in ('engine','engine_report','fixture','supervisor')}
            for p in paths.values():p.write_text('host dummy')
            def supervise(supervisor,command,work,timeout,poll,*,on_started,environment,diagnostics):
                on_started(999)
                owner=(out/'session-owner.json').read_bytes()
                (work/'startup-audit.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events()))
                d=work/'user/data';d.mkdir(exist_ok=True)
                (d/'live-av-v2.bin').write_bytes(ev.HEADER+b''.join(map(ev.pack_record,samples())))
                for _ in range(20):self.assertFalse(poll())
                self.assertEqual((out/'session-owner.json').read_bytes(),owner)
                return self.result
            for bad in (False,True):
                if bad:
                    out=root/'bad';out.mkdir()
                self.result=transport()
                if bad:self.result['forced_termination']=True
                original_publish=session.publish_status
                publications=[]
                def owner_only(path,snapshot):
                    self.assertEqual(path.name,'session-owner.json')
                    self.assertFalse(path.exists())
                    publications.append(path)
                    original_publish(path,snapshot)
                with patch.object(session.sys,'platform','win32'),patch.object(session.platform,'machine',return_value='AMD64'),\
                    patch.object(contract,'verify_inputs',return_value={}),patch.object(startup,'supervise',side_effect=supervise),\
                    patch.object(session,'publish_status',side_effect=owner_only):
                    code,r=session.run_session(**paths,output=out)
                self.assertEqual(publications,[out/'session-owner.json'])
                self.assertEqual(code,int(bad));self.assertEqual(r['normal_exit_verified'],not bad)
                self.assertFalse(r['independent_av_qualification_performed'])
                self.assertFalse(r['automated_gameplay_input_sent'])
                self.assertFalse((out/'session-status.json').exists())
                self.assertFalse(list(out.glob('*.tmp')))
                import live_av_v2_guest_tests as driver
                state=driver.optional_progress(out,lambda *a,**k:None)
                self.assertTrue(state['running_observed']);self.assertEqual(len(state['samples']),7)

    def test_runner_first_failure_precedes_cleanup_and_owner_is_write_once(self):
        for mode in ('audit','owner-collision','missing-audit'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as t:
                root=Path(t);out=root/'out';out.mkdir()
                paths={k:root/k for k in ('engine','engine_report','fixture','supervisor')}
                for p in paths.values():p.write_text('inert host dummy')
                def supervise(supervisor,command,work,timeout,poll,*,on_started,environment,diagnostics):
                    on_started(999)
                    if mode=='owner-collision':
                        before=(out/'session-owner.json').read_bytes()
                        try:on_started(1000)
                        finally:self.assertEqual((out/'session-owner.json').read_bytes(),before)
                    else:
                        if mode=='audit':(work/'startup-audit.jsonl').write_text('not-json\n')
                        with self.assertRaises(ValueError):poll()
                        diagnostic=[json.loads(s) for s in (out/'session-diagnostics.jsonl').read_text().splitlines()]
                        self.assertEqual(diagnostic[-1]['event'],'first_failure')
                        # No observation/publication after the first fault, even
                        # when the shared supervisor invokes its monitor again.
                        with patch.object(ev,'progress',side_effect=AssertionError('reentered validation')):
                            self.assertTrue(poll())
                        (work/'startup-audit.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events()))
                        (work/'supervisor.json').write_text(json.dumps(dict(transport(),reason='requested',forced_termination=True)))
                        raise RuntimeError('secondary supervision cleanup failure')
                with patch.object(session.sys,'platform','win32'),patch.object(session.platform,'machine',return_value='AMD64'),\
                    patch.object(contract,'verify_inputs',return_value={}),patch.object(startup,'supervise',side_effect=supervise),\
                    patch.object(session.time,'monotonic',side_effect=[0,31]):
                    code,result=session.run_session(**paths,output=out)
                self.assertEqual(code,1);self.assertEqual(result['status'],'failed')
                self.assertEqual(result['error'],result['first_failure']['message'])
                self.assertNotIn('secondary supervision',result['error'])
                if mode!='owner-collision':
                    self.assertEqual(result['supervision_error'],'secondary supervision cleanup failure')
                    self.assertTrue(result['transport']['forced_termination'])
                    self.assertEqual(result['first_failure']['phase'],'guest_audit_monitor')
                else:self.assertEqual(result['first_failure']['phase'],'immutable_owner_creation')
                self.assertFalse((out/'session-status.json').exists())

    def test_owner_and_original_audit_fail_explicitly_without_snapshot(self):
        import live_av_v2_guest_tests as driver
        with tempfile.TemporaryDirectory() as t:
            out=Path(t);(out/'session').mkdir();owner=out/'session-owner.json';audit=out/'session/startup-audit.jsonl'
            self.assertIsNone(driver.optional_progress(out,lambda *a,**k:None))
            for value in (None,[],1,{},dict(schema_version=True,supervisor_pid=2),
                          dict(schema_version=1,supervisor_pid=0),dict(schema_version=1,supervisor_pid=2,extra=True)):
                owner.write_text(json.dumps(value))
                with self.subTest(value=value),self.assertRaises(ValueError):driver.optional_progress(out,lambda *a,**k:None)
            owner.write_text('{broken')
            with self.assertRaises(ValueError):driver.optional_progress(out,lambda *a,**k:None)
            owner.write_text(json.dumps(dict(schema_version=1,supervisor_pid=2)))
            # Absent/incomplete startup evidence never grants readiness. The
            # runner and driver enforce their existing readiness budgets.
            self.assertFalse(driver.optional_progress(out,lambda *a,**k:None)['running_observed'])
            for text in ('broken\n',json.dumps(dict(event='guest_entry'))+'\n',
                         ''.join(json.dumps(e)+'\n' for e in events(samples()[:1]))+'{}\n'):
                audit.write_text(text)
                with self.assertRaises(ValueError):driver.optional_progress(out,lambda *a,**k:None)
            audit.write_text(''.join(json.dumps(e)+'\n' for e in events()))
            self.assertTrue(driver.optional_progress(out,lambda *a,**k:None)['running_observed'])

    def test_diagnostics_are_append_only_bounded_and_io_failure_is_explicit(self):
        from live_v2_diagnostics import Diagnostics,FirstFailure
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'diagnostics';d=Diagnostics(p);d.MAX_RECORDS=2
            d.emit('one');prefix=p.read_bytes();d.emit('two')
            self.assertTrue(p.read_bytes().startswith(prefix))
            before=p.read_bytes()
            with self.assertRaises(ValueError):d.emit('overflow')
            self.assertEqual(p.read_bytes(),before)
            with self.assertRaises(FileExistsError):Diagnostics(p)
            p=Path(t)/'byte-limit';d=Diagnostics(p);d.MAX_BYTES=5
            with self.assertRaises(ValueError):d.emit('too-large')
            self.assertEqual(p.read_bytes(),b'')
            with patch.object(Path,'open',side_effect=PermissionError('host I/O denial')),self.assertRaises(PermissionError):
                d.MAX_BYTES=1000;d.emit('io-failure')
            f=FirstFailure();first=OSError('original publication failure')
            first.winerror=1175 # Injected host exception, not an OS reproduction.
            f.capture(first,'publication',Mock(side_effect=PermissionError('diagnostic write failed')))
            f.capture(RuntimeError('cleanup later'),'cleanup')
            r={};f.update_result(r)
            self.assertIs(f.error,first);self.assertEqual(r['error'],str(first))
            self.assertEqual(r['first_failure']['winerror'],1175)
            self.assertEqual(r['first_failure_diagnostic_error'],'diagnostic write failed')
            d=Diagnostics(Path(t)/'final-write-failure')
            for prior in (False,True):
                f=FirstFailure()
                if prior:f.capture(ValueError('original cause'),'audit',d.emit)
                with patch.object(Path,'write_text',side_effect=PermissionError('final write denied')),\
                    self.assertRaisesRegex((ValueError,PermissionError),'original cause' if prior else 'final write denied'):
                    f.write_result(Path(t)/'result',{},d.emit)
            logged=[json.loads(s)['event'] for s in d.path.read_text().splitlines()]
            self.assertEqual(logged,['first_failure','first_failure','final_result_write_failure'])

    def test_requested_key_post_order_and_guest_neutral_are_separate(self):
        import live_av_v2_guest_tests as driver
        for key in ('n','g'):
            args=SimpleNamespace(cross_key=key,engine=Path('unused'));owned=SimpleNamespace(pid=10,window=11)
            log=[];actions=[]
            def emit(event,**fields):log.append(dict(event=event,**fields))
            def post(*args):
                log.append(dict(event='actual_host_api_call'))
                return dict(root_pid=10,key=args[2],down=args[3])
            with patch.object(driver.windows,'send_key',side_effect=post):
                driver.post_key(args,9,owned,True,actions,emit)
                driver.post_key(args,9,owned,False,actions,emit)
            self.assertEqual([e['event'] for e in log],['keyboard_action_requested','actual_host_api_call','keyboard_action_posted']*2)
            self.assertEqual([e['down'] for e in log if e['event']=='keyboard_action_requested'],[True,False])
            self.assertEqual([e['action_index'] for e in log if e['event']=='keyboard_action_requested'],[0,1])
            self.assertEqual(len(actions),2)
            log=[];actions=[]
            with patch.object(driver.windows,'send_key',side_effect=OSError('post denied')),self.assertRaises(OSError):
                driver.post_key(args,9,owned,True,actions,emit)
            self.assertEqual([e['event'] for e in log],['keyboard_action_requested']);self.assertEqual(actions,[])
            log=[]
            cursor,previous=driver.observe_guest_transitions(samples(),0,None,emit)
            self.assertEqual(cursor,7)
            self.assertEqual(driver.observe_guest_transitions(samples(),cursor,previous,emit),(cursor,previous))
            self.assertTrue(all(e['event']=='guest_input_observed' for e in log))
            self.assertEqual(log[-1]['raw_buttons'],0) # No host release is inferred.

    def test_failed_driver_keeps_key_capture_first_error_and_cleanup_separately(self):
        import live_av_v2_guest_tests as driver
        for post_fails in (False,True):
            with self.subTest(post_fails=post_fails),tempfile.TemporaryDirectory() as t:
                root=Path(t);out=root/'connected-input';work=out/'session'
                (work/'user/screenshots').mkdir(parents=True);(work/'app').mkdir()
                (work/'user/screenshots/neutral.png').write_bytes(b'inert host placeholder')
                (work/'app/palette.bin').write_bytes(bytes(range(4)))
                (work/'startup-audit.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events(samples()[:1])))
                forced=dict(transport(),reason='requested',forced_termination=True)
                (work/'supervisor.json').write_text(json.dumps(forced))
                (out/'session-result.json').write_text(json.dumps(dict(status='failed',error='independent runner error')))
                process=Mock(returncode=None);process.poll.side_effect=lambda:process.returncode
                process.wait.side_effect=lambda **kw:setattr(process,'returncode',1)
                owned=Mock(pid=123,window=456)
                owned.poll.side_effect=[None,None,None,RuntimeError('first ownership failure')]
                owned.summary.return_value=dict(samples=3);owned.close.side_effect=OSError('secondary observer cleanup')
                args=SimpleNamespace(**{k:Path('inert') for k in ('engine','engine_report','fixture','supervisor')},cross_key='g')
                status=dict(supervisor_pid=99,**ev.progress(events(samples()[:1])))
                posted=dict(root_pid=123,key='cross-g',down=True)
                with patch.object(driver.subprocess,'Popen',return_value=process),\
                    patch.object(driver,'optional_progress',return_value=status),patch.object(driver.time,'monotonic',side_effect=[0,0,4,5]),\
                    patch.object(driver.time,'sleep'),patch.object(driver.windows,'_owned_window'),patch.object(driver,'OwnedWindowTrace',return_value=owned),\
                    patch.object(driver.windows,'request_screenshot'),patch.object(driver,'readback_ready',return_value=True),\
                    patch.object(ev,'image_sequence',return_value=0),patch.object(ev,'verify_image',return_value=dict(sequence=0)),\
                    patch.object(driver.windows,'send_key',side_effect=OSError('first post failure') if post_fails else None,return_value=posted),\
                    self.assertRaisesRegex((RuntimeError,OSError),'first post failure' if post_fails else 'first ownership failure'):
                    driver.run_case(args,root,'connected-input',Mock())
                r=json.loads((root/'connected-input-result.json').read_text())
                self.assertEqual(r['status'],'failed');self.assertEqual(len(r['images']),1)
                self.assertEqual(len(r['external_keyboard_actions']),0 if post_fails else 1)
                self.assertEqual(r['cleanup_errors'][0]['error'],'secondary observer cleanup')
                self.assertEqual(r['runner_outcome']['error'],'independent runner error')
                self.assertEqual(r['cleanup_transport'],forced)
                self.assertTrue(r['cleanup']['stop_requested']);process.kill.assert_not_called()
                log=[json.loads(s) for s in (root/'connected-input-window.jsonl').read_text().splitlines()]
                names=[s['event'] for s in log]
                self.assertLess(names.index('first_failure'),names.index('cleanup_outcome'))
                self.assertEqual([e['down'] for e in log if e['event']=='keyboard_action_requested'],[True])

    def test_driver_missing_owner_has_bounded_failure_without_input_or_launch(self):
        import live_av_v2_guest_tests as driver
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);args=SimpleNamespace(**{k:Path('inert') for k in ('engine','engine_report','fixture','supervisor')},cross_key='g')
            process=Mock(returncode=None);process.poll.side_effect=lambda:process.returncode
            process.wait.side_effect=lambda **kw:setattr(process,'returncode',1)
            with patch.object(driver.subprocess,'Popen',return_value=process),\
                patch.object(driver.time,'monotonic',side_effect=[0,0,61]),patch.object(driver.time,'sleep'),\
                patch.object(driver.windows,'send_key') as key,self.assertRaisesRegex(ValueError,'expired'):
                driver.run_case(args,root,'connected-input',Mock())
            key.assert_not_called()
            r=json.loads((root/'connected-input-result.json').read_text())
            self.assertEqual(r['external_keyboard_actions'],[]);self.assertIn('expired',r['error'])

    def test_shared_and_legacy_snapshot_sources_are_unchanged(self):
        # Reviewed pre-correction LF hashes, not hashes calculated from the new implementation.
        for name,expected in {
            'tools/live_status.py':'a7bbe9732d09cc8fc7a59df8627d7568e3b7ab5bf91ef32a58600e2dc7038e00',
            'tools/run_live_session.py':'40eace4cfed1fdc689d99d7b26e49276ce8d78897351ad96eb784ce4cf6b788e',
        }.items():
            self.assertEqual(hashlib.sha256((ROOT/name).read_bytes().replace(b'\r\n',b'\n')).hexdigest(),expected)

    def test_exact_cadence_one_open_and_legacy_boundaries(self):
        source=(ROOT/'research/homebrew/live_av_v2/main.cpp').read_text()
        self.assertIn('sceKernelUsleep(LiveV2::PostFlipSleepUs)',source)
        self.assertEqual(source.count('scePadOpen('),1)
        self.assertNotIn('scePadClose(',source)
        import ps4_launch, runtime_settings
        self.assertNotIn('live-av-v2',ps4_launch.PROFILES)
        self.assertNotIn('live-av-v2',runtime_settings.AUDIO_TITLES)

    def test_pending_owner_is_logged_and_progress_uses_original_audit(self):
        import live_av_v2_guest_tests as driver
        emitted=[]
        with patch.object(driver,'read_status',side_effect=FileNotFoundError):
            self.assertIsNone(driver.optional_progress(Path('unused'),lambda event:emitted.append(event)))
        self.assertEqual(emitted,['owner_metadata_pending'])
        with patch.object(driver,'read_status',side_effect=ValueError),self.assertRaises(ValueError):
            driver.optional_progress(Path('unused'),lambda event:None)
        with patch.object(driver,'read_status',return_value=dict(schema_version=1,supervisor_pid=10)),\
            patch.object(startup,'read_events',return_value=events()):
            self.assertTrue(driver.optional_progress(Path('unused'),lambda event:None)['running_observed'])

    def test_human_protocol_permissions_order_and_budget_without_ui(self):
        from live_av_v2_guide import Protocol
        for scenario,reconnect,count in (('recovery',True,9),('disconnected-close',False,3)):
            with self.assertRaises(ValueError):Protocol(scenario)
            p=Protocol(scenario,physical_authorized=True,disconnect_authorized=True,reconnect_authorized=reconnect,before_close=lambda:None)
            p.ready()
            for i in range(count):
                self.assertEqual(p.index,i)
                with self.assertRaises(ValueError):p.verified()
                if p.mode=='usb-permission':p.confirm()
                p.confirm();p.capture();p.confirm();p.verified()
            self.assertEqual(p.mode,'close-permission')
            p.confirm();self.assertEqual(p.mode,'close');p.confirm();self.assertEqual(p.mode,'closed')
            with self.assertRaises(ValueError):p.confirm()
            with self.assertRaises(ValueError):p.check_budget(p.started+361)

    def test_supervisor_report_is_consumed_only_after_containment_finishes(self):
        import live_av_v2_guest_tests as driver
        with tempfile.TemporaryDirectory() as t:
            out=Path(t);(out/'session').mkdir();order=[]
            def wait(pid):
                order.append(pid)
                if pid==2:(out/'session/supervisor.json').write_text(json.dumps(transport()))
            with patch.object(driver,'wait_dead',side_effect=wait):
                r=driver.completed_transport(out,launcher_dead=True,root_pid=1,supervisor_pid=2)
            self.assertEqual(order,[1,2]);self.assertEqual(r,transport())

    def test_physical_cli_refuses_missing_consent_before_any_output_or_device(self):
        with tempfile.TemporaryDirectory() as t:
            out=Path(t)/'must-not-exist'
            command=[sys.executable,str(ROOT/'tests/live_av_v2_guest_tests.py')]
            for key in ('engine','engine-report','fixture','supervisor','muted-endpoint-observer'):
                command.extend(['--'+key,'unused'])
            command.extend(['--output',str(out),'--physical-scenario','recovery'])
            result=subprocess.run(command,capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,2);self.assertFalse(out.exists())
            self.assertIn('permissions required',result.stderr)

    def test_v2_contract_rejects_changed_engine_source_fixture_and_patch(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);(root/'config').mkdir()
            for name in ('startup-research.json','g2-integration-audit.json'):
                shutil.copyfile(ROOT/'config'/name,root/'config'/name)
            c=json.loads((root/'config/startup-research.json').read_text())
            for key in ('patch','audit_header','services_header','aac_header'):
                path=Path(c[key+'_path']);(root/path).parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(ROOT/path,root/path)
            source=root/'research/homebrew/live_av_v2/main.cpp';source.parent.mkdir(parents=True)
            source.write_bytes(b'original source')
            engine=root/'engine';fixture=root/'fixture';report=root/'report'
            engine.write_bytes(b'engine');fixture.write_bytes(b'fixture')
            config=dict(schema_version=1,source_sha256=startup.digest(source),oelf_sha256=startup.digest(fixture))
            (root/'config/live-av-v2.json').write_text(json.dumps(config))
            audit=json.loads((root/'config/g2-integration-audit.json').read_text())
            r=dict(status='strict_engine_built',upstream_revision=audit['upstream']['revision'],
                patched_tree=c['expected_patched_tree'],aac_backend='ffmpeg-aac-lc',fdk_linkage_verified_absent=True,
                aac_tests=dict(status='passed'),executable_sha256=startup.digest(engine))
            for key in ('patch','audit_header','services_header','aac_header'):r[key+'_sha256']=c[key+'_sha256']
            report.write_text(json.dumps(r))
            with patch.object(contract,'ROOT',root):
                contract.verify_inputs(engine,report,fixture)
                for path in (engine,fixture,source,root/c['patch_path']):
                    original=path.read_bytes();path.write_bytes(original+b'changed')
                    with self.assertRaises(ValueError):contract.verify_inputs(engine,report,fixture)
                    path.write_bytes(original)
                with self.assertRaises(ValueError):contract.verify_inputs(engine,report,fixture,'live-av')

    def test_generated_physical_recovery_contract_and_missing_edges(self):
        from live_av_v2_guide import RECOVERY
        rows=[];native=[];phases=[];human=[dict(event='human_ready_clicked',index=-1,qpc_seconds=.01)]
        opened=dict(event='hotplug_opened',episode=0,instance_id=10,qpc=100000,qpc_frequency=1000000,
            vendor=1356,product=3302,real_type=6,connection='wired',virtual=False,sole=True)
        native.append(opened)
        for i in range(485):
            at=(i+1)/10;connected=not 21.1<=at<33.1
            pressed=(6.1<=at<11.1 or 16.1<=at<21.1 or 38.1<=at<43.1)
            row=copy.deepcopy(samples()[0]);row.update(sequence=i,flip=i+1,observed_us=round(at*1e6),
                timestamp=round(at*1e6) if connected else 0,audio_blocks=i*2,
                raw_buttons=ev.CROSS if pressed else 0,effective_buttons=ev.CROSS if pressed and connected else 0,
                connected=int(connected),state=ev.CONNECTED if connected else ev.DISCONNECTED,audio_command=int(pressed and connected))
            rows.append(row)
            native.append(dict(event='hotplug_state',qpc=round(at*1e6),episode=int(at>=33.1),
                instance_id=11 if at>=33.1 else 10,connected=connected,input_valid=connected,
                buttons=int(pressed) if connected else None,axes=[0]*4 if connected else None))
        native.extend([dict(event='hotplug_removed',episode=0,instance_id=10,qpc=21100000),
            dict(opened,episode=1,instance_id=11,qpc=33100000)])
        for at,ep,down in ((6.1,0,True),(11.1,0,False),(16.1,0,True),(21.1,0,False),(38.1,1,True),(43.1,1,False)):
            native.append(dict(event='sdl_button',qpc=round(at*1e6),episode=ep,instance_id=10+ep,button=0,down=down))
        native.sort(key=lambda r:r['qpc']);native.append(dict(event='stopped',qpc=49000000))
        for i,(start,stop) in enumerate(zip((1,6,11,16,21,26,33,38,43),(5,10,15,20,25,32,37,42,47))):
            phases.append(dict(index=i,label=RECOVERY[i],sequence=stop*10-1,instruction_qpc_seconds=float(start),
                capture_qpc_seconds=float(stop),guest_after_observed_us=int(start*1e6),pixels_verified=230400))
            usb=i in (4,6)
            if usb:human.append(dict(index=i,event='usb-permission',qpc_seconds=start-.1))
            human.extend(dict(index=i,event=e,qpc_seconds=stamp) for e,stamp in
                zip((('usb_action_instruction' if usb else 'action'),'human_action_confirmed','capture_prompt','human_f12_confirmed'),
                    (float(start),start+.2,stop-.3,stop-.2)))
        close=dict(last_owned_qpc_seconds=47.1,instruction_qpc_seconds=47.2,root_exit_qpc_seconds=48.,
            finished_qpc_seconds=48.1,confirmed_qpc_seconds=48.3,ownership_failed=False,root_pid=123,bound_window=99,
            last_guest_observed_us=rows[-1]['observed_us'],last_guest_seen_qpc_seconds=47.9)
        human.extend(dict(index=9,event=e,qpc_seconds=stamp) for e,stamp in
            zip(('close-permission','normal_close_instruction','human_close_confirmed'),(47.05,47.2,48.3)))
        self.assertEqual(ev.verify_physical(native,rows,phases,RECOVERY,transport(),close)['qualified_phases'],9)
        ev.verify_confirmations(human,phases,RECOVERY,close)
        for kind in ('release','missing-phase','ownership','short','reopen','confirmation'):
            n=copy.deepcopy(native);p=copy.deepcopy(phases);c=copy.deepcopy(close);s=copy.deepcopy(rows)
            if kind=='release':n=[r for r in n if not(r['event']=='sdl_button' and r['qpc']==43100000)]
            elif kind=='missing-phase':p.pop()
            elif kind=='ownership':c['ownership_failed']=True
            elif kind=='short':p[5]['sequence']=p[4]['sequence']+1
            elif kind=='reopen':s[-1]['handle']=2
            else:
                with self.assertRaises(ValueError):ev.verify_confirmations(human[:-1],phases,RECOVERY,close)
                continue
            with self.subTest(kind=kind),self.assertRaises(ValueError):ev.verify_physical(n,s,p,RECOVERY,transport(),c)


from live_v2_handoff_tests import HandoffTests

if __name__=='__main__':unittest.main()
