# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
"""Actual Python supervision; inert process/device edges, never a guest launch."""
from contextlib import contextmanager, ExitStack
from pathlib import Path
from unittest.mock import patch
import json, os, sys, subprocess, tempfile, unittest

ROOT = Path(os.environ.get('D1_SOURCE', Path(__file__).resolve().parents[1])).resolve()
sys.path[:0] = [str(ROOT/'tools'), str(ROOT/'tests')]
import run_live_v2_session as session
import run_homebrew_startup as startup
import live_av_v2_contract as contract
import live_av_v2_evidence as ev

@contextmanager
def lifetime(timeout):
    assert timeout is None
    yield 'until_exit', {}

def run_case(mode, base):
    import live_av_v2_tests as fixture
    base.mkdir(); out=base/'output';out.mkdir();inputs=base/'inputs';inputs.mkdir()
    paths={k:inputs/k for k in ('engine','engine_report','fixture','supervisor')}
    for p in paths.values():p.write_text('INERT DATA; NOT EXECUTABLE',encoding='utf-8')
    first=OSError(5,'FIRST guest audit');first.winerror=1400
    deep=mode.startswith('deep-')
    postmortem_mode=mode.startswith(('audit-postmortem-','postmortem-no-first-'))
    outcome_mode=mode.startswith(('audit-outcome-','outcome-no-first-'))
    no_first=mode.startswith(('postmortem-no-first-','outcome-no-first-'))
    double_sink=(postmortem_mode or outcome_mode) and mode.endswith('-double-sink')
    first_cause=LookupError('Original explicit cause') if deep or mode.startswith('audit-fallback-') or postmortem_mode or outcome_mode else None
    first.__cause__=first_cause
    real_verify=contract.verify_inputs;real_digest=contract.digest
    if deep:
        locked=json.loads((ROOT/'config/startup-research.json').read_text())
        audit=json.loads((ROOT/'config/g2-integration-audit.json').read_text())
        report=dict(status='strict_engine_built',upstream_revision=audit['upstream']['revision'],
            aac_backend='ffmpeg-aac-lc',fdk_linkage_verified_absent=True,aac_tests={'status':'passed'},
            executable_sha256=startup.digest(paths['engine']))
        for key in ('patch_sha256','audit_header_sha256','services_header_sha256','aac_header_sha256'):
            report[key]=locked[key]
        report['patched_tree']=locked['expected_patched_tree']
        depth=int(mode.rsplit('-',1)[1])
        paths['engine_report'].write_text(json.dumps(report)[:-1]+',"review_extra":'+'['*depth+'0'+']'*depth+'}',encoding='utf-8')
    seen={};state=dict(polls=0,kills=0,waits=0,returncode=None,progress=0,report_reads=0,journal_appends=0)
    real_supervise=startup.supervise;real_progress=ev.progress;real_open=Path.open
    before=dict(os.environ)
    class Child:
        pid=8172
        @property
        def returncode(self):return state['returncode']
        def poll(self):
            state['polls']+=1
            if mode in ('report-cleanup','cleanup-failed') and state['polls'] in (2,3):
                raise OSError(9,'SECOND status read')
            if state['polls'] <= (41 if mode=='audit-overflow' else 2 if mode.startswith('audit') else 1):return None
            state['returncode']=0;return 0
        def wait(self,timeout=None):
            state['waits']+=1
            if mode in ('report-cleanup','cleanup-failed') and state['waits']==1:
                raise subprocess.TimeoutExpired('INERT',timeout)
            if mode=='cleanup-failed':raise OSError(10,'SECOND wait after kill')
            state['returncode']=0;return 0
        def kill(self):
            state['kills']+=1
            if mode=='cleanup-failed':raise OSError(13,'SECOND kill denied')
            state['returncode']=-9
    def popen(args,**kw):
        assert Path(args[0])==paths['supervisor'].resolve()
        work=out/'session';rows=fixture.samples()
        (work/'startup-audit.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in fixture.events(rows)),encoding='utf-8')
        (work/'user/data').mkdir(exist_ok=True)
        (work/'user/data/live-av-v2.bin').write_bytes(ev.HEADER+b''.join(map(ev.pack_record,rows)))
        report=dict(fixture.transport(),schema_version=1)
        if not deep and not no_first and mode not in ('control','outcome-serialization','result-serialization','publication','both-publications'):
            report.update(reason='requested',exit_code=125,forced_termination=True)
        if mode in ('root-unconfirmed','cleanup-failed'):report['root_exit_verified']=False
        (work/'supervisor.json').write_text('not-json' if mode=='report-cleanup' else json.dumps(report),encoding='utf-8')
        if mode=='audit-existing':(out/'session-result.json').write_text('EXISTING-IMMUTABLE',encoding='utf-8')
        assert kw['env']['SDL_AUDIO_DRIVER']=='wasapi'
        seen['inert_popen_calls']=seen.get('inert_popen_calls',0)+1
        return Child()
    def progress(events,**kw):
        state['progress']+=1
        if (mode in ('audit-first','audit-stderr','audit-overflow','audit-diagnostic-serialization','audit-publication','audit-both-publications','audit-short','audit-existing','report-cleanup','cleanup-failed','metadata') or mode.startswith(('deep-first-','audit-fallback-','audit-postmortem-','audit-outcome-'))) and state['progress']==1:
            raise first
        return real_progress(events,**kw)
    def supervise(*args,**kw):
        seen['diagnostics_keyword']='diagnostics' in kw
        if mode=='audit-overflow':
            args=list(args);poll=args[4];polls=0
            def injected_poll():
                nonlocal polls
                polls+=1
                if polls>1:raise OSError(28,'SECOND repeated host poll failure')
                return poll()
            args[4]=injected_poll
        try:
            value=real_supervise(*args,**kw)
            seen['normal_diagnostics']=kw.get('diagnostics')
            return value
        except BaseException as error:
            seen['cause_is_first']=error.__cause__ is first
            seen['shared_diagnostics']=error.supervision_diagnostics
            if mode=='metadata':
                error.supervision_diagnostics['secondary_dropped']=object()
            raise
    class Stream:
        def __init__(self,real):self.real=real
        def flush(self):raise OSError(28,'SECOND stderr flush')
        def close(self):self.real.close()
        def __getattr__(self,name):return getattr(self.real,name)
    class ShortWrite:
        def __init__(self,real):self.real=real
        def __enter__(self):return self
        def __exit__(self,*args):self.real.close()
        def write(self,raw):self.real.write(raw[:17]);return 17
    def opened(path,*args,**kw):
        access=args[0] if args else kw.get('mode','r')
        kind=KeyboardInterrupt if '-interrupt' in mode else SystemExit if '-systemexit' in mode else RuntimeError if '-runtime' in mode else OSError
        if path.name=='supervisor.json' and access=='r':
            state['report_reads']+=1
            if postmortem_mode and state['report_reads']==2:
                raise kind('SECOND actual postmortem report read')
        if path.name=='session-diagnostics.jsonl' and access=='ab':
            state['journal_appends']+=1
            if outcome_mode and state['journal_appends']==(2 if no_first else 3):
                raise kind('SECOND actual outcome journal append')
            if double_sink and seen.get('final_write_attempted'):
                raise RuntimeError('THIRD actual fallback journal unavailable')
        if path.name=='session-result.json':seen['final_write_attempted']=True
        if path.name=='session-result.json' and ('publication' in mode or mode.startswith('audit-fallback-') or double_sink):
            raise PermissionError(13,'SECOND final result publication denied')
        if path.name=='session-diagnostics.jsonl' and mode.startswith('audit-fallback-') and args and args[0]=='ab' and seen.get('final_write_attempted'):
            kind=RuntimeError if mode.endswith('runtime') else OSError
            raise kind('THIRD actual journal append unavailable')
        if path.name=='session-diagnostics.jsonl' and 'both-publications' in mode and args and args[0]=='ab' and seen.get('final_write_attempted'):
            raise OSError(28,'SECOND diagnostic publication denied')
        stream=real_open(path,*args,**kw)
        if mode=='audit-short' and path.name=='session-result.json':return ShortWrite(stream)
        return Stream(stream) if (mode in ('audit-stderr','audit-publication','audit-both-publications') or mode.startswith('audit-fallback-')) and path.name=='supervisor-stderr.txt' else stream
    original_write=Path.write_text
    def write_text(path,*args,**kw):
        if path.name=='session-result.json' and 'publication' in mode:
            seen['final_write_attempted']=True
            raise PermissionError(13,'SECOND final result publication denied')
        return original_write(path,*args,**kw)
    original_emit=session.Diagnostics.emit
    def emit(obj,event,**kw):
        if mode=='audit-diagnostic-serialization' and event=='first_failure':raise TypeError('SECOND first-failure serialization')
        if mode=='outcome-serialization' and event=='supervision_outcome':raise TypeError('SECOND outcome serialization')
        if 'both-publications' in mode and event=='final_result_write_failure':raise OSError(28,'SECOND diagnostic publication denied')
        return original_emit(obj,event,**kw)
    captured=[];original_capture=session.FirstFailure.capture
    def capture(obj,error,*args,**kw):
        original_capture(obj,error,*args,**kw)
        if obj.error is not None:captured.append(obj.error)
    def verify(*args,**kw):
        fixture_sha=json.loads((ROOT/'config/live-av-v2.json').read_text())['oelf_sha256']
        with patch.object(contract,'digest',side_effect=lambda p:fixture_sha if p.resolve()==paths['fixture'].resolve() else real_digest(p)):
            value=real_verify(*args,**kw)
        seen['actual_verifier_accepted']=True
        return value
    patches=[patch.object(session.sys,'platform','win32'),patch.object(session.platform,'machine',return_value='AMD64'),
        patch.object(session.platform,'platform',return_value='INERT-HOST'),patch.object(session.platform,'processor',return_value='inert'),
        patch.object(contract,'verify_inputs',side_effect=verify) if deep else patch.object(contract,'verify_inputs',return_value={'scope':object() if mode=='result-serialization' else 'inert-only'}),
        patch.object(startup,'supervisor_lifetime',side_effect=lifetime),patch.object(startup,'background_process_options',return_value={}),
        patch.object(startup.subprocess,'Popen',side_effect=popen),patch.object(startup.time,'sleep'),
        # File-system latency must not consume production cleanup budgets in
        # an inert injection. TimeoutExpired is injected explicitly above.
        patch.object(startup.time,'monotonic',return_value=0.0),
        patch.object(startup,'supervise',side_effect=supervise),patch.object(ev,'progress',side_effect=progress),
        patch.object(Path,'open',opened),patch.object(Path,'write_text',write_text),
        patch.object(session.Diagnostics,'emit',emit),patch.object(session.FirstFailure,'capture',capture)]
    raised=None;code=result=None
    with ExitStack() as stack:
        for p in patches:stack.enter_context(p)
        try:code,result=session.run_session(**paths,output=out,volume_percent=0)
        except BaseException as error:raised=error
    assert before==dict(os.environ)
    assert first.__cause__ is first_cause
    assert all(Path(m.__file__).resolve().is_relative_to(ROOT) for m in (session,startup,contract,ev,fixture))
    raw=(out/'session-result.json').read_text(encoding='utf-8') if (out/'session-result.json').exists() else None
    try:durable=json.loads(raw) if raw is not None else None
    except ValueError:durable=None
    # Preserve the original result file; avoid adding nesting to deep metadata
    # merely to serialize this independent observation envelope.
    observed_result={k:v for k,v in durable.items() if k!='build'} if deep and durable is not None else durable
    seen.update(state=state,code=code,result=observed_result,result_raw=raw if durable is None else None,
        build_omitted_from_observation=deep,original_first_identity=bool(captured) and captured[0] is first,first_cause_identity=first.__cause__ is first_cause,
        raised_is_first=raised is first,raised_type=type(raised).__name__ if raised else None,
        raised_errno=getattr(raised,'errno',None),raised_winerror=getattr(raised,'winerror',None),
        persistence_unsuccessful=getattr(raised,'secondary_persistence_unsuccessful',False),
        publication_failure=getattr(raised,'result_publication_failure',None),secondary_publication_failure=getattr(raised,'secondary_publication_failure',None),native_launches=0,device_accesses=0)
    # Do not serialize deliberately corrupted metadata in the test observation.
    if mode=='metadata':seen['shared_diagnostics']['secondary_dropped']='injected nonserializable object'
    (base/'observations.json').write_text(json.dumps(seen,indent=2),encoding='utf-8')
    return seen,out,raised

class HandoffTests(unittest.TestCase):
    def case(self,mode):
        dest=os.environ.get('D1_EVIDENCE')
        if dest:
            root=Path(dest);root.mkdir(parents=True,exist_ok=True)
        else:
            temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);root=Path(temp.name)
        return run_case(mode,root/mode)
    def first(self,s):
        self.assertTrue(s['original_first_identity']);self.assertTrue(s['cause_is_first'])
        f=s['result']['first_failure']
        self.assertEqual((f['phase'],f['type'],f['errno'],f['winerror']),('guest_audit_monitor','OSError',5,1400))
        self.assertEqual(s['code'],1);self.assertEqual(s['result']['status'],'failed')
    def test_durable_stderr_secondary(self):
        s,_,_=self.case('audit-stderr');self.first(s)
        shared=s['shared_diagnostics']['secondary_failures']
        self.assertTrue(any(r['phase']=='supervisor_stderr_flush' and r['errno']==28 for r in shared))
        durable=s['result'].get('supervision_diagnostics',{})
        self.assertTrue(any(r['phase']=='supervisor_stderr_flush' and r['errno']==28 for r in durable.get('secondary_failures',[])))
    def test_normal_return_and_existing_consumers(self):
        s,out,_=self.case('control')
        self.assertEqual((s['code'],s['result']['status']),(0,'closed'))
        self.assertEqual(s['result']['schema_version'],1)
        self.assertEqual(s['result']['supervision_diagnostics']['secondary_failures'],[])
        ev.verify_transport(s['result']['transport'])
        import live_av_v2_guest_tests as driver
        self.assertTrue(driver.optional_progress(out,lambda *a,**k:None)['running_observed'])
    def test_first_without_secondary(self):
        s,_,_=self.case('audit-first');self.first(s)
        self.assertEqual(s['result']['supervision_diagnostics']['secondary_failures'],[])
    def test_report_and_cleanup_secondaries(self):
        s,_,_=self.case('report-cleanup');self.first(s)
        phases={r['phase'] for r in s['result']['supervision_diagnostics']['secondary_failures']}
        self.assertTrue({'supervisor_cleanup_poll','supervisor_cleanup_timeout','supervisor_report'}<=phases)
        self.assertEqual((s['state']['kills'],s['state']['waits']),(1,2))
    def test_failed_cleanup_cannot_pass(self):
        s,_,_=self.case('cleanup-failed');self.first(s)
        phases={r['phase'] for r in s['result']['supervision_diagnostics']['secondary_failures']}
        self.assertTrue({'supervisor_kill','supervisor_wait_after_kill','supervisor_report'}<=phases)
    def test_unconfirmed_root_cannot_pass(self):
        s,_,_=self.case('root-unconfirmed')
        self.assertEqual((s['code'],s['result']['status']),(1,'failed'))
        self.assertFalse(s['result']['transport']['root_exit_verified'])
    def test_metadata_failure_keeps_first(self):
        s,_,_=self.case('metadata');self.first(s)
        self.assertEqual(s['result']['supervision_diagnostics_persistence']['status'],'failed')
    def test_actual_shared_overflow_is_retained(self):
        s,_,_=self.case('audit-overflow');self.first(s)
        shared=s['shared_diagnostics'];durable=s['result']['supervision_diagnostics']
        self.assertEqual(len(shared['secondary_failures']),32)
        self.assertEqual(shared['secondary_dropped'],8)
        self.assertEqual(len(durable['secondary_failures']),32)
        self.assertEqual(durable['secondary_dropped'],8)
        self.assertEqual(durable['shared_secondary_dropped'],8)
        self.assertEqual(durable['projection_secondary_dropped'],0)
    def test_outcome_serialization_cannot_pass(self):
        s,_,raised=self.case('outcome-serialization')
        self.assertIsNone(raised);self.assertEqual(s['code'],1)
        self.assertEqual(s['result']['first_failure']['phase'],'outcome_diagnostics')
        self.assertEqual(s['result']['first_failure']['type'],'TypeError')
    def test_first_diagnostic_serialization_keeps_original(self):
        s,_,_=self.case('audit-diagnostic-serialization');self.first(s)
        self.assertIn('SECOND first-failure serialization',s['result']['first_failure_diagnostic_error'])
    def test_publication_failure_without_prior(self):
        s,out,raised=self.case('publication')
        self.assertIsNotNone(raised);self.assertTrue(s['persistence_unsuccessful'])
        self.assertIsNone(s['result'])
        rows=[json.loads(x) for x in (out/'session-diagnostics.jsonl').read_text().splitlines()]
        self.assertTrue(rows[-1]['secondary_persistence_unsuccessful'])
    def test_result_serialization_cannot_pass(self):
        s,out,raised=self.case('result-serialization')
        self.assertIsInstance(raised,TypeError)
        self.assertTrue(s['persistence_unsuccessful']);self.assertIsNone(s['result'])
        rows=[json.loads(x) for x in (out/'session-diagnostics.jsonl').read_text().splitlines()]
        self.assertEqual(rows[-1]['first_failure']['phase'],'final_result_write')
    def test_publication_failure_keeps_first_and_records_secondary(self):
        s,out,raised=self.case('audit-publication')
        self.assertTrue(s['raised_is_first']);self.assertTrue(s['persistence_unsuccessful'])
        rows=[json.loads(x) for x in (out/'session-diagnostics.jsonl').read_text().splitlines()]
        marker=rows[-1];self.assertEqual(marker['event'],'final_result_write_failure')
        self.assertEqual(marker['first_failure']['errno'],5)
        self.assertEqual(marker['supervision_diagnostics']['secondary_failures'][0]['errno'],28)
    def test_both_publications_fail_explicitly(self):
        s,_,_=self.case('audit-both-publications')
        self.assertTrue(s['raised_is_first']);self.assertTrue(s['persistence_unsuccessful'])
        self.assertEqual(s['publication_failure']['errno'],13)
    def test_projection_bounds_and_drop_count(self):
        row=dict(phase='secondary',type='OSError',message='x'*5000,errno=28,winerror=1400,raw_stderr='PRIVATE',cause={'type':'ValueError','message':'y'*5000})
        value=session.supervision_snapshot(dict(primary_failure=None,secondary_failures=[row]*40,secondary_dropped=7))
        self.assertEqual(len(value['secondary_failures']),32)
        self.assertEqual(value['secondary_dropped'],15)
        self.assertLessEqual(len(json.dumps(value).encode()),65536)
        self.assertNotIn('PRIVATE',json.dumps(value));self.assertTrue(value['fields_truncated'])
        for r in value['secondary_failures']:
            self.assertEqual((r['errno'],r['winerror']),(28,1400))
        row['message']='\U0001f600'*512;row['cause']['message']='\U0001f600'*512
        bounded=session.supervision_snapshot(dict(primary_failure=None,secondary_failures=[row]*32,secondary_dropped=7))
        self.assertLessEqual(len(json.dumps(bounded).encode()),65536)
        self.assertEqual(bounded['secondary_dropped'],7+32-len(bounded['secondary_failures']))
    def test_metadata_rejection(self):
        for value in (dict(secondary_dropped=True),dict(secondary_dropped=-1),dict(secondary_dropped=object()),dict(secondary_dropped=0,secondary_failures=[object()])):
            with self.subTest(value=str(value)),self.assertRaises((ValueError,TypeError)):
                session.supervision_snapshot(value)
    def test_publication_metadata_failure_never_replaces_first_or_cause(self):
        first=OSError(5,'FIRST original');first.winerror=1400
        cause=ValueError('Original explicit cause');first.__cause__=cause
        fault=session.FirstFailure();fault.capture(first,'guest_audit_monitor')
        emitted=[]
        with patch.object(Path,'open',side_effect=PermissionError(13,'SECOND publication')),\
             patch.object(startup,'failure_details',side_effect=TypeError('SECOND metadata builder')),\
             self.assertRaises(OSError) as raised:
            session.write_session_result(Path('inert-result'),dict(status='failed'),fault,lambda e,**kw:emitted.append(kw))
        self.assertIs(raised.exception,first);self.assertIs(first.__cause__,cause)
        self.assertEqual(emitted[-1]['first_failure']['phase'],'guest_audit_monitor')
        self.assertEqual(emitted[-1]['publication_failure']['errno'],13)
    def test_nonserializable_first_metadata_still_raises_original(self):
        first=OSError(5,'FIRST original');fault=session.FirstFailure();fault.capture(first,'guest_audit_monitor')
        fault.record['errno']=object();emitted=[]
        with self.assertRaises(OSError) as raised:
            session.write_session_result(Path('must-not-be-created'),dict(status='failed'),fault,lambda e,**kw:emitted.append(kw))
        self.assertIs(raised.exception,first)
        self.assertEqual(emitted[-1]['first_failure']['errno'],5)
        self.assertEqual(emitted[-1]['publication_failure']['type'],'TypeError')
    def test_first_metadata_builder_failure_keeps_identity_and_codes(self):
        import live_v2_diagnostics
        for kind in (TypeError,ValueError,OSError,RuntimeError):
            with self.subTest(metadata_error=kind.__name__):
                first=OSError(5,'FIRST original');first.winerror=1400;fault=session.FirstFailure()
                with patch.object(live_v2_diagnostics.traceback,'format_exception',side_effect=kind('SECOND traceback metadata')):
                    session.capture_failure(fault,first,'guest_audit_monitor')
                self.assertIs(fault.error,first)
                self.assertTrue(fault.record['metadata_unavailable'])
                self.assertEqual((fault.record['errno'],fault.record['winerror']),(5,1400))
    def deep_publication(self,prefix):
        # A fresh HOST Python worker fixes the caller stack independently of
        # unittest discovery/import depth. Keep the reviewed depth992 input;
        # neither the recursion limit nor the real serializer is replaced.
        dest=os.environ.get('D1_EVIDENCE')
        if dest:root=Path(dest);root.mkdir(parents=True,exist_ok=True)
        else:
            temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);root=Path(temp.name)
        mode=prefix+'-992';base=root/mode
        command=[sys.executable,'-E','-B',str(Path(__file__).resolve()),'--deep-publication-case',mode,str(base)]
        result=subprocess.run(command,capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        s=json.loads((base/'observations.json').read_text(encoding='utf-8'))
        self.assertTrue(s.get('actual_verifier_accepted'))
        self.assertEqual(s['publication_failure']['type'],'RecursionError')
        return s,base/'output'
    def test_deep_json_publication_preserves_first_and_explicit_cause(self):
        s,out=self.deep_publication('deep-first')
        self.assertTrue(s['original_first_identity']);self.assertTrue(s['raised_is_first'])
        self.assertTrue(s['cause_is_first']);self.assertTrue(s['first_cause_identity'])
        self.assertEqual((s['raised_type'],s['raised_errno'],s['raised_winerror']),('OSError',5,1400))
        self.assertTrue(s['persistence_unsuccessful']);self.assertFalse((out/'session-result.json').exists())
        marker=json.loads((out/'session-diagnostics.jsonl').read_text().splitlines()[-1])
        self.assertEqual(marker['event'],'final_result_write_failure')
        self.assertEqual(marker['first_failure']['phase'],'guest_audit_monitor')
        self.assertEqual(marker['publication_failure']['type'],'RecursionError')
    def test_deep_json_without_prior_failure_is_primary_and_never_success(self):
        s,out=self.deep_publication('deep-no-first')
        self.assertEqual(s['raised_type'],'RecursionError');self.assertTrue(s['persistence_unsuccessful'])
        self.assertIsNone(s['code']);self.assertFalse((out/'session-result.json').exists())
        marker=json.loads((out/'session-diagnostics.jsonl').read_text().splitlines()[-1])
        self.assertEqual((marker['first_failure']['phase'],marker['first_failure']['type']),('final_result_write','RecursionError'))
    def test_actual_fallback_journal_runtime_and_os_errors_preserve_first(self):
        for suffix,kind in (('runtime','RuntimeError'),('oserror','OSError')):
            with self.subTest(sink_error=kind):
                s,out,raised=self.case('audit-fallback-'+suffix)
                self.assertTrue(s['raised_is_first']);self.assertTrue(s['first_cause_identity'])
                self.assertTrue(s['persistence_unsuccessful']);self.assertEqual((raised.errno,raised.winerror),(5,1400))
                self.assertEqual(s['publication_failure']['errno'],13)
                self.assertEqual(s['secondary_publication_failure']['type'],kind)
                self.assertLessEqual(len(s['secondary_publication_failure']['message']),512)
                self.assertTrue(any(r['errno']==28 for r in s['shared_diagnostics']['secondary_failures']))
                records=[json.loads(x) for x in (out/'session-diagnostics.jsonl').read_text().splitlines()]
                self.assertNotIn('final_result_write_failure',[r['event'] for r in records])
                self.assertFalse((out/'session-result.json').exists())
    def test_partial_and_existing_publication_artifacts_are_not_replaced(self):
        for mode in ('audit-short','audit-existing'):
            with self.subTest(mode=mode):
                s,out,raised=self.case(mode)
                self.assertTrue(s['raised_is_first']);self.assertTrue(s['persistence_unsuccessful'])
                raw=(out/'session-result.json').read_text()
                if mode=='audit-short':self.assertEqual(len(raw),17)
                else:self.assertEqual(raw,'EXISTING-IMMUTABLE')
                with self.assertRaises(ValueError):json.loads(raw)
    def test_publication_handlers_do_not_suppress_process_control_exceptions(self):
        for kind in (KeyboardInterrupt,SystemExit):
            for sink in ('result','journal'):
                with self.subTest(kind=kind.__name__,sink=sink):
                    signal=kind('inert process-control exception')
                    fault=session.FirstFailure();fault.capture(OSError(5,'FIRST'),'guest_audit_monitor')
                    def emit(*args,**kw):raise signal
                    with patch.object(Path,'open',side_effect=signal if sink=='result' else PermissionError(13,'result denied')),self.assertRaises(kind) as raised:
                        session.write_session_result(Path('inert-never-created'),dict(status='failed'),fault,emit)
                    self.assertIs(raised.exception,signal)
    def test_postmortem_runtime_and_oserror_controls_publish_original_first(self):
        for suffix in ('runtime','oserror'):
            with self.subTest(kind=suffix):
                s,out,raised=self.case('audit-postmortem-'+suffix);self.first(s)
                self.assertIsNone(raised);self.assertTrue(s['first_cause_identity'])
                self.assertEqual(s['state']['report_reads'],2)
                self.assertIn('SECOND actual postmortem report read',s['result']['postmortem_error'])
                self.assertTrue((out/'session-result.json').exists())
    def test_outcome_runtime_and_oserror_controls_publish_original_first(self):
        for suffix in ('runtime','oserror'):
            with self.subTest(kind=suffix):
                s,out,raised=self.case('audit-outcome-'+suffix);self.first(s)
                self.assertIsNone(raised);self.assertTrue(s['first_cause_identity'])
                self.assertEqual(s['state']['journal_appends'],3)
                self.assertIn('SECOND actual outcome journal append',s['result']['outcome_diagnostic_error'])
                self.assertTrue((out/'session-result.json').exists())
    def test_finalization_without_prior_first_never_returns_success(self):
        for name,phase in (('postmortem','postmortem'),('outcome','outcome_diagnostics')):
            with self.subTest(boundary=name):
                s,out,raised=self.case(name+'-no-first-runtime')
                self.assertIsNone(raised);self.assertEqual((s['code'],s['result']['status']),(1,'failed'))
                self.assertEqual((s['result']['first_failure']['type'],s['result']['first_failure']['phase']),('RuntimeError',phase))
                self.assertTrue((out/'session-result.json').exists())
    def test_finalization_and_both_publication_sink_failures_keep_first(self):
        for name in ('postmortem','outcome'):
            with self.subTest(boundary=name):
                s,out,raised=self.case('audit-'+name+'-runtime-double-sink')
                self.assertTrue(s['original_first_identity']);self.assertTrue(s['raised_is_first'])
                self.assertTrue(s['first_cause_identity']);self.assertTrue(s['persistence_unsuccessful'])
                self.assertEqual((raised.errno,raised.winerror),(5,1400))
                self.assertEqual(s['publication_failure']['errno'],13)
                self.assertEqual(s['secondary_publication_failure']['type'],'RuntimeError')
                self.assertFalse((out/'session-result.json').exists())
                records=[json.loads(x)['event'] for x in (out/'session-diagnostics.jsonl').read_text().splitlines()]
                self.assertNotIn('final_result_write_failure',records)
    def test_finalization_guards_preserve_process_control_propagation(self):
        for name in ('postmortem','outcome'):
            for suffix,kind in (('interrupt','KeyboardInterrupt'),('systemexit','SystemExit')):
                with self.subTest(boundary=name,kind=kind):
                    s,out,raised=self.case('audit-'+name+'-'+suffix)
                    self.assertEqual(s['raised_type'],kind);self.assertIsNone(s['code'])
                    self.assertTrue(s['original_first_identity']);self.assertTrue(s['first_cause_identity'])
                    self.assertFalse((out/'session-result.json').exists())

if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--deep-publication-case':
        run_case(sys.argv[2],Path(sys.argv[3]))
    else:unittest.main()
