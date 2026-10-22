# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
"""Bounded AUTOMATED guest regressions. Never physical USB recovery evidence.

No device setting setters. Mandatory read-only mute guard before guest launch.
Keyboard and window messages belong only to this explicit acceptance driver.
"""
import argparse
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
from muted_endpoint import MutedEndpoint, validate_report
from dualsense_evidence import readback_ready
from owned_window_trace import OwnedWindowTrace
from live_session_guest_tests import wait_dead
from live_v2_diagnostics import Diagnostics, FirstFailure

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
    diagnostics=Diagnostics(root/(name+'-window.jsonl'));emit=diagnostics.emit
    fault=FirstFailure();phase='startup';cursor=0;previous=None
    with (root/(name+'-console.txt')).open('wb') as log:
        process=None;began=time.monotonic();closing=False
        try:
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
            fault.capture(error,phase,emit)
        finally:
            result.update(images=images,external_keyboard_actions=actions,
                          cleanup=dict(stop_requested=False,worker_killed=False),cleanup_errors=[])
            def cleanup_step(label, action):
                try:action()
                except BaseException as error:
                    result['cleanup_errors'].append(dict(step=label,error=str(error)))
                    fault.capture(error,'cleanup_'+label,emit)
            def stop_worker():
                if process is None:return
                if process.poll() is None:
                    stop=out/'session/stop.request'
                    if stop.parent.exists():
                        stop.touch(exist_ok=True);result['cleanup']['stop_requested']=True
                    try:process.wait(timeout=8)
                    except subprocess.TimeoutExpired:
                        result['cleanup']['worker_killed']=True
                        process.kill();process.wait(timeout=5)
                result['cleanup']['worker_exit_code']=process.returncode
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
            fault.update_result(result)
            fault.write_result(root/(name+'-result.json'),result,emit)
        if fault.error is not None:raise fault.error
    return result


def run_physical(args,root,endpoint):
    """Future opt-in collector. Never called by automated modes or host CI."""
    from live_av_v2_guide import Protocol,Guide
    from pad_hotplug_guest_tests import read_lines
    from live_av_v2_contract import verify_inputs
    verify_inputs(args.engine,args.engine_report,args.fixture)
    arrival_mode=getattr(args,'arrival_diagnostics_v1',False)
    if arrival_mode:
        from build_arrival_probe_v1 import verify_probe
        verify_probe(args.sdl_observer,args.engine,args.engine_report)
    else:
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
    if arrival_mode:
        from build_arrival_probe_v1 import SOURCES
        sources+=list(dict.fromkeys(ROOT/p for p in (*SOURCES,'tools/arrival_diagnostics_v1.py','tools/build_arrival_probe_v1.py') if ROOT/p not in sources))
        target=root/'arrival-build-v1.json';target.write_bytes((args.sdl_observer.parent/target.name).read_bytes())
    for source in sources:
        target=root/'tested-source'/source.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(source.read_bytes())
    context=dict(inputs={k:dict(path=str(getattr(args,k)),sha256=startup.digest(getattr(args,k))) for k in
        ('engine','engine_report','fixture','supervisor','sdl_observer','muted_endpoint_observer')},
        source_sha256={p.relative_to(ROOT).as_posix():startup.digest(p) for p in sources},scenario=args.physical_scenario)
    (root/'collection-context.json').write_text(json.dumps(context,indent=2)+'\n')
    protocol=Protocol(args.physical_scenario,physical_authorized=args.physical_test_authorized,
        disconnect_authorized=args.disconnect_authorized,reconnect_authorized=args.reconnect_authorized)
    guide=Guide(protocol,root/'human-confirmations.jsonl')
    observer=process=owned=None;phases=[];pending={};seen=set();current=None;rows=[];close={'ownership_failed':False}
    result=dict(status='failed',scenario=args.physical_scenario,profile='live-av-v2',
        automatic_retry_performed=False,synthetic_input_sent=False,pcm_correctness_tested=False)
    arrival_fault=FirstFailure() if arrival_mode else None
    last_sequence=-1;guest_trace=None;diagnostic_close_error=None
    def emit(event,**fields):
        record=dict(fields)
        record.setdefault('qpc_seconds',time.perf_counter())
        record['event']=event
        with (root/'window.jsonl').open('a',encoding='utf-8') as f:
            f.write(json.dumps(record)+'\n')
    def cleanup_step(name,action):
        if not arrival_mode:return action()
        try:return action()
        except BaseException as error:
            arrival_fault.capture(error,'arrival_cleanup_'+name)
            result.setdefault('arrival_cleanup_errors',[]).append(dict(step=name,type=type(error).__name__,message=str(error)))
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
        if arrival_mode:
            from arrival_diagnostics_v1 import GuestTrace
            guest_trace=GuestTrace(root/'arrival-guest-v1.jsonl')
        # Wait for a real Ready click before launching observer or guest.
        while protocol.mode=='ready':budget();time.sleep(.025)
        with (root/'native-stdout.json').open('wb') as so,(root/'native-stderr.txt').open('wb') as se:
            command=[str(args.sdl_observer),'--watch-hotplug' if args.physical_scenario=='recovery' else '--watch-disconnect',
                str(root/'native.jsonl'),str(root/'native-stop.request'),str(root/'native-ready.txt'),'390000','--disconnect-authorized']
            if args.physical_scenario=='recovery':command.append('--reconnect-authorized')
            if arrival_mode:
                command[1]='--watch-arrival-v1'
                command.insert(6,str(root/'arrival-native-v1.jsonl'))
                command.append('--arrival-diagnostics-authorized')
            observer=subprocess.Popen(command,stdout=so,stderr=se,**startup.background_process_options())
            began=time.perf_counter()
            while not (root/'native-ready.txt').exists():
                budget()
                if time.perf_counter()-began>10:raise ValueError('SDL observer not ready within ten seconds')
                time.sleep(.025)
            options={k:str(getattr(args,k)) for k in ('engine','engine_report','fixture','supervisor')}
            options.update(output=str(root/'guest'),volume_percent=0,cross_key=args.cross_key)
            config=root/'guest-options.json';config.write_text(json.dumps(options))
            with (root/'guest-console.txt').open('wb') as log:
                process=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'worker',str(config)],
                    stdout=log,stderr=subprocess.STDOUT,**startup.background_process_options())
                while process.poll() is None:
                    budget();read_begin=time.perf_counter();state=optional_progress(root/'guest',emit);read_end=time.perf_counter()
                    native=read_lines(root/'native.jsonl')
                    if not state or not state['running_observed']:time.sleep(.025);continue
                    rows=state['samples']
                    if guest_trace:guest_trace.observe(rows,read_begin,read_end)
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
        result['error']=str(error)
        if arrival_fault:arrival_fault.capture(error,'arrival_physical_monitor')
        if guest_trace:
            try:guest_trace.fail(error)
            except BaseException as diagnostic_error:result['arrival_diagnostic_error']=str(diagnostic_error)
        raise
    finally:
        def finish_process():
            if process is not None and process.poll() is None:
                stop=root/'guest/session/stop.request'
                if stop.parent.exists():stop.touch(exist_ok=True)
                try:process.wait(timeout=8)
                except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
        def finish_observer():
            if observer is not None:
                (root/'native-stop.request').touch(exist_ok=True)
                try:observer.wait(timeout=5)
                except subprocess.TimeoutExpired:observer.kill();observer.wait(timeout=5);result['observer_forced_cleanup']=True
        def finish_owned():
            if owned:result['window_observation']=owned.summary();owned.close()
        cleanup_step('process',finish_process)
        cleanup_step('observer',finish_observer)
        cleanup_step('owned_window',finish_owned)
        if guest_trace:
            try:guest_trace.close()
            except BaseException as error:
                result['arrival_diagnostic_error']=str(error)
                if 'error' not in result:diagnostic_close_error=error
        cleanup_step('guide',guide.close)
        result.update(phases=phases,close=close)
        if arrival_fault:
            if diagnostic_close_error is not None:arrival_fault.capture(diagnostic_close_error,'arrival_guest_trace_close')
            arrival_fault.update_result(result)
        (root/'physical-result.json').write_text(json.dumps(result,indent=2)+'\n')
        if arrival_fault and arrival_fault.error is not None:raise arrival_fault.error
        if diagnostic_close_error is not None:raise diagnostic_close_error
    # Final checks retain incomplete/failed original evidence; no automatic retry.
    if process.returncode or observer.returncode or result.get('observer_forced_cleanup'):raise ValueError('Guest/observer did not exit normally')
    final=json.loads((root/'guest/session-result.json').read_text());rows=final['samples']
    wait_dead(final['transport']['root_pid'])
    close['last_guest_observed_us']=rows[-1]['observed_us']
    ev.verify_confirmations(protocol.events,phases,protocol.plan,close)
    result['acceptance']=ev.verify_physical(read_lines(root/'native.jsonl',final=True),rows,phases,protocol.plan,final['transport'],close)
    for p in phases:ev.verify_image(root/p['path'],(root/'guest/session/app/palette.bin').read_bytes(),rows[p['sequence']])
    if set((root/'guest/session/user/screenshots').glob('*.png'))!=seen:raise ValueError('Unqualified extra screenshot')
    if arrival_mode:
        import arrival_diagnostics_v1 as arrival
        native_diagnostic=arrival.load(root/'arrival-native-v1.jsonl')
        guest_diagnostic=arrival.load(root/'arrival-guest-v1.jsonl',1024*1024)
        arrival.validate_native(native_diagnostic)
        arrival.validate_guest(guest_diagnostic,rows)
        result['arrival_diagnostics']=arrival.boundaries(native_diagnostic,guest_diagnostic,rows,read_lines(root/'native.jsonl',final=True))
        if not result['arrival_diagnostics']['boundary_coverage_complete']:
            raise ValueError('Arrival boundary evidence incomplete; strict acceptance alone cannot qualify diagnostics')
    result.update(status='passed',journal=final['journal'])
    (root/'physical-result.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('engine','engine-report','fixture','supervisor','muted-endpoint-observer','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--case',choices=CASES)
    parser.add_argument('--cross-key',choices=('n','g'),default='n')
    parser.add_argument('--physical-scenario',choices=('recovery','disconnected-close'))
    parser.add_argument('--sdl-observer',type=Path)
    parser.add_argument('--arrival-diagnostics-v1',action='store_true',help='Separate attested observer and streams; recovery only')
    for flag in ('physical-test-authorized','disconnect-authorized','reconnect-authorized','hotplug-endpoint-protocol-authorized'):
        parser.add_argument('--'+flag,action='store_true')
    args=parser.parse_args()
    if args.arrival_diagnostics_v1 and args.physical_scenario!='recovery':
        parser.error('Arrival v1 requires separately authorized physical recovery; no automated mode')
    if args.physical_scenario:
        if (args.case or not args.sdl_observer or not args.physical_test_authorized or not args.disconnect_authorized or
            not args.hotplug_endpoint_protocol_authorized or
            (args.physical_scenario=='recovery')!=args.reconnect_authorized):
            parser.error('New separate physical/scenario/USB/endpoint permissions required; no session started')
    elif any((args.physical_test_authorized,args.disconnect_authorized,args.reconnect_authorized,args.hotplug_endpoint_protocol_authorized,args.sdl_observer)):
        parser.error('Physical permissions/helpers forbidden in automated regressions')
    if sys.platform!='win32':parser.error('Real guest regression requires Windows')
    for k,v in vars(args).items():
        if isinstance(v,Path):setattr(args,k,v.resolve())
    args.output.mkdir(parents=True,exist_ok=False)
    if args.physical_scenario:
        from hotplug_endpoint import MutedEndpoint as HotplugEndpoint,validate_report as validate_hotplug
        try:
            with HotplugEndpoint(args.muted_endpoint_observer,args.output) as endpoint:
                result=run_physical(args,args.output,endpoint)
            result['endpoint']=validate_hotplug(args.output/'endpoint.jsonl')
            (args.output/'physical-result.json').write_text(json.dumps(result,indent=2)+'\n')
        except BaseException as error:
            path=args.output/'physical-result.json'
            result=json.loads(path.read_text()) if path.exists() else {}
            if args.arrival_diagnostics_v1:
                fault=FirstFailure();fault.capture(error,'arrival_final_validation')
                result.setdefault('first_failure',fault.record)
                result.update(status='failed',error=result['first_failure']['message'])
            else:result.update(status='failed',error=str(error))
            path.write_text(json.dumps(result,indent=2)+'\n')
            raise
        return
    records=[]
    with MutedEndpoint(args.muted_endpoint_observer,args.output) as endpoint:
        for name in ((args.case,) if args.case else CASES):
            records.append(run_case(args,args.output,name,endpoint))
    result=dict(status='passed',cases=records,physical_input_tested=False,
        endpoint=validate_report(args.output/'endpoint.jsonl'))
    (args.output/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(status='passed',cases=len(records))))


if __name__=='__main__':
    sys.exit(worker(Path(sys.argv[2])) if len(sys.argv)>1 and sys.argv[1]=='worker' else main())
