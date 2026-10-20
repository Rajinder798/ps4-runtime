# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
"""Opt-in human-assisted ONE USB cycle. Requires separate owner permissions.

Not part of host CI. No keyboard/controller injection or system-setting changes.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import time

ROOT=Path('C:\\gow3 repo\\ps4-runtime')
sys.path.insert(0,str(ROOT/'tests'))
sys.path.insert(0,str(ROOT/'tools'))
import pad_hotplug_evidence as hp
import run_homebrew_startup as startup
import videoout_capture as windows
from dualsense_evidence import append_progress,readback_ready
from confirmed_guide import ConfirmedGuide as Guide,reconnect_expired
from hotplug_endpoint import MutedEndpoint,validate_report
from owned_window_trace import OwnedWindowTrace


def read_lines(path,*,final=False):
    if not path.exists(): return []
    if path.stat().st_size>startup.MAX_AUDIT_BYTES: raise ValueError('Native evidence exceeds fixed audit budget')
    lines=path.read_text(encoding='utf-8').splitlines(keepends=True)
    if final and lines and not lines[-1].endswith('\n'): raise ValueError('Truncated final native evidence')
    return [json.loads(line) for line in lines if line.endswith('\n')]


def instruction(index,capture=False):
    title,text=(
        ('CONTROLLER NEUTRAL','Click inside the new game window. Leave every control untouched.'),
        ('HOLD CROSS','Hold only Cross. Leave sticks and triggers untouched.'),
        ('UNPLUG USB NOW','The held image is verified. Physically unplug USB ONCE. Then release Cross on the disconnected controller. Do not reconnect yet.'),
        ('LEAVE USB DISCONNECTED','Leave USB disconnected and controls released. Wait for the second progress capture.'),
        ('RECONNECT SAME USB NOW','Reconnect the SAME DualSense directly by USB-C ONCE. Leave every control untouched. Do not press PS.'),
        ('HOLD CROSS','Press and hold only Cross on the reconnected DualSense.'),
        ('RELEASE CROSS','Release Cross completely. Leave every control untouched.')
    )[index]
    if capture:
        title='F12 NOW — '+title
        text='Keep the current connection/control state. Physically press laptop F12 (Fn if needed), then wait for the panel to advance. Keep Cross HELD in a hold stage.'
    else: text+=' Wait for F12 NOW before any screenshot.'
    return f'{index+1}/7 — '+title,text+' Keep Windows muted. Use F12, not F11. Do not change audio/controller settings.'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('engine','engine-report','fixture','supervisor','sdl-observer','muted-endpoint-observer','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--disconnect-authorized',action='store_true')
    parser.add_argument('--reconnect-authorized',action='store_true')
    args=parser.parse_args()
    if not args.disconnect_authorized or not args.reconnect_authorized:
        parser.error('Requires separate explicit owner authorization for disconnect AND reconnect; no session started')
    if sys.platform!='win32': parser.error('Human hardware workflow requires Windows')
    for key,value in vars(args).items():
        if isinstance(value,Path): setattr(args,key,value.resolve())
    args.output.mkdir(parents=True,exist_ok=False)
    out=args.output;result=dict(profile='pad-hotplug-av',status='failed',guest_completed=False,
        keyboard_injection_performed=False,automated_window_close_sent=False,hardware_acoustic_output_tested=False,
        disconnect_authorized=True,reconnect_authorized=True,automatic_retry_performed=False)
    guide=None
    try:
        result['build']=startup.verify_inputs(args.engine,args.engine_report,args.fixture,'pad-hotplug-av')
        metadata=json.loads((args.sdl_observer.parent/'build.json').read_text())
        source=ROOT/'tests/dualsense_sdl_probe.cpp'
        library=args.engine.parent/'externals/sdl3/SDL3-static.lib'
        if (metadata['source_lf_sha256']!=hashlib.sha256(source.read_bytes().replace(b'\r\n',b'\n')).hexdigest() or
                metadata['probe_sha256']!=startup.digest(args.sdl_observer) or
                metadata['engine_sha256']!=startup.digest(args.engine) or
                metadata['sdl_static_library_sha256']!=startup.digest(library)):
            raise ValueError('SDL observer source/build/engine/library identity mismatch')
        inputs={k:dict(path=str(getattr(args,k)),sha256=startup.digest(getattr(args,k))) for k in
                ('engine','engine_report','fixture','supervisor','sdl_observer','muted_endpoint_observer')}
        sources=[Path(__file__),ROOT/'tools/pad_hotplug_evidence.py',source,ROOT/'research/homebrew/pad_hotplug_av/main.cpp',
                 ROOT/'tests/owned_window_trace.py',ROOT/'tests/window_identity_diagnostics.py',ROOT/'tests/dualsense_guide.py']
        hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes().replace(b'\r\n',b'\n')).hexdigest() for p in sources}
        for p in sources:
            target=out/'test-source-snapshot'/p.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(p,target)
        (out/'collection-context.json').write_bytes((json.dumps(dict(inputs=inputs,source_lf_sha256=hashes,
            disconnect_authorized=True,reconnect_authorized=True,keyboard_injection_performed=False),indent=2)+'\n').encode())
        guide=Guide(out,hp.PLAN)
        guide.show('One separately approved USB cycle','Keep Windows muted. Click Ready only when prepared for seven captures, one unplug and one reconnect of this same controller. Follow each prompt; no physical action is automated.')
        guide.wait_ready()
        with MutedEndpoint(args.muted_endpoint_observer,out) as endpoint:
            run(args,result,guide,endpoint)
            guide.wait_close_confirmation(endpoint)
        result['endpoint_observation']=validate_report(out/'endpoint.jsonl')
        result['status']='passed'
    except BaseException as error:
        result['error']=str(error)
        raise
    finally:
        try:
            if (out/'session').exists(): startup.collect_failure_evidence(out,result)
        finally:
            (out/'result.json').write_bytes((json.dumps(result,indent=2)+'\n').encode())
            if guide: guide.close()
    print(json.dumps(dict(status=result['status'],qualified_phases=len(result['phases']))))


def run(args,result,guide,endpoint):
    out=args.output;work=out/'session';startup.prepare_session(work)
    (work/'user/config.json').write_text(json.dumps(dict(Log=dict(filter='*:info',flush_level='trace'))))
    app=work/'app';app.mkdir();staged=app/'pad_hotplug_av.oelf';shutil.copyfile(args.fixture,staged)
    if startup.digest(staged)!=startup.digest(args.fixture): raise ValueError('Staged fixture differs')
    palette=bytes(secrets.SystemRandom().sample(range(8),4))
    (app/'palette.bin').write_bytes(palette)
    (app/'audio.bin').write_bytes(bytes(secrets.SystemRandom().sample(range(4),4)))
    result['palette']=list(palette)
    owner=[];observer=None;state=None;phases=[];latest=[];phase=None
    pending={};seen=set();capture_announced=closing=failed=False;begun=time.monotonic();reconnected=False
    trace=work/'startup-audit.jsonl'
    def emit(event,**fields):
        with (out/'host-trace.jsonl').open('a',encoding='utf-8') as stream:
            stream.write(json.dumps(dict(event=event,monotonic=time.monotonic(),**fields))+'\n')
    def issue(index):
        nonlocal phase,capture_announced
        phase=dict(index=index,label=hp.PLAN[index][0],instruction_qpc_seconds=time.perf_counter(),
            guest_after_observed_us=latest[-1]['observed_us'] if latest else 0,issued_monotonic=time.monotonic())
        capture_announced=False
        emit('human_instruction',instruction=instruction(index)[1],**phase)
        append_progress(out/'progress.jsonl',dict(state='awaiting_physical_action',**phase))
        guide.show(*instruction(index))
    def poll():
        nonlocal state,latest,capture_announced,closing,failed,reconnected
        if failed: return True  # Preserve first failure and request cleanup; never advance/retry.
        try:
            guide.pump();endpoint.check()
            if observer.poll() is not None: raise ValueError('Native observer stopped; preserve stderr, no retry')
            if time.monotonic()-begun>360: raise ValueError('Approved 360-second human test budget exceeded')
            native=read_lines(out/'native.jsonl')
            current=hp.progress(startup.read_events(trace));latest=current['samples']
            if not current['running_observed']:
                if time.monotonic()-begun>30: raise ValueError('Guest startup readiness exceeded 30 seconds')
                return False
            if latest[0]['state']!=hp.CONNECTED: raise ValueError('Initial guest controller was not connected; no retry')
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
                    except (OSError,ValueError) as error: diagnostic['discovery_error']=str(error)
                    emit('window_identity_failure_postmortem',**diagnostic)
                    raise
            if closing: return False
            removed=[r for r in native if r['event']=='hotplug_removed']
            opened=[r for r in native if r['event']=='hotplug_opened']
            if removed and guide.unplug_instruction_monotonic is None: raise ValueError('USB removed before separately confirmed instruction')
            if len(opened)>1 and guide.reconnect_instruction_monotonic is None: raise ValueError('USB reconnected before separately confirmed instruction')
            if removed and phase['index']<2: raise ValueError('Removal before human unplug instruction')
            if len(opened)>1 and phase['index']<4: raise ValueError('Reconnect before human reconnect instruction')
            if any(s['state']==hp.CONNECTED and (s['raw_buttons'] not in (0,hp.CROSS) or s['raw_triggers']!=[0,0]) for s in latest):
                raise ValueError('Unexpected guest control outside Cross-only plan')
            if phase['index']==4:
                reconnected=reconnected or (len(opened)==2 and latest[-1]['state']==hp.CONNECTED)
                if not reconnected and reconnect_expired(guide.reconnect_instruction_monotonic,time.monotonic()):
                    raise ValueError('Reconnect not observed within 30 seconds; no retry/reopen')
            frequency=opened[0]['qpc_frequency']
            rows=[r for r in native if r['event']=='hotplug_state']
            sdl,seconds=hp.stable_suffix(rows,phase['index'],native=True,after=phase['instruction_qpc_seconds'],frequency=frequency)
            guest,duration=hp.stable_suffix(latest,phase['index'],after=phase['guest_after_observed_us']/1e6)
            spacing_ok=phase['index']!=3 or latest[-1]['observed_us']-latest[phases[2]['sequence']]['observed_us']>=5000000
            if guide.action_confirmed and not capture_announced and spacing_ok and min(seconds,duration)>=3 and min(len(sdl),len(guest))>=20:
                capture_announced=True;guide.show(*instruction(phase['index'],True))
                append_progress(out/'progress.jsonl',dict(state='ready_for_human_f12',**phase))
            for path in sorted(set((work/'user/screenshots').glob('*.png'))-seen):
                if not readback_ready(path,pending): continue
                if not capture_announced: raise ValueError('Screenshot before phase qualification')
                if not guide.capture_confirmed: continue
                seq=hp.image_sequence(path)
                if seq>=len(latest): continue  # Completed flip may precede its original audit line.
                sample=latest[seq];image=hp.verify_image(path,palette,sample)
                _,held=hp.stable_suffix(latest[:seq+1],phase['index'],after=phase['guest_after_observed_us']/1e6)
                if held<3 or seconds<3 or not hp.matches(sample,phase['index']): raise ValueError('Wrong/short-held guest capture')
                if phase['index']==3 and sample['observed_us']-latest[phases[2]['sequence']]['observed_us']<5000000:
                    raise ValueError('Second disconnected image lacks five-second progression')
                phases.append(dict(**phase,**image,capture_qpc_seconds=time.perf_counter(),path=str(path.relative_to(out))))
                seen.add(path);emit('image_verified',**phases[-1])
                append_progress(out/'progress.jsonl',dict(state='phase_verified',completed=len(phases)))
                if len(phases)==7: closing=True;guide.finish()
                else: issue(len(phases))
            return False
        except BaseException as error:
            failed=True;emit('test_failure',error=str(error))
            if isinstance(error,(KeyboardInterrupt,SystemExit)): raise
            raise ValueError(str(error)) from error
    try:
        with (out/'native-stdout.json').open('wb') as so,(out/'native-stderr.txt').open('wb') as se:
            observer=subprocess.Popen([str(args.sdl_observer),'--watch-hotplug',str(out/'native.jsonl'),
                str(out/'native-stop.request'),str(out/'native-ready.txt'),'390000','--disconnect-authorized','--reconnect-authorized'],
                stdout=so,stderr=se,**startup.background_process_options())
            deadline=time.monotonic()+10
            while not (out/'native-ready.txt').exists():
                guide.pump();endpoint.check()
                if observer.poll() is not None or time.monotonic()>deadline: raise ValueError('Native wired observer did not become ready')
                time.sleep(.025)
            command=[args.engine,'--game',staged,'--ignore-game-patch','--startup-audit',trace]
            result['command']=list(map(str,command))
            result['transport']=startup.supervise(args.supervisor,command,work,None,poll,on_started=owner.append)
    finally:
        result['phases']=phases;primary=sys.exc_info()[1];errors=[]
        try:
            if state:
                result['window_observation']=state.summary()
                try: state.diagnostics.snapshot('supervision_finished')
                except (OSError,RuntimeError) as e: errors.append(str(e))
                try: state.close()
                except (OSError,RuntimeError) as e: errors.append(str(e))
        finally:
            if observer:
                (out/'native-stop.request').touch(exist_ok=True)
                try: observer.wait(timeout=5)
                except subprocess.TimeoutExpired: observer.kill();observer.wait(timeout=5);raise RuntimeError('Native observer needed termination')
            if errors:
                result['window_diagnostic_cleanup_errors']=errors
                emit('window_diagnostic_cleanup_failure',errors=errors)
                if primary is None and sys.exc_info()[1] is None: raise ValueError('Window diagnostic cleanup failed')
    transport=result['transport']
    if (transport['reason']!='exited' or transport['exit_code']!=0 or transport['forced_termination'] or
            transport['active_before_cleanup']!=0 or not transport['tree_cleanup'] or not transport['root_exit_verified'] or
            transport.get('owner_watch_verified') is not True or observer.returncode):
        raise ValueError('Normal user close/empty process tree not verified')
    samples=hp.progress(startup.read_events(trace,final=True))['samples'];result['samples']=samples
    result['guest_records']=hp.verify_records((work/'user/data/pad-hotplug.bin').read_bytes(),samples)
    result['evidence_requirements']=hp.verify_phases(read_lines(out/'native.jsonl',final=True),samples,phases,
                                                    disconnect_authorized=True,reconnect_authorized=True)
    log=(work/'user/log/shad_log.txt').read_text(encoding='utf-8')
    counts=list(map(int,re.findall(r'(\d+) controllers are currently connected',log)))
    slots=list(map(int,re.findall(r'Gamepad registered for slot (\d+)! Handle: \d+',log)))
    if not counts or set(counts)!={0,1} or len(slots)<2 or any(slot!=0 for slot in slots):
        raise ValueError('Sole engine controller removal/re-registration in slot zero not verified')
    result.update(engine_controller_counts=counts,engine_slots=slots,normal_exit_verified=True)


if __name__=='__main__': main()
