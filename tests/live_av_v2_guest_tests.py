# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
"""Bounded AUTOMATED guest regressions. Never physical USB recovery evidence.

No device setting setters. Mandatory read-only mute guard before guest launch.
Keyboard and window messages belong only to this explicit acceptance driver.
"""
import argparse
from contextlib import contextmanager
import json
from pathlib import Path
import subprocess
import hashlib
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'tests')]
import run_live_v2_session as session
import run_homebrew_startup as startup
import live_av_v2_evidence as ev
import videoout_capture as windows
from live_status import read_status
from fixed_render_endpoint import FixedMutedEndpoint as MutedEndpoint
from fixed_render_endpoint import load_fixed_inventory, require_fixed_guard
from fixed_render_endpoint import bounded_acceptance_failure, finalization_emitter
from dualsense_evidence import readback_ready
from owned_window_trace import OwnedWindowTrace
from live_session_guest_tests import wait_dead
from live_v2_diagnostics import Diagnostics, FirstFailure
from hotplug_endpoint import MutedEndpoint as LegacyHotplugEndpoint, validate_report as validate_hotplug

CASES=('no-input-close','connected-input','launcher-death','requested-stop')


def optional_progress(output, emit):
    try:owner=read_status(output/'session-owner.json')
    except FileNotFoundError:
        emit('owner_metadata_pending')
        return None
    if (not isinstance(owner,dict) or set(owner)!={'schema_version','supervisor_pid'} or
        type(owner['schema_version']) is not int or owner['schema_version']!=1 or
        type(owner['supervisor_pid']) is not int or owner['supervisor_pid']<=0):
        raise ValueError('Invalid immutable session ownership metadata')
    state=ev.progress(startup.read_events(output/'session/startup-audit.jsonl'))
    return dict(supervisor_pid=owner['supervisor_pid'],**state)


def post_key(args, owner, owned, down, actions, emit):
    key='cross-g' if args.cross_key=='g' else 'cross'
    fields=dict(action_index=len(actions),key=key,requested_key=args.cross_key.upper(),down=down,
                supervisor_pid=owner,root_pid=owned.pid,window_handle=owned.window)
    emit('keyboard_action_requested',**fields)
    posted=windows.send_key(owner,args.engine,key,down)
    # A successful API return means posted, not physically pressed or delivered.
    actions.append(posted)
    emit('keyboard_action_posted',**fields,api_result=posted)


def observe_guest_transitions(rows, cursor, previous, emit):
    for row in rows[cursor:]:
        state=tuple(row[k] for k in ('rc','connected','raw_buttons','effective_buttons','state'))
        if state!=previous:
            emit('guest_input_observed',sequence=row['sequence'],timestamp=row['timestamp'],
                observed_us=row['observed_us'],rc=row['rc'],connected=row['connected'],
                raw_buttons=row['raw_buttons'],effective_buttons=row['effective_buttons'],state=row['state'])
            previous=state
    return len(rows),previous


def completed_transport(out, *, launcher_dead, root_pid, supervisor_pid):
    if launcher_dead:
        wait_dead(root_pid)
        wait_dead(supervisor_pid)
    return json.loads((out/'session/supervisor.json').read_text())


def worker(path):
    args=json.loads(path.read_text())
    for key in ('engine','engine_report','fixture','supervisor','output'):args[key]=Path(args[key])
    args['output'].mkdir()
    code,result=session.run_session(**args)
    print(json.dumps(result));return code


def run_case(args,root,name,endpoint):
    out=root/name;options={k:str(getattr(args,k)) for k in ('engine','engine_report','fixture','supervisor')}
    options.update(output=str(out),volume_percent=0,cross_key=args.cross_key)
    config=root/(name+'-options.json');config.write_text(json.dumps(options))
    actions=[];images=[];seen=set();pending={};owned=None;owner=None;ready=None;last_action=None
    result=dict(name=name,status='failed',physical_input_tested=False,pcm_correctness_tested=False)
    diagnostics=Diagnostics(root/(name+'-window.jsonl'));emit=finalization_emitter(diagnostics.emit,result)
    fault=FirstFailure();phase='startup';cursor=0;previous=None
    with (root/(name+'-console.txt')).open('wb') as log:
        process=None;began=time.monotonic();closing=False
        try:
            phase='fixed_endpoint_policy_prelaunch'
            result['expected_endpoint_inventory_sha256']=require_fixed_guard(endpoint)
            result['audio_policy']='option-a-fixed-all-active-render-sampled'
            phase='startup'
            process=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'worker',str(config)],
                stdout=log,stderr=subprocess.STDOUT,**startup.background_process_options())
            while process.poll() is None:
                phase='endpoint_and_window_observation'
                endpoint.check();now=time.monotonic()
                if now-began>60:raise ValueError('Bounded automated guest test expired; no retry')
                if owned is not None and not closing:owned.poll()
                phase='immutable_owner_and_guest_audit'
                status=optional_progress(out,emit)
                if status is None:time.sleep(.02);continue
                cursor,previous=observe_guest_transitions(status['samples'],cursor,previous,emit)
                if not status['running_observed']:time.sleep(.02);continue
                owner=status['supervisor_pid']
                if owned is None:
                    phase='window_binding'
                    owned=OwnedWindowTrace(windows._owned_window(owner,args.engine),emit,lifecycle=True)
                    ready=last_action=now
                phase='window_observation'
                if not closing:owned.poll()
                if name=='launcher-death':process.kill();closing=True;break
                if name=='requested-stop':
                    (out/'session/stop.request').touch(exist_ok=True);closing=True
                elif name=='no-input-close' and now-ready>=1 and not closing:
                    result['external_close']=windows.request_close(owner,args.engine);closing=True
                elif name=='connected-input' and not closing:
                    phase='guest_matched_screenshot'
                    s=status['samples'][-1];index=len(images);expected=ev.CROSS if index%2 else 0
                    if now-last_action>=3 and s['state']==ev.CONNECTED and s['raw_buttons']==expected:
                        if not pending:
                            windows.request_screenshot(owner,args.engine)
                            pending['requested']=True
                        for path in sorted(set((out/'session/user/screenshots').glob('*.png'))-seen):
                            # Wait for the SAME original PNG to finish; never resend a capture.
                            if not readback_ready(path,pending):continue
                            seq=ev.image_sequence(path)
                            rows=ev.progress(startup.read_events(out/'session/startup-audit.jsonl'))['samples']
                            if seq>=len(rows):continue
                            image=ev.verify_image(path,(out/'session/app/palette.bin').read_bytes(),rows[seq])
                            if rows[seq]['raw_buttons']!=expected:raise ValueError('Wrong mapped guest input')
                            images.append(dict(**image,path=str(path)));seen.add(path);pending={}
                            if len(images)==5:
                                result['external_close']=windows.request_close(owner,args.engine);closing=True
                            else:
                                phase='keyboard_post'
                                post_key(args,owner,owned,len(images)%2==1,actions,emit)
                                last_action=now
                            break
                time.sleep(.02)
            phase='supervisor_completion'
            process.wait(timeout=8)
            transport=completed_transport(out,launcher_dead=name=='launcher-death',
                root_pid=owned.pid if owned else None,supervisor_pid=owner)
            result['transport']=transport
            if owned is None:raise ValueError('Guest never reached owned-window readiness')
            wait_dead(owned.pid);wait_dead(owner)
            if transport['root_pid']!=owned.pid or not transport['tree_cleanup'] or not transport['owner_watch_verified']:
                raise ValueError('Exact owned root cleanup missing')
            if name in ('launcher-death','requested-stop'):
                expected='owner_exited' if name=='launcher-death' else 'requested'
                if transport['reason']!=expected or transport['forced_termination'] is not True:
                    raise ValueError('Wrong forced cleanup cause')
                if name=='requested-stop':
                    r=json.loads((out/'session-result.json').read_text())
                    if process.returncode!=1 or r['normal_exit_verified']:raise ValueError('Stop falsely accepted')
            else:
                ev.verify_transport(transport)
                r=json.loads((out/'session-result.json').read_text())
                if process.returncode or r['status']!='closed':raise ValueError(r.get('error','Runner did not close'))
                ev.verify_continuity(r['samples'])
                if name=='connected-input' and (len(images)!=5 or len(actions)!=4):raise ValueError('Missing two Cross cycles')
                result['journal']=r['journal']
            result.update(status='passed',images=images,external_keyboard_actions=actions)
        except BaseException as error:
            session.capture_failure(fault,error,phase,emit)
        finally:
            result.update(images=images,external_keyboard_actions=actions,
                          cleanup=dict(stop_requested=False,worker_killed=False),cleanup_errors=[],cleanup_errors_dropped=0)
            def cleanup_failure(label,error):
                record=session.publication_failure_record(error,'cleanup_'+label)
                if len(result['cleanup_errors'])<32:
                    result['cleanup_errors'].append(dict(step=label,error=record['message'],**record))
                else:result['cleanup_errors_dropped']+=1
                session.capture_failure(fault,error,'cleanup_'+label,emit)
            def cleanup_step(label, action):
                try:return action()
                except BaseException as error:
                    cleanup_failure(label,error)
            def stop_worker():
                if process is None:return
                code=cleanup_step('worker_poll',process.poll)
                if type(code) is not int:
                    def request_stop():
                        stop=out/'session/stop.request'
                        if stop.parent.exists():
                            stop.touch(exist_ok=True);result['cleanup']['stop_requested']=True
                    cleanup_step('worker_stop_request',request_stop)
                    try:
                        process.wait(timeout=8)
                    except BaseException as error:
                        cleanup_failure('worker_wait',error)
                        result['cleanup']['worker_killed']=True
                        cleanup_step('worker_kill',process.kill)
                        cleanup_step('worker_wait_after_kill',lambda:process.wait(timeout=5))
                code=cleanup_step('worker_final_poll',process.poll)
                confirmed=(type(code) is int and type(process.returncode) is int and code==process.returncode)
                result['cleanup']['worker_exit_confirmed']=confirmed
                result['cleanup']['worker_exit_code']=process.returncode
                if not confirmed:
                    cleanup_failure('worker_exit_confirmation',RuntimeError('Automated worker exit not confirmed'))
            cleanup_step('worker',stop_worker)
            if owned:
                cleanup_step('window_summary',lambda:result.update(window_observation=owned.summary()))
                cleanup_step('window_observer',owned.close)
            def read_cleanup_report():
                path=out/'session/supervisor.json'
                if path.exists():result['cleanup_transport']=json.loads(path.read_text())
                path=out/'session-result.json'
                if path.exists():
                    runner=json.loads(path.read_text())
                    result['runner_outcome']={k:runner[k] for k in ('status','error','first_failure',
                        'supervision_error','postmortem_error','normal_exit_verified') if k in runner}
            cleanup_step('supervisor_report',read_cleanup_report)
            cleanup_step('diagnostic_outcome',lambda:emit('cleanup_outcome',**result['cleanup'],
                errors=result['cleanup_errors'],transport=result.get('cleanup_transport')))
            try:
                result['supervision_diagnostics']=session.supervision_snapshot(dict(primary_failure=None,
                    secondary_failures=result['cleanup_errors'],secondary_dropped=result['cleanup_errors_dropped']))
                result['supervision_diagnostics_persistence']=dict(status='included',scope='automated-case-cleanup')
            except (OSError,ValueError,TypeError,RuntimeError,OverflowError) as error:
                result['supervision_diagnostics_persistence']=dict(status='failed',
                    error=session.publication_failure_record(error,'case_cleanup_diagnostics'))
                session.capture_failure(fault,error,'case_cleanup_diagnostics',emit)
            if fault.error is not None:
                first_phase=fault.record.get('phase',phase) if type(fault.record) is dict else phase
                result['acceptance_failure_details']=bounded_acceptance_failure(fault.error,first_phase)
            fault.update_result(result)
            session.write_session_result(root/(name+'-result.json'),result,fault,emit)
        if fault.error is not None:raise fault.error
    return result


class PhysicalFinalization:
    """Physical-only FIRST/SECOND accounting; no device access or retries."""
    def __init__(self, result):
        self.result = result
        self.first = self.first_record = None
        self.secondary = []
        self.dropped = 0
        self.children = {}
        self.stages = {}
        self.journal = None

    @staticmethod
    def describe(error, phase):
        from run_live_v2_session import publication_failure_record
        row = publication_failure_record(error, phase)
        if error.__cause__ is not None:
            row['cause'] = publication_failure_record(error.__cause__, 'cause')
        return row

    def failure(self, error, phase):
        if self.first is None:
            self.first = error
            self.first_record = self.describe(error, phase)
        elif error is not self.first:
            if len(self.secondary) < 32:
                self.secondary.append(self.describe(error, phase))
            else:
                self.dropped += 1
        self.result['status'] = 'failed'

    def attempt(self, phase, action):
        self.stages[phase] = dict(attempted=True, completed=False)
        try:
            value = action()
            self.stages[phase]['completed'] = True
            return value
        except BaseException as error:
            self.failure(error, phase)
        return None

    @contextmanager
    def stream(self, path, mode, phase):
        stream = path.open(mode)
        try:
            yield stream
        except BaseException as error:
            self.failure(error, phase)
            raise
        finally:
            self.attempt(phase+'_close', stream.close)

    def child(self, name, process, stop, timeout):
        if process is None:
            return
        record = dict(pid=None, observed_exit_codes=[], termination_attempted=False,
                      cleanup_confirmed=False, final_exit_code=None)
        self.children[name] = record
        record['pid'] = self.attempt(name+'_identity', lambda: process.pid)
        if type(record['pid']) is not int or record['pid'] <= 0:
            record['pid'] = None
            self.failure(RuntimeError('Child identity unavailable'), name+'_identity')

        def status():
            code = process.poll()
            if code is not None and type(code) is not int:
                raise RuntimeError('Invalid child process status')
            if code is not None:
                record['observed_exit_codes'].append(code)
            return code

        code = self.attempt(name+'_poll', status)
        if code is None:
            self.attempt(name+'_stop', lambda: stop.touch(exist_ok=True))
            waited = self.attempt(name+'_wait', lambda: process.wait(timeout=timeout))
            if type(waited) is int:
                record['observed_exit_codes'].append(waited)
            code = self.attempt(name+'_cleanup_poll', status)
            if code is None:
                record['termination_attempted'] = True
                self.attempt(name+'_kill', process.kill)
                waited = self.attempt(name+'_wait_after_kill', lambda: process.wait(timeout=5))
                if type(waited) is int:
                    record['observed_exit_codes'].append(waited)
        code = self.attempt(name+'_final_poll', status)
        returned = self.attempt(name+'_returncode', lambda: process.returncode)
        record['final_exit_code'] = code
        record['cleanup_confirmed'] = type(code) is int and type(returned) is int and code == returned
        if not record['cleanup_confirmed']:
            self.failure(RuntimeError('Final child exit not confirmed'), name+'_exit_confirmation')
        elif code != 0 or record['termination_attempted']:
            self.failure(RuntimeError('Child did not exit normally'), name+'_exit')

    def snapshot(self):
        value = dict(schema_version=1, first_failure=self.first_record,
                     secondary_failures=list(self.secondary), secondary_dropped=self.dropped,
                     children=self.children, stages=self.stages)
        while len(json.dumps(value, allow_nan=False).encode('utf-8')) > 65536 and value['secondary_failures']:
            value['secondary_failures'].pop()
            value['secondary_dropped'] += 1
        return value

    def raise_first(self):
        if self.first is not None:
            self.first.physical_finalization = self.snapshot()
            raise self.first

    def publish(self, path):
        """One exclusive write. Never repair, replace or retry a partial result."""
        self.result['physical_finalization'] = self.snapshot()
        if self.first is not None:
            self.result.update(status='failed', error=self.first_record['message'],
                               first_failure=self.first_record)
        # A readable payload alone cannot prove that write/close completed.
        self.result['result_publication'] = dict(status='payload',
            observation='Successful write and close required; file existence alone is insufficient')
        stream=None;publication_failures=[]
        def failed(error,phase):
            self.failure(error,phase)
            publication_failures.append(self.describe(error,phase))
        try:
            raw = json.dumps(self.result, indent=2, allow_nan=False)+'\n'
            stream=path.open('x', encoding='utf-8')
            if stream.write(raw) != len(raw):
                raise OSError('Incomplete physical result write')
        except BaseException as error:
            # Latch write/short-write FIRST before close can raise. Implicit
            # exception context is not a substitute for explicit SECOND records.
            failed(error,'physical_result_publication')
        finally:
            if stream is not None:
                try:
                    stream.close()
                except BaseException as error:
                    failed(error,'physical_result_close')
        if publication_failures:
            self.result.update(status='failed', error=self.first_record['message'], first_failure=self.first_record)
            self.result['result_publication'] = dict(status='failed', failure=publication_failures[0],
                                                     failures=publication_failures)
            self.result['physical_finalization'] = self.snapshot()
            if self.journal is not None:
                self.attempt('physical_publication_failure_journal', lambda: self.journal.emit(
                    'physical_result_publication_failed', finalization=self.snapshot(),
                    publication=self.result['result_publication']))
            self.result['physical_finalization'] = self.snapshot()
            self.first.physical_result_publication_failed = True
            self.first.physical_result_publication_failure = self.result['result_publication']
        self.raise_first()


HOTPLUG_ENDPOINT_FIELDS = frozenset(('token', 'available', 'device_state', 'muted', 'volume', 'same_device_volume'))


class PhysicalMutedEndpoint(LegacyHotplugEndpoint):
    """Safer physical-only lifecycle; legacy protocol/reader remain unchanged."""
    def __init__(self, helper, output, finalizer):
        self.finalizer = finalizer
        self.report, self.stop, self.ready = (output/name for name in
            ('endpoint.jsonl', 'endpoint-stop.request', 'endpoint-ready.txt'))
        self.all_render = False
        self.child = self.errors = None
        self.cleanup_confirmed = False
        try:
            self.errors = (output/'endpoint-stderr.txt').open('xb')
            self.child = subprocess.Popen([str(helper.resolve()), '--watch', str(self.report),
                str(self.stop), str(self.ready), '600000'], stdout=subprocess.DEVNULL, stderr=self.errors)
        except BaseException as error:
            finalizer.failure(error, 'endpoint_launch')
            self.finish()
            finalizer.raise_first()

    def __enter__(self):
        # Legacy __enter__ calls __exit__ on startup failure; our outer caller
        # owns exactly one cleanup attempt instead.
        import time
        deadline = time.monotonic()+10
        while not self.ready.exists():
            self.check()
            if time.monotonic() >= deadline:
                raise RuntimeError('Endpoint observer not ready; no guest will be launched')
            time.sleep(.025)
        self.check()
        self.require_hotplug_schema(deadline)
        return self

    def require_hotplug_schema(self, deadline):
        """The plain observer also accepts --watch but rejects every default change
        (physical-recovery-v2-001). Before any SDL observer or guest, require the
        separately approved hotplug observer's own first sample schema."""
        while True:
            self.check()
            lines = self.report.read_bytes().split(b'\n') if self.report.exists() else []
            if len(lines) > 1:
                break  # A newline-terminated first record; a partial line is still pending.
            if time.monotonic() >= deadline:
                raise RuntimeError('Endpoint observer wrote no complete first sample; no guest will be launched')
            time.sleep(.025)
        try:
            first = json.loads(lines[0])
        except ValueError:
            first = None
        endpoints = first.get('endpoints') if isinstance(first, dict) else None
        if (not isinstance(first, dict) or first.get('schema_version') != 1 or first.get('event') != 'sample' or
                type(first.get('default_token')) is not int or first.get('default_changed') is not False or
                not isinstance(endpoints, list) or not endpoints or
                any(not isinstance(row, dict) or not HOTPLUG_ENDPOINT_FIELDS <= set(row) for row in endpoints)):
            raise RuntimeError('Endpoint observer is not the separately approved hotplug observer; '
                               'no guest will be launched')

    def finish(self):
        self.finalizer.attempt('endpoint_finalization', lambda:
            self.finalizer.child('endpoint', self.child, self.stop, 5))
        if self.child is not None:
            self.cleanup_confirmed = self.finalizer.children['endpoint']['cleanup_confirmed']
        if self.errors is not None:
            self.finalizer.attempt('endpoint_stderr_close', self.errors.close)

def run_physical(args,root,endpoint,finalizer):
    """Future opt-in collector. Never called by automated modes or host CI."""
    from live_av_v2_guide import Protocol,Guide
    from pad_hotplug_guest_tests import read_lines
    from live_av_v2_contract import verify_inputs
    verify_inputs(args.engine,args.engine_report,args.fixture)
    metadata=json.loads((args.sdl_observer.parent/'build.json').read_text())
    if (metadata['probe_sha256']!=startup.digest(args.sdl_observer) or
        metadata['engine_sha256']!=startup.digest(args.engine) or
        metadata['source_lf_sha256']!=hashlib.sha256((ROOT/'tests/dualsense_sdl_probe.cpp').read_bytes().replace(b'\r\n',b'\n')).hexdigest() or
        metadata['sdl_static_library_sha256']!=startup.digest(args.engine.parent/'externals/sdl3/SDL3-static.lib')):
        raise ValueError('Physical observer source/engine/SDL attestation mismatch')
    sources=[Path(__file__),ROOT/'tests/live_av_v2_guide.py',ROOT/'tools/live_av_v2_evidence.py',
        ROOT/'tools/live_av_v2_contract.py',ROOT/'tools/run_live_v2_session.py',
        ROOT/'tools/live_v2_diagnostics.py',
        ROOT/'research/homebrew/live_av_v2/main.cpp',ROOT/'tests/dualsense_sdl_probe.cpp',
        ROOT/'tests/owned_window_trace.py',ROOT/'tests/hotplug_endpoint.py']
    for source in sources:
        target=root/'tested-source'/source.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(source.read_bytes())
    context=dict(inputs={k:dict(path=str(getattr(args,k)),sha256=startup.digest(getattr(args,k))) for k in
        ('engine','engine_report','fixture','supervisor','sdl_observer','muted_endpoint_observer')},
        source_sha256={p.relative_to(ROOT).as_posix():startup.digest(p) for p in sources},scenario=args.physical_scenario)
    (root/'collection-context.json').write_text(json.dumps(context,indent=2)+'\n')
    protocol=Protocol(args.physical_scenario,physical_authorized=args.physical_test_authorized,
        disconnect_authorized=args.disconnect_authorized,reconnect_authorized=args.reconnect_authorized)
    observer=process=owned=guide=None;phases=[];pending={};seen=set();current=None;rows=[];close={'ownership_failed':False}
    result=finalizer.result
    last_sequence=-1
    def emit(event,**fields):
        record=dict(fields)
        record.setdefault('qpc_seconds',time.perf_counter())
        record['event']=event
        with (root/'window.jsonl').open('a',encoding='utf-8') as f:
            f.write(json.dumps(record)+'\n')
    def budget():
        guide.pump();endpoint.check()
        if observer is not None and observer.poll() is not None:raise ValueError('SDL observer stopped; no retry')
    def before_close():
        owned.poll();close['last_owned_qpc_seconds']=time.perf_counter()
        close.update(root_pid=owned.pid,bound_window=owned.window)
        progress=optional_progress(root/'guest',emit)
        if not progress or not progress['samples'] or progress['samples'][-1]['state']!=ev.expected_control(protocol.plan[-1])[0]:
            raise ValueError('Wrong final Pad connection state before close')
    protocol.before_close=before_close
    try:
        guide=Guide(protocol,root/'human-confirmations.jsonl')
        # Wait for a real Ready click before launching observer or guest.
        while protocol.mode=='ready':budget();time.sleep(.025)
        with finalizer.stream(root/'native-stdout.json','wb','native_stdout') as so,\
             finalizer.stream(root/'native-stderr.txt','wb','native_stderr') as se:
            command=[str(args.sdl_observer),'--watch-hotplug' if args.physical_scenario=='recovery' else '--watch-disconnect',
                str(root/'native.jsonl'),str(root/'native-stop.request'),str(root/'native-ready.txt'),'390000','--disconnect-authorized']
            if args.physical_scenario=='recovery':command.append('--reconnect-authorized')
            observer=subprocess.Popen(command,stdout=so,stderr=se,**startup.background_process_options())
            began=time.perf_counter()
            while not (root/'native-ready.txt').exists():
                budget()
                if time.perf_counter()-began>10:raise ValueError('SDL observer not ready within ten seconds')
                time.sleep(.025)
            options={k:str(getattr(args,k)) for k in ('engine','engine_report','fixture','supervisor')}
            options.update(output=str(root/'guest'),volume_percent=0,cross_key=args.cross_key)
            config=root/'guest-options.json';config.write_text(json.dumps(options))
            with finalizer.stream(root/'guest-console.txt','wb','worker_console') as log:
                process=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'worker',str(config)],
                    stdout=log,stderr=subprocess.STDOUT,**startup.background_process_options())
                while process.poll() is None:
                    budget();state=optional_progress(root/'guest',emit)
                    native=read_lines(root/'native.jsonl')
                    if not state or not state['running_observed']:time.sleep(.025);continue
                    rows=state['samples']
                    if rows[-1]['sequence']!=last_sequence:
                        last_sequence=rows[-1]['sequence'];close['last_guest_seen_qpc_seconds']=time.perf_counter()
                    if owned is None:owned=OwnedWindowTrace(windows._owned_window(state['supervisor_pid'],args.engine),emit,lifecycle=True)
                    instructions=[e for e in protocol.events if e['event']=='normal_close_instruction']
                    if instructions:
                        close['instruction_qpc_seconds']=instructions[0]['qpc_seconds']
                        if time.perf_counter()-close['instruction_qpc_seconds']>30:raise ValueError('Human close budget expired')
                        time.sleep(.025);continue
                    try:owned.poll()
                    except (OSError,RuntimeError):close['ownership_failed']=True;raise
                    if protocol.index==len(protocol.plan):time.sleep(.025);continue
                    if current is None or current['index']!=protocol.index:
                        current=dict(index=protocol.index,label=protocol.plan[protocol.index],guest_after_observed_us=rows[-1]['observed_us'])
                    instruction=[e for e in protocol.events if e['index']==protocol.index and e['event'] in ('action','usb_action_instruction')]
                    removed=[e for e in native if e['event']=='hotplug_removed'];opened=[e for e in native if e['event']=='hotplug_opened']
                    unplug=[e for e in protocol.events if e['event']=='usb_action_instruction' and protocol.plan[e['index']]=='disconnected']
                    reconnect=[e for e in protocol.events if e['event']=='usb_action_instruction' and protocol.plan[e['index']]=='reconnected-neutral']
                    if removed and not unplug:raise ValueError('USB removed before explicit instruction')
                    if len(opened)>1 and not reconnect:raise ValueError('USB added before explicit instruction')
                    if reconnect and len(opened)<2 and time.perf_counter()-reconnect[-1]['qpc_seconds']>30:
                        raise ValueError('Reconnect exceeded 30 seconds from explicit instruction')
                    if not instruction:time.sleep(.025);continue
                    current['instruction_qpc_seconds']=instruction[-1]['qpc_seconds']
                    f=opened[0]['qpc_frequency'];label=current['label']
                    guest,duration=ev.stable_suffix(rows,label,after=current['guest_after_observed_us']/1e6)
                    sdl,seconds=ev.stable_suffix([e for e in native if e['event']=='hotplug_state'],label,native=True,
                        after=current['instruction_qpc_seconds'],frequency=f)
                    spacing=label!='disconnected-progress' or rows[-1]['observed_us']-rows[phases[-1]['sequence']]['observed_us']>=5000000
                    if protocol.mode=='qualifying' and spacing and min(duration,seconds)>=3 and min(len(guest),len(sdl))>=20:
                        protocol.capture();guide.render()
                    paths=sorted(set((root/'guest/session/user/screenshots').glob('*.png'))-seen)
                    if len(paths)>1:raise ValueError('Extra physical screenshot; no retry')
                    for path in paths:
                        if protocol.mode not in ('capture','waiting-image'):raise ValueError('Early physical screenshot')
                        if not readback_ready(path,pending) or protocol.mode!='waiting-image':continue
                        seq=ev.image_sequence(path)
                        if seq>=len(rows):continue
                        image=ev.verify_image(path,(root/'guest/session/app/palette.bin').read_bytes(),rows[seq])
                        _,held=ev.stable_suffix(rows[:seq+1],label,after=current['guest_after_observed_us']/1e6)
                        if held<3 or not ev.matches(rows[seq],label):raise ValueError('Wrong/short-held physical capture')
                        phases.append(dict(**current,**image,capture_qpc_seconds=time.perf_counter(),path=str(path.relative_to(root))))
                        seen.add(path);protocol.verified();guide.render()
                    time.sleep(.025)
                process.wait(timeout=8)
                close['root_exit_qpc_seconds']=close['finished_qpc_seconds']=time.perf_counter()
                if not close.get('instruction_qpc_seconds'):raise ValueError('Guest exited before explicit human close')
                while protocol.mode!='closed':budget();time.sleep(.025)
                close['confirmed_qpc_seconds']=protocol.events[-1]['qpc_seconds']
                while True:
                    budget();native=read_lines(root/'native.jsonl');states=[r for r in native if r['event']=='hotplug_state']
                    if states and states[-1]['qpc']/f>=max(close['finished_qpc_seconds'],close['confirmed_qpc_seconds']):break
                    time.sleep(.025)
    except BaseException as error:
        finalizer.failure(error,'physical_collection')
    finally:
        finalizer.attempt('worker_finalization',lambda:
            finalizer.child('worker',process,root/'guest/session/stop.request',8))
        if owned is not None:
            result['window_observation']=finalizer.attempt('window_summary',owned.summary)
            finalizer.attempt('window_close',owned.close)
        finalizer.attempt('sdl_finalization',lambda:
            finalizer.child('sdl',observer,root/'native-stop.request',5))
        if finalizer.children.get('sdl',{}).get('termination_attempted'):
            result['observer_forced_cleanup']=True
        if guide is not None:
            finalizer.attempt('guide_close',guide.close)
        result.update(phases=phases,close=close)
    finalizer.raise_first()
    # Final checks retain incomplete/failed original evidence; no automatic retry.
    if process.returncode or observer.returncode or result.get('observer_forced_cleanup'):raise ValueError('Guest/observer did not exit normally')
    final=json.loads((root/'guest/session-result.json').read_text());rows=final['samples']
    wait_dead(final['transport']['root_pid'])
    close['last_guest_observed_us']=rows[-1]['observed_us']
    ev.verify_confirmations(protocol.events,phases,protocol.plan,close)
    result['acceptance']=ev.verify_physical(read_lines(root/'native.jsonl',final=True),rows,phases,protocol.plan,final['transport'],close)
    for p in phases:ev.verify_image(root/p['path'],(root/'guest/session/app/palette.bin').read_bytes(),rows[p['sequence']])
    if set((root/'guest/session/user/screenshots').glob('*.png'))!=seen:raise ValueError('Unqualified extra screenshot')
    result.update(status='passed',journal=final['journal'])
    return result


def collect_physical(args,root):
    """Keep physical finalization outside qualification and all helper lifetimes."""
    result=dict(status='failed',scenario=args.physical_scenario,profile='live-av-v2',
        automatic_retry_performed=False,synthetic_input_sent=False,pcm_correctness_tested=False,
        audio_policy='legacy-hotplug-per-seen-default-not-option-a',option_a_acceptance=False)
    finalizer=PhysicalFinalization(result)
    endpoint=None
    try:
        finalizer.journal=Diagnostics(root/'physical-finalization.jsonl')
        endpoint=PhysicalMutedEndpoint(args.muted_endpoint_observer,root,finalizer)
        endpoint.__enter__()
        run_physical(args,root,endpoint,finalizer)
    except BaseException as error:
        finalizer.failure(error,'physical_acceptance')
    finally:
        if endpoint is not None:
            finalizer.attempt('endpoint_finish',endpoint.finish)
            if not endpoint.cleanup_confirmed:
                finalizer.failure(RuntimeError('Endpoint cleanup is unconfirmed'),'endpoint_cleanup')
            result['endpoint']=finalizer.attempt('endpoint_evidence',lambda: validate_hotplug(root/'endpoint.jsonl'))
        finalizer.publish(root/'physical-result.json')
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('engine','engine-report','fixture','supervisor','muted-endpoint-observer','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--case',choices=CASES)
    parser.add_argument('--cross-key',choices=('n','g'),default='n')
    parser.add_argument('--physical-scenario',choices=('recovery','disconnected-close'))
    parser.add_argument('--sdl-observer',type=Path)
    parser.add_argument('--endpoint-inventory',type=Path,
        help='Explicit expected active-render identities and all three default roles; required only for automated Option A')
    for flag in ('physical-test-authorized','disconnect-authorized','reconnect-authorized','hotplug-endpoint-protocol-authorized'):
        parser.add_argument('--'+flag,action='store_true')
    args=parser.parse_args()
    if args.physical_scenario:
        if args.endpoint_inventory is not None:
            parser.error('Option A inventory is not the separate physical HotplugEndpoint protocol')
        if (args.case or not args.sdl_observer or not args.physical_test_authorized or not args.disconnect_authorized or
            not args.hotplug_endpoint_protocol_authorized or
            (args.physical_scenario=='recovery')!=args.reconnect_authorized):
            parser.error('New separate physical/scenario/USB/endpoint permissions required; no session started')
    elif any((args.physical_test_authorized,args.disconnect_authorized,args.reconnect_authorized,args.hotplug_endpoint_protocol_authorized,args.sdl_observer)):
        parser.error('Physical permissions/helpers forbidden in automated regressions')
    elif args.endpoint_inventory is None:
        parser.error('Automated Option A requires an explicit fixed endpoint inventory; no session started')
    if sys.platform!='win32':parser.error('Real guest regression requires Windows')
    for k,v in vars(args).items():
        if isinstance(v,Path):setattr(args,k,v.resolve())
    expected_inventory=None if args.physical_scenario else load_fixed_inventory(args.endpoint_inventory)
    args.output.mkdir(parents=True,exist_ok=False)
    if args.physical_scenario:
        collect_physical(args,args.output)
        return
    records=[];endpoint=None;fault=FirstFailure()
    diagnostics=Diagnostics(args.output/'acceptance-diagnostics.jsonl')
    phase='fixed_endpoint_policy_startup'
    result=dict(status='failed',cases=records,physical_input_tested=False,
        audio_policy='option-a-fixed-all-active-render-sampled',
        observation='Sampled observations only; no real-time routing or acoustic silence guarantee')
    emit=finalization_emitter(diagnostics.emit,result)
    try:
        endpoint=MutedEndpoint(args.muted_endpoint_observer,args.output,
            all_render=True,fixed_inventory=expected_inventory)
        with endpoint:
            require_fixed_guard(endpoint)
            for name in ((args.case,) if args.case else CASES):
                phase='automated_case_'+name
                records.append(run_case(args,args.output,name,endpoint))
            phase='fixed_endpoint_policy_finalization'
        if not endpoint.cleanup_confirmed or endpoint.fixed_summary is None:
            raise RuntimeError('Fixed endpoint guard completion is not verified')
        result.update(status='passed',endpoint=endpoint.fixed_summary)
    except BaseException as error:
        session.capture_failure(fault,error,phase,emit)
    finally:
        result['endpoint_cleanup_confirmed']=bool(endpoint and endpoint.cleanup_confirmed)
        try:
            result['supervision_diagnostics']=session.supervision_snapshot(dict(
                primary_failure=None,secondary_failures=endpoint.cleanup_failures if endpoint else
                    getattr(fault.error,'endpoint_cleanup_failures',[]),secondary_dropped=0))
            result['supervision_diagnostics_persistence']=dict(status='included',scope='endpoint-guard-cleanup')
        except (OSError,ValueError,TypeError,RuntimeError,OverflowError) as error:
            result['supervision_diagnostics_persistence']=dict(status='failed',
                error=session.publication_failure_record(error,'endpoint_cleanup_diagnostics'))
            session.capture_failure(fault,error,'endpoint_cleanup_diagnostics',emit)
        if fault.error is not None:
            first_phase=fault.record.get('phase',phase) if type(fault.record) is dict else phase
            result['acceptance_failure_details']=bounded_acceptance_failure(fault.error,first_phase)
        fault.update_result(result)
        session.write_session_result(args.output/'summary.json',result,fault,emit)
    if fault.error is not None:raise fault.error
    print(json.dumps(dict(status='passed',cases=len(records))))


if __name__=='__main__':
    sys.exit(worker(Path(sys.argv[2])) if len(sys.argv)>1 and sys.argv[1]=='worker' else main())
