# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
"""Opt-in human-assisted USB stick test. No injected inputs or disconnect test."""
import argparse
import hashlib
import json
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
import pad_axes_evidence as axes
import run_homebrew_startup as startup
import videoout_capture as windows
from dualsense_guide import Guide
from dualsense_evidence import append_progress, readback_ready
from muted_endpoint import MutedEndpoint, validate_report
from owned_window_trace import OwnedWindowTrace


def read_lines(path):
    if not path.exists(): return []
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines(keepends=True) if line.endswith('\n')]


def instruction(index, capture=False):
    label, target, sign = axes.PLAN[index]
    if target is None:
        title = 'BOTH STICKS CENTERED'
        text = 'Release both sticks completely. Leave every button and trigger untouched.'
    else:
        stick = 'LEFT' if target < 2 else 'RIGHT'
        direction = ('LEFT' if sign<0 else 'RIGHT') if target%2==0 else ('UP' if sign<0 else 'DOWN')
        title = f'HOLD {stick} STICK {direction}'
        text = f'Gently push the {stick} stick fully straight {direction} and KEEP HOLDING it there. Do not click the stick. Leave the other stick, buttons and triggers untouched. If F12 NOW does not appear, gently straighten the alignment without releasing; avoid a diagonal.'
    if capture:
        title = 'F12 NOW — '+title
        text += '\n\nPhysically press laptop F12 (Fn if needed), keeping this stick position until the panel advances.'
    else: text += '\n\nWait for F12 NOW before taking the screenshot. Use F12, not F11. Do not close the game before the final prompt.'
    return f'{index+1}/{len(axes.PLAN)} — '+title, text+'\n\nKeep the game focused and Windows muted. Do not disconnect USB.'


def _set_failure(result, error, phase):
    result['status'] = 'failed'
    if 'failure' not in result:
        prior = getattr(error, 'supervision_diagnostics', {}).get('primary_failure')
        result['failure'] = prior or startup.failure_details(error, phase)
        result['error'] = result['failure']['message']


def finish_observation(state, observer, emit, result, out, primary):
    """Always finish both observers; cleanup never replaces an existing error."""
    failures = []

    def attempt(phase, action):
        try:
            action()
        except BaseException as error:
            failures.append((error, phase))

    if state:
        attempt('window_summary', lambda: result.update(window_observation=state.summary()))
        attempt('window_snapshot', lambda: state.diagnostics.snapshot('supervision_finished'))
        attempt('window_observer_close', state.close)
    if observer:
        attempt('sdl_stop_request', lambda: (out/'physical-stop.request').touch(exist_ok=True))
        try:
            observer.wait(timeout=5)
        except subprocess.TimeoutExpired as timeout_error:
            error = RuntimeError('SDL axes observer needed termination')
            error.__cause__ = timeout_error
            failures.append((error, 'sdl_cleanup_timeout'))
            attempt('sdl_kill', observer.kill)
            attempt('sdl_wait_after_kill', lambda: observer.wait(timeout=5))
        except BaseException as error:
            failures.append((error, 'sdl_cleanup_wait'))
        result['sdl_observer_exit_code'] = observer.returncode
    if failures:
        result.setdefault('cleanup_failures', []).extend(startup.failure_details(e, p) for e, p in failures)
        recorded = len(failures)
        attempt('cleanup_evidence', lambda: emit('observation_cleanup_failures', failures=result['cleanup_failures']))
        # An evidence-write failure is secondary too; do not retry the write.
        for error, phase in failures[recorded:]:
            result['cleanup_failures'].append(startup.failure_details(error, phase))
        if primary is None:
            error, phase = failures[0]
            _set_failure(result, error, phase)
            raise error


def write_result(out, result):
    # Publish only after the new partial has been written and closed successfully.
    target, partial = out/'result.json', out/'result.partial.json'
    if target.exists(): raise FileExistsError('Result already exists; no overwrite')
    with partial.open('xb') as stream:
        stream.write((json.dumps(result,indent=2)+'\n').encode())
        stream.flush()
    partial.rename(target)


def finalize_result(out, result, guide, primary):
    """Preserve the primary even if postmortem collection/publication fails."""
    first = primary
    for phase, action in (
        ('failure_evidence', lambda: startup.collect_failure_evidence(out, result) if (out/'session').exists() else None),
        ('guide_close', guide.close),
    ):
        try:
            action()
        except BaseException as error:
            result.setdefault('cleanup_failures', []).append(startup.failure_details(error, phase))
            if first is None:
                first = error
                _set_failure(result, error, phase)
    try:
        write_result(out,result)
    except BaseException as error:
        result.setdefault('cleanup_failures', []).append(startup.failure_details(error, 'result_publication'))
        if first is None:
            first = error
            _set_failure(result, error, 'result_publication')
        # Last-resort diagnostics only; a failed sink cannot turn failure into success.
        try:
            print(json.dumps(dict(primary=result.get('failure'), cleanup_failures=result['cleanup_failures'])), file=sys.stderr)
        except BaseException:
            pass
    if first is not None and primary is None:
        raise first


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('engine','engine-report','fixture','supervisor','sdl-observer','muted-endpoint-observer','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    for name,value in vars(args).items(): setattr(args,name,value.resolve())
    args.output.mkdir(parents=True,exist_ok=False)
    out=args.output
    context=dict(inputs={name:dict(path=str(getattr(args,name)),sha256=startup.digest(getattr(args,name)))
                        for name in ('engine','engine_report','fixture','supervisor','sdl_observer','muted_endpoint_observer')},
                 source_lf_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes().replace(b'\r\n',b'\n')).hexdigest()
                                  for p in (Path(__file__),ROOT/'tools/pad_axes_evidence.py',ROOT/'tests/dualsense_sdl_probe.cpp',
                                            ROOT/'research/homebrew/pad_axes/main.cpp',ROOT/'tests/dualsense_guide.py',
                                            ROOT/'tests/owned_window_trace.py',ROOT/'tests/window_identity_diagnostics.py')},
                 keyboard_injection_performed=False,disconnect_test_authorized=False,automatic_retry_performed=False)
    (out/'collection-context.json').write_bytes((json.dumps(context,indent=2)+'\n').encode())
    result=dict(profile='pad-axes',status='failed',guest_completed=False,keyboard_injection_performed=False,
                automated_window_close_sent=False,disconnect_or_reconnect_tested=False,hardware_acoustic_output_tested=False)
    guide=Guide(out,axes.PLAN)
    guide.show('Analog stick test — controls untouched',
               'Keep Windows muted and USB connected. Click Ready when prepared to follow 17 steps beside the game. '
               'Move only the named stick; use F12 only when prompted. No audio or disconnect test is performed.')
    endpoint=None
    try:
        guide.wait_ready()
        endpoint=MutedEndpoint(args.muted_endpoint_observer,out,all_render=True)
        with endpoint:
            run(args,result,guide,endpoint)
        result['endpoint_observation']=validate_report(out/'endpoint.jsonl',all_render=True)
        result['status']='passed'
    except BaseException as error:
        _set_failure(result,error,'axes_session')
        raise
    finally:
        if endpoint is not None and endpoint.cleanup_failures:
            result.setdefault('cleanup_failures',[]).extend(endpoint.cleanup_failures)
        if endpoint is not None:
            result['endpoint_observer_exit_code']=endpoint.child.returncode
        finalize_result(out,result,guide,sys.exc_info()[1])
    print(json.dumps(dict(status=result['status'],phases=len(result['phases']))))


def run(args,result,guide,endpoint):
    out=args.output; work=out/'session'
    result['build']=startup.verify_inputs(args.engine,args.engine_report,args.fixture,'pad-axes')
    startup.prepare_session(work)
    (work/'user/config.json').write_text(json.dumps(dict(Log=dict(filter='*:info',flush_level='trace'))))
    app=work/'app'; app.mkdir()
    staged=app/'pad_axes.oelf'; shutil.copyfile(args.fixture,staged)
    if startup.digest(staged)!=startup.digest(args.fixture): raise ValueError('Staged axes fixture differs')
    palette=secrets.SystemRandom().sample(range(8),4); (app/'palette.bin').write_bytes(bytes(palette));result['palette']=palette
    observer=None; phases=[]; seen=set(); state=None; begun=time.monotonic(); closing=False
    pending_readbacks={}
    phase=None; capture_announced=False; latest=[]; previous_samples=0
    trace=work/'startup-audit.jsonl'
    def emit(event,**fields):
        with (out/'host-trace.jsonl').open('a',encoding='utf-8') as stream:
            stream.write(json.dumps(dict(event=event,monotonic=time.monotonic(),**fields))+'\n')
    def issue(index):
        nonlocal phase,capture_announced
        phase=dict(index=index,label=axes.PLAN[index][0],instruction_qpc_seconds=time.perf_counter(),
                   guest_after_elapsed_seconds=latest[-1]['elapsed_us']/1e6 if latest else 0)
        capture_announced=False
        title,text=instruction(index)
        emit('human_instruction',instruction=text,**phase)
        guide.show(title,text)
        append_progress(out/'progress.jsonl',dict(state='awaiting_physical_action',**phase))
    def poll():
        nonlocal latest,state,closing,capture_announced,previous_samples
        try:
            guide.pump();endpoint.check()
            if observer.poll() is not None: raise ValueError('Physical observer stopped; no automatic retry')
            if time.monotonic()-begun>540: raise ValueError('Human-assisted axes test exceeded 540-second budget')
            native=read_lines(out/'physical.jsonl')
            if any(r['event']=='removed' or (r['event'] in ('state','axis_state') and not r['connected']) for r in native):
                raise ValueError('Unexpected USB disconnect; reconnect is not authorized')
            current=axes.progress(startup.read_events(trace));latest=current['samples']
            if not current['running_observed']:
                if time.monotonic()-begun>30: raise ValueError('Axes guest startup readiness exceeded 30 seconds')
                return False
            if state is None:
                state=OwnedWindowTrace(windows._owned_window(owner[0],args.engine),emit,lifecycle=True)
                issue(0)
            if not closing:
                try: state.poll()
                except RuntimeError:
                    diagnostic=dict(expected_window=state.window,expected_root_pid=state.pid)
                    try:
                        _,window,pid=windows._owned_window(owner[0],args.engine)
                        diagnostic.update(current_owned_window=window,current_root_pid=pid)
                    except (OSError,ValueError) as error: diagnostic['owned_window_discovery_error']=str(error)
                    emit('window_identity_failure_postmortem',**diagnostic)
                    raise  # Record only. Never rebind, restore focus or bypass ownership.
            if len(latest)>previous_samples:
                emit('guest_observations_received',first=previous_samples,last=len(latest)-1,qpc_seconds=time.perf_counter())
                previous_samples=len(latest)
            if closing:return False
            opened=next(r for r in native if r['event']=='opened')
            raw_states=[r for r in native if r['event']=='axis_state']
            good_sdl,sdl_seconds=axes.stable_suffix(raw_states,axes.PLAN[phase['index']],sdl=True,
                after=phase['instruction_qpc_seconds'],frequency=opened['qpc_frequency'])
            good_guest,guest_seconds=axes.stable_suffix(latest,axes.PLAN[phase['index']],after=phase['guest_after_elapsed_seconds'])
            if not capture_announced and min(sdl_seconds,guest_seconds)>=3 and len(good_sdl)>=20 and len(good_guest)>=20:
                capture_announced=True
                append_progress(out/'progress.jsonl',dict(state='ready_for_human_f12',sdl_seconds=sdl_seconds,guest_seconds=guest_seconds,**phase))
                guide.show(*instruction(phase['index'],capture=True))
            paths=set((work/'user/screenshots').glob('*.png'))-seen
            for path in sorted(paths):
                if not readback_ready(path,pending_readbacks): continue
                if not capture_announced: raise ValueError('Screenshot taken before stable analog phase qualification')
                sequence=axes.image_sequence(path)
                if sequence>=len(latest): continue  # Its completed flip may precede its audit line.
                sample=latest[sequence]
                image=axes.verify_image(path,bytes(palette),sample)
                if not axes.matches(sample['axes'],sample['buttons'],sample['connected'],axes.PLAN[phase['index']]):
                    raise ValueError('Screenshot does not show requested actual guest stick position')
                _,duration=axes.stable_suffix(latest[:sequence+1],axes.PLAN[phase['index']],after=phase['guest_after_elapsed_seconds'])
                if duration<3 or sdl_seconds<3: raise ValueError('Stick released before capture was qualified')
                phases.append(dict(**phase,**image,path=str(path.relative_to(out)),capture_qpc_seconds=time.perf_counter(),
                                   stable_sdl_seconds=sdl_seconds,stable_guest_seconds=duration))
                seen.add(path);emit('image_verified',**phases[-1])
                append_progress(out/'progress.jsonl',dict(state='phase_verified',completed=len(phases),label=phase['label']))
                if len(phases)==len(axes.PLAN):
                    closing=True;guide.finish()
                else:issue(len(phases))
            return False
        except (RuntimeError,KeyError,StopIteration) as error:
            raise ValueError(str(error)) from error
    owner=[]
    try:
        with (out/'sdl-stdout.json').open('wb') as so,(out/'sdl-stderr.txt').open('wb') as se:
            observer=subprocess.Popen([str(args.sdl_observer),'--watch-axes',str(out/'physical.jsonl'),
                str(out/'physical-stop.request'),str(out/'physical-ready.txt'),'570000'],stdout=so,stderr=se,**startup.background_process_options())
            deadline=time.monotonic()+10
            while not (out/'physical-ready.txt').exists():
                guide.pump();endpoint.check()
                if observer.poll() is not None or time.monotonic()>deadline:raise ValueError('Wired SDL axes observer did not become ready')
                time.sleep(.025)
            command=[args.engine,'--game',staged,'--ignore-game-patch','--startup-audit',trace]
            result['command']=list(map(str,command))
            result['transport']=startup.supervise(args.supervisor,command,work,None,poll,on_started=owner.append,
                diagnostics=result.setdefault('supervision_diagnostics',{}))
    finally:
        result['phases']=phases
        primary_error=sys.exc_info()[1]
        finish_observation(state,observer,emit,result,out,primary_error)
    transport=result['transport']
    if (transport['reason']!='exited' or transport['exit_code']!=0 or transport['forced_termination'] or
            transport['active_before_cleanup']!=0 or not transport['tree_cleanup'] or not transport['root_exit_verified'] or
            transport.get('owner_watch_verified') is not True or observer.returncode):
        raise ValueError('Normal user close and empty process tree were not verified')
    samples=axes.progress(startup.read_events(trace,final=True))['samples'];result['samples']=samples
    result['guest_records']=axes.verify_records((work/'user/data/pad-axes.bin').read_bytes(),samples)
    result['physical_verification']=axes.verify_phases(read_lines(out/'physical.jsonl'),samples,phases)
    result['window_observation']=state.summary()
    log=(work/'user/log/shad_log.txt').read_text(encoding='utf-8')
    import re
    counts=list(map(int,re.findall(r'(\d+) controllers are currently connected',log)))
    if not counts or any(n!=1 for n in counts) or not re.search(r'Gamepad registered for slot 0! Handle: \d+',log):
        raise ValueError('Sole controller selection for engine slot zero was not verified')
    result.update(engine_controller_counts=counts,normal_exit_verified=True)


if __name__=='__main__':main()
