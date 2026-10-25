# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
"""Deterministic host regressions. No guest, controller, COM acquisition or input."""
import copy
import argparse
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
import run_homebrew_startup as startup
import dualsense_axes_guest_tests as axes
from muted_endpoint import MutedEndpoint, validate_report

HELPER = sys.argv.pop() if len(sys.argv) > 1 else 'unsupported'


def good_transport(**changes):
    return dict(schema_version=1, tree_cleanup=True, root_exit_verified=True, **changes)


class FailureTests(unittest.TestCase):
    def supervise(self, failures, transport=None, details=None):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            (out/'supervisor.json').write_text(json.dumps(transport or good_transport()))
            child = Mock(returncode=0, pid=123)
            child.poll.side_effect = [None]*len(failures) + [0, 0]
            def poll():
                error = failures.pop(0)
                if error: raise error
                return False
            with patch.object(startup.subprocess, 'Popen', return_value=child), patch.object(startup.time, 'sleep'):
                return startup.supervise(Path('inert-supervisor'), ['never-executed'], out, 1, poll,
                                         diagnostics=details)

    def test_two_poll_failures_keep_original_code_phase_and_timestamp(self):
        first = OSError(5, 'original poll failure')
        first.winerror = 1400
        details = {}
        with self.assertRaises(ValueError) as caught:
            self.supervise([first, ValueError('later poll failure')], details=details)
        self.assertIs(caught.exception.__cause__, first)
        self.assertIn('original poll failure', str(caught.exception))
        primary = details['primary_failure']
        self.assertEqual((primary['errno'], primary['winerror'], primary['phase']), (5, 1400, 'poll'))
        self.assertGreater(primary['unix_ns'], 0)
        self.assertGreater(primary['qpc_seconds'], 0)
        self.assertEqual(details['secondary_failures'][0]['message'], 'later poll failure')

    def test_cleanup_verification_runs_and_cannot_replace_poll_failure(self):
        for field in ('tree_cleanup', 'root_exit_verified'):
            details = {}
            bad = good_transport(); bad[field] = False
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'original'):
                self.supervise([ValueError('original')], bad, details)
            self.assertEqual(details['secondary_failures'][-1]['phase'], 'supervisor_report')
            self.assertFalse(details['transport'][field])

    def test_cleanup_verification_without_poll_failure_is_primary(self):
        bad = good_transport(); bad['root_exit_verified'] = False
        with self.assertRaisesRegex(RuntimeError, 'root exit'):
            self.supervise([None], bad)

    def test_secondary_metadata_failure_cannot_replace_primary(self):
        with patch.object(startup, 'failure_details', side_effect=OSError('metadata sink failed')):
            with self.assertRaisesRegex(ValueError, 'original'):
                self.supervise([ValueError('original'), ValueError('later')])

    def test_successful_existing_supervisor_return_contract(self):
        result = self.supervise([None])
        self.assertEqual(result, good_transport())

    def test_stop_write_failure_does_not_skip_wait_kill_or_report_verification(self):
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp);(out/'supervisor.json').write_text(json.dumps(good_transport()))
            child=Mock(returncode=0,pid=123);child.poll.return_value=None
            child.wait.side_effect=[subprocess.TimeoutExpired('inert',6),0]
            details={}
            with patch.object(startup.subprocess,'Popen',return_value=child), \
                 patch.object(Path,'touch',side_effect=OSError(5,'stop write denied')):
                with self.assertRaisesRegex(ValueError,'original'):
                    startup.supervise(Path('inert'),['never-executed'],out,1,
                        Mock(side_effect=ValueError('original')),diagnostics=details)
            child.kill.assert_called_once()
            self.assertEqual(child.wait.call_count,2)
            self.assertTrue(details['transport']['tree_cleanup'])
            self.assertIn('supervisor_stop_request',[e['phase'] for e in details['secondary_failures']])

    def test_secondary_failure_history_is_bounded_and_explicit(self):
        details={}
        with self.assertRaisesRegex(ValueError,'first'):
            self.supervise([ValueError('first')]+[ValueError('later') for _ in range(39)],details=details)
        self.assertEqual(len(details['secondary_failures']),32)
        self.assertEqual(details['secondary_dropped'],7)

    def test_cleanup_poll_query_failure_preserves_primary_and_still_waits(self):
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp);(out/'supervisor.json').write_text(json.dumps(good_transport()))
            child=Mock(returncode=0,pid=123)
            child.poll.side_effect=[None,OSError('late poll query'),OSError('cleanup poll query')]
            child.wait.return_value=0;details={}
            with patch.object(startup.subprocess,'Popen',return_value=child),patch.object(startup.time,'sleep'):
                with self.assertRaisesRegex(ValueError,'original'):
                    startup.supervise(Path('inert'),['never-executed'],out,1,
                        Mock(side_effect=ValueError('original')),diagnostics=details)
            child.wait.assert_called_once_with(timeout=6)
            self.assertIn('supervisor_cleanup_poll',[e['phase'] for e in details['secondary_failures']])

    def test_sdl_timeout_secondary_and_all_cleanup_attempted(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp); result = {}
            observer = Mock(returncode=0)
            observer.wait.side_effect = [subprocess.TimeoutExpired('inert', 5), 0]
            state = Mock()
            state.summary.return_value = dict(samples=2)
            state.diagnostics.snapshot.side_effect = OSError(87, 'snapshot failed')
            emit = Mock(side_effect=OSError(5, 'evidence failed'))
            axes.finish_observation(state, observer, emit, result, out, ValueError('primary'))
            self.assertTrue((out/'physical-stop.request').exists())
            observer.kill.assert_called_once()
            state.close.assert_called_once()
            self.assertEqual(observer.wait.call_count, 2)
            self.assertEqual([e['phase'] for e in result['cleanup_failures']],
                             ['window_snapshot', 'sdl_cleanup_timeout', 'cleanup_evidence'])
            self.assertEqual(result['cleanup_failures'][-1]['errno'], 5)
            self.assertEqual(result['cleanup_failures'][1]['cause']['type'],'TimeoutExpired')

    def test_sdl_cleanup_failure_alone_becomes_primary(self):
        with tempfile.TemporaryDirectory() as temp:
            result = {}; observer = Mock(returncode=0)
            observer.wait.side_effect = [subprocess.TimeoutExpired('inert', 5), 0]
            with self.assertRaisesRegex(RuntimeError, 'needed termination'):
                axes.finish_observation(None, observer, Mock(), result, Path(temp), None)
            self.assertEqual(result['status'], 'failed')
            self.assertEqual(result['failure']['phase'], 'sdl_cleanup_timeout')

    def test_primary_survives_postmortem_and_guide_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp); (out/'session').mkdir()
            primary = OSError(5, 'original')
            result = {}; axes._set_failure(result, primary, 'poll')
            guide = Mock(); guide.close.side_effect = RuntimeError('guide failure')
            with patch.object(startup, 'collect_failure_evidence', side_effect=RuntimeError('postmortem failure')):
                with self.assertRaises(OSError) as caught:
                    try: raise primary
                    finally: axes.finalize_result(out, result, guide, sys.exc_info()[1])
            self.assertIs(caught.exception, primary)
            saved = json.loads((out/'result.json').read_text())
            self.assertEqual(saved['failure']['errno'], 5)
            self.assertEqual(saved['status'], 'failed')
            self.assertEqual([x['phase'] for x in saved['cleanup_failures']], ['failure_evidence', 'guide_close'])

    def test_publication_failure_cannot_mask_primary_or_claim_success(self):
        with tempfile.TemporaryDirectory() as temp:
            primary = ValueError('original'); result = {}
            axes._set_failure(result, primary, 'poll')
            with patch.object(axes, 'write_result', side_effect=OSError(32, 'publication locked')), patch('sys.stderr', io.StringIO()):
                with self.assertRaises(ValueError) as caught:
                    try: raise primary
                    finally: axes.finalize_result(Path(temp), result, Mock(), sys.exc_info()[1])
            self.assertIs(caught.exception, primary)
            self.assertEqual(result['cleanup_failures'][-1]['errno'], 32)
            self.assertEqual(result['failure']['message'], 'original')

    def test_result_close_failure_leaves_no_published_success(self):
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp); stream=Mock()
            stream.__enter__=Mock(return_value=stream)
            stream.__exit__=Mock(side_effect=OSError(5,'close failed'))
            with patch.object(Path,'open',return_value=stream):
                with self.assertRaisesRegex(OSError,'close failed'):
                    axes.write_result(out,dict(status='passed'))
            self.assertFalse((out/'result.json').exists())

    def test_result_publication_never_reuses_existing_result(self):
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp);(out/'result.json').write_text('preserve')
            with self.assertRaises(FileExistsError):axes.write_result(out,dict(status='passed'))
            self.assertEqual((out/'result.json').read_text(),'preserve')

    def test_postmortem_failure_without_primary_cannot_leave_passed_status(self):
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp); (out/'session').mkdir(); result=dict(status='passed')
            with patch.object(startup, 'collect_failure_evidence', side_effect=RuntimeError('collection failed')):
                with self.assertRaisesRegex(RuntimeError, 'collection failed'):
                    axes.finalize_result(out,result,Mock(),None)
            self.assertEqual(json.loads((out/'result.json').read_text())['status'],'failed')

    def test_actual_main_boundary_preserves_poll_failure_after_sdl_timeout(self):
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp)/'session-output'
            args=argparse.Namespace(**{name:Path('unused-host-test-path') for name in
                ('engine','engine_report','fixture','supervisor','sdl_observer','muted_endpoint_observer')},output=out)
            endpoint=MagicMock();endpoint.__enter__.return_value=endpoint
            endpoint.cleanup_failures=[];endpoint.child.returncode=0
            primary=OSError(5,'first poll failure')
            def inert_run(args,result,guide,endpoint):
                observer=Mock(returncode=0)
                observer.wait.side_effect=[subprocess.TimeoutExpired('inert',5),0]
                try:
                    self.supervise([primary,ValueError('second poll failure')],details=result.setdefault('supervision_diagnostics',{}))
                finally:
                    axes.finish_observation(None,observer,Mock(),result,args.output,sys.exc_info()[1])
            with patch.object(axes.argparse.ArgumentParser,'parse_args',return_value=args), \
                 patch.object(axes.startup,'digest',return_value='host-only-placeholder'), \
                 patch.object(axes,'Guide'),patch.object(axes,'MutedEndpoint',return_value=endpoint) as create, \
                 patch.object(axes,'run',side_effect=inert_run):
                with self.assertRaisesRegex(ValueError,'first poll failure'):
                    axes.main()
            self.assertTrue(create.call_args.kwargs['all_render'])
            saved=json.loads((out/'result.json').read_text())
            self.assertEqual((saved['status'],saved['failure']['errno'],saved['failure']['phase']),('failed',5,'poll'))
            self.assertEqual(saved['supervision_diagnostics']['secondary_failures'][0]['message'],'second poll failure')
            self.assertEqual(saved['cleanup_failures'][0]['phase'],'sdl_cleanup_timeout')
            self.assertFalse((out/'session').exists())


def render_records():
    return [dict(schema_version=2,event='identity',token=i,identity=f'FAKE-ENDPOINT-{i}') for i in range(2)] + [
        dict(schema_version=2,event='sample',elapsed_ms=n*25,default_tokens=[0,0,0],
             endpoints=[dict(token=i,active=True,muted=True,volume=.5) for i in range(2)]) for n in range(2)
    ] + [dict(schema_version=2,event='summary',status='passed',samples=2)]


class AllRenderTests(unittest.TestCase):
    def validate(self, rows):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'endpoint.jsonl'; path.write_text(''.join(json.dumps(r)+'\n' for r in rows))
            return validate_report(path,all_render=True)

    def test_all_active_endpoints_are_required_and_legacy_is_distinct(self):
        self.assertEqual(self.validate(render_records())['endpoint_identities'],2)
        legacy=[dict(elapsed_ms=n*25,muted=True,volume=.5,same_endpoint=True) for n in range(2)] + [dict(status='passed',samples=2)]
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'legacy';path.write_text(''.join(json.dumps(r)+'\n' for r in legacy))
            self.assertTrue(validate_report(path)['muted'])
            with self.assertRaises(RuntimeError):validate_report(path,all_render=True)

    def test_default_nondefault_new_unmuted_missing_or_invalid_samples_rejected(self):
        for kind in ('default_unmute','nondefault_unmute','new_unmute','default_changed','removed','unavailable','volume','nan','identity','schema','failed_footer','wrong_count','incomplete'):
            rows=render_records(); sample=rows[-2]
            if kind=='default_unmute':sample['endpoints'][0]['muted']=False
            elif kind=='nondefault_unmute':sample['endpoints'][1]['muted']=False
            elif kind=='new_unmute':
                rows.insert(-2,dict(schema_version=2,event='identity',token=2,identity='FAKE-NEW'))
                sample['endpoints'].append(dict(token=2,active=True,muted=False,volume=.5))
            elif kind=='default_changed':sample['default_tokens'][2]=1
            elif kind=='removed':sample['endpoints'].pop()
            elif kind=='unavailable':sample['endpoints'][1]['active']=False
            elif kind=='volume':sample['endpoints'][1]['volume']=.75
            elif kind=='nan':sample['endpoints'][1]['volume']=float('nan')
            elif kind=='identity':rows[1]['identity']=rows[0]['identity']
            elif kind=='schema':sample['schema_version']=1
            elif kind=='failed_footer':rows[-1]['status']='failed'
            elif kind=='wrong_count':rows[-1]['samples']=3
            else:rows.pop()
            with self.subTest(kind=kind),self.assertRaises(RuntimeError):self.validate(rows)

    def test_muted_new_endpoint_is_permitted_and_stable(self):
        rows=render_records();rows.insert(-2,dict(schema_version=2,event='identity',token=2,identity='FAKE-NEW'))
        rows[-2]['endpoints'].append(dict(token=2,active=True,muted=True,volume=.7))
        self.assertEqual(self.validate(rows)['endpoint_identities'],3)

    def test_query_hresult_and_observer_phase_survive_abort(self):
        with tempfile.TemporaryDirectory() as temp:
            endpoint=object.__new__(MutedEndpoint);endpoint.all_render=True
            endpoint.child=Mock();endpoint.child.poll.return_value=1
            endpoint.report=Path(temp)/'report'
            failure=dict(schema_version=2,event='failure',phase='GetMute',identity='FAKE-B',code_domain='HRESULT',code=-2147467259,unix_ns=123,elapsed_ms=25)
            endpoint.report.write_text(json.dumps(failure)+'\n'+json.dumps(dict(event='summary',status='failed'))+'\n')
            with self.assertRaises(RuntimeError) as caught:endpoint.check()
            record=startup.failure_details(caught.exception,'poll')
            self.assertEqual(record['hresult'],-2147467259)
            self.assertEqual(record['observer_failure'],failure)

    def test_endpoint_entry_failure_is_not_masked_by_failed_exit(self):
        with tempfile.TemporaryDirectory() as temp:
            endpoint=object.__new__(MutedEndpoint);endpoint.all_render=True
            endpoint.report=Path(temp)/'report';endpoint.ready=Path(temp)/'ready';endpoint.stop=Path(temp)/'stop'
            endpoint.errors=io.StringIO();endpoint.cleanup_failures=[]
            endpoint.child=Mock(returncode=1);endpoint.child.poll.return_value=1;endpoint.child.wait.return_value=1
            with self.assertRaisesRegex(RuntimeError,'Endpoint observer stopped'):
                endpoint.__enter__()
            self.assertEqual(endpoint.cleanup_failures[-1]['phase'],'endpoint_exit')
            self.assertTrue(endpoint.errors.closed)

    def test_new_mode_is_opt_in_and_has_no_audio_setter_or_stream_calls(self):
        with tempfile.TemporaryDirectory() as temp:
            for all_render,flag in ((False,'--watch'),(True,'--watch-all-render')):
                folder=Path(temp)/str(all_render);folder.mkdir()
                with patch('muted_endpoint.subprocess.Popen',return_value=Mock()) as spawn:
                    endpoint=MutedEndpoint(Path('unused-helper'),folder,all_render=all_render)
                self.assertEqual(spawn.call_args.args[0][1],flag)
                endpoint.errors.close()
        import re
        source='\n'.join((ROOT/'tests'/name).read_text() for name in ('endpoint_observer.cpp','all_render_observer.h','all_render_guard.h'))
        self.assertIsNone(re.search(r'\b(SetMute|SetMasterVolumeLevel|SetMasterVolumeLevelScalar|IAudioClient|IAudioRenderClient|SDL_OpenAudioDevice)\b',source))

    @unittest.skipIf(HELPER=='unsupported','Native argument rejection only; no COM')
    def test_new_mode_arguments_fail_before_any_com_or_output(self):
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp);report=out/'report';stop=out/'stop';ready=out/'ready'
            for value in ('0','99','600001','-1','nan'):
                child=subprocess.run([HELPER,'--watch-all-render',report,stop,ready,value],capture_output=True,timeout=5)
                self.assertEqual(child.returncode,1)
                self.assertFalse(report.exists());self.assertFalse(ready.exists())
            report.write_text('preserve')
            child=subprocess.run([HELPER,'--watch-all-render',report,stop,ready,'100'],capture_output=True,timeout=5)
            self.assertEqual(child.returncode,1);self.assertEqual(report.read_text(),'preserve')


if __name__=='__main__':unittest.main()
