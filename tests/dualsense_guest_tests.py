# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later

"""Opt-in, human-assisted physical USB DualSense; no input/close injection.

The operator appends one {index, instruction, monotonic} command only after
asking the human to act. These commands are test expectations, never guest
inputs. Only physical controls change guest state; the human presses F12 for
readbacks and closes the game window. No phase file is supplied to the guest.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
import dualsense_evidence as physical
import live_av_evidence as evidence
import run_homebrew_startup as startup
import videoout_capture as windows
from live_status import read_status
from muted_endpoint import MutedEndpoint, validate_report
from owned_window_trace import OwnedWindowTrace


def records(path):
    if not path.exists(): return []
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines(keepends=True)
            if line.endswith('\n')]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('engine', 'engine-report', 'fixture', 'supervisor', 'sdl-observer', 'muted-endpoint-observer', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--disconnect-authorized', action='store_true',
                        help='Separate session only after explicit human permission; no reconnect')
    parser.add_argument('--controls', choices=('cross','buttons'), default='cross',
                        help='Explicit scope; Cross requires both cycles, all-buttons adds Circle/D-pad')
    parser.add_argument('--guided',action='store_true',help='Local human instruction panel; Cross-only normal session')
    args = parser.parse_args()
    if args.guided and args.controls!='cross':
        parser.error('The local guide is Cross-only; disconnect needs the separately authorized flag')
    for key, value in vars(args).items():
        if isinstance(value, Path): setattr(args, key, value.resolve())
    args.output.mkdir(parents=True, exist_ok=False)
    context = dict(inputs={key: dict(path=str(getattr(args,key)),sha256=startup.digest(getattr(args,key)))
                           for key in ('engine','engine_report','fixture','supervisor','sdl_observer','muted_endpoint_observer')},
                   source_lf_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes().replace(b'\r\n',b'\n')).hexdigest()
                       for p in (Path(__file__),ROOT/'tools/dualsense_evidence.py',ROOT/'tests/dualsense_sdl_probe.cpp',
                                 ROOT/'tests/dualsense_guide.py')},
                   controls=args.controls,guided=args.guided,disconnect_authorized=args.disconnect_authorized,keyboard_injection_performed=False)
    (args.output/'collection-context.json').write_bytes((json.dumps(context,indent=2)+'\n').encode())
    guide = None
    try:
        if args.guided:
            from dualsense_guide import Guide
            plan = physical.selected_plan(args.controls)
            guide = Guide(args.output,plan[:1] if args.disconnect_authorized else plan,args.disconnect_authorized)
            guide.wait_ready()  # No SDL observer, audio or guest is active yet.
        with MutedEndpoint(args.muted_endpoint_observer, args.output) as endpoint:
            result = session(args, endpoint, guide)
        result['endpoint_observation'] = validate_report(args.output/'endpoint.jsonl')
        result['status'] = 'passed'
    except BaseException as error:
        result = dict(status='failed', error=str(error), automatic_retry_performed=False)
        path = args.output/'guest/session-result.json'
        if path.exists(): result['guest_result'] = json.loads(path.read_text(encoding='utf-8'))
        (args.output/'result.json').write_bytes((json.dumps(result, indent=2)+'\n').encode())
        raise
    finally:
        if guide: guide.close()
    (args.output/'result.json').write_bytes((json.dumps(result, indent=2)+'\n').encode())
    print(json.dumps(dict(status='passed', disconnect=args.disconnect_authorized)))


def session(args, endpoint, guide=None):
    out = args.output
    guest = out/'guest'
    commands = out/'human-commands.jsonl'
    observer = child = None
    state = None
    captures, seen, samples_seen = [], set(), set()
    completed = 0
    closing = False
    began = time.monotonic()
    def emit(event, **fields):
        with (out/'host-trace.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(dict(event=event, monotonic=time.monotonic(), **fields))+'\n')
    def progress(**fields):
        physical.append_progress(out/'progress.jsonl', dict(completed=completed, **fields))
    command_count = 0
    plan = physical.selected_plan(args.controls)
    capture_announced = None
    disconnected_at = None
    disconnect_observation_seconds = 0
    with (out/'sdl-stdout.json').open('wb') as sdl_out, (out/'sdl-stderr.txt').open('wb') as sdl_err, (out/'guest-console.txt').open('wb') as console:
        try:
            observer = subprocess.Popen([str(args.sdl_observer), '--watch', str(out/'physical.jsonl'),
                str(out/'physical-stop.request'), str(out/'physical-ready.txt'), '570000'], stdout=sdl_out, stderr=sdl_err,
                **startup.background_process_options())
            deadline = time.monotonic()+10
            while not (out/'physical-ready.txt').exists():
                endpoint.check()
                if observer.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError('Physical SDL observer failed before guest launch')
                time.sleep(.02)
            physical_records = records(out/'physical.jsonl')
            if not physical_records or physical_records[0]['connection'] != 'wired':
                raise RuntimeError('Wired hardware identity not verified')
            command = [sys.executable, str(ROOT/'tools/run_live_session.py')]
            for key in ('engine', 'engine_report', 'fixture', 'supervisor'):
                command += ['--'+key.replace('_','-'), str(getattr(args, key))]
            child = subprocess.Popen([*command, '--output', str(guest)], stdout=console, stderr=subprocess.STDOUT,
                                     **startup.background_process_options())
            progress(state='starting_guest')
            if guide: guide.issue(0,commands)
            while child.poll() is None:
                if guide: guide.pump()
                endpoint.check()
                if observer.poll() is not None: raise RuntimeError('Physical observer stopped; no automatic retry')
                if time.monotonic()-began > 540: raise RuntimeError('Human-assisted session exceeded 540-second budget')
                physical_records = records(out/'physical.jsonl')
                states = [r for r in physical_records if r['event']=='state']
                disconnected = any(r['event']=='removed' for r in physical_records) or bool(states and not states[-1]['connected'])
                instructions = records(commands)
                if len(instructions) > command_count:
                    if len(instructions) != command_count+1 or instructions[-1]['index'] != command_count:
                        raise RuntimeError('Human phases must be explicit and consecutive')
                    command_count += 1
                    capture_announced = None
                    physical.record_instruction(out/'host-trace.jsonl', instructions[-1])
                    progress(state='awaiting_physical_action', stage=instructions[-1]['index'])
                if disconnected and not (args.disconnect_authorized and command_count==2 and completed==1):
                    raise RuntimeError('Unauthorized or premature controller disconnect')
                if disconnected and disconnected_at is None:
                    disconnected_at = time.monotonic()
                    progress(state='physical_disconnect_observed')
                try: status = read_status(guest/'session-status.json')
                except (OSError, ValueError): time.sleep(.025); continue
                if not status['running_observed']: time.sleep(.025); continue
                if state is None:
                    state = OwnedWindowTrace(windows._owned_window(status['supervisor_pid'], args.engine), emit)
                    progress(state='ready_for_human_neutral_capture')
                if not closing and not disconnected: state.poll()
                for sample in status['samples']:
                    if sample['sequence'] not in samples_seen:
                        emit('guest_observation', sample=sample)
                        samples_seen.add(sample['sequence'])
                if closing: time.sleep(.025); continue
                if args.disconnect_authorized and completed==1:
                    if command_count==2:
                        if instructions[-1].get('action')!='disconnect': raise RuntimeError('Explicit disconnect command required')
                        if disconnected_at is not None:
                            disconnect_observation_seconds = time.monotonic()-disconnected_at
                            if disconnect_observation_seconds >= 5:
                                closing = True
                                progress(state='ready_for_human_close_after_disconnect')
                                if guide: guide.close_after_disconnect()
                    time.sleep(.025); continue
                if not instructions: time.sleep(.025); continue
                index = instructions[-1]['index']
                if index >= len(plan) or index > completed: raise RuntimeError('Unexpected human phase')
                if args.disconnect_authorized and index != 0: raise RuntimeError('Disconnect session only qualifies initial neutral')
                sample = status['samples'][-1]
                if sample['sequence'] > index: raise RuntimeError('Unexpected extra guest action; retain failed attempt')
                if sample['sequence'] < index: time.sleep(.025); continue
                expected, sdl_expected = plan[index][1:]
                if sample['buttons'] != expected: raise RuntimeError('Wrong physical button reached guest')
                if not states or states[-1]['buttons'] != sdl_expected: time.sleep(.025); continue
                opened = next(r for r in physical_records if r['event']=='opened')
                # SDL's QPC and Python perf_counter share a clock; monotonic() on
                # this Python may use a different Windows clock. Never mix them.
                held = time.perf_counter() - states[-1]['qpc']/opened['qpc_frequency']
                if completed == index and capture_announced != index and held >= 3:
                    capture_announced = index
                    progress(state='ready_for_human_f12',stage=index,label=plan[index][0],stable_sdl_seconds=held)
                    if guide: guide.capture(index)
                if capture_announced != index and completed == index: time.sleep(.025); continue
                if completed == index:
                    for path in sorted(set((guest/'session/user/screenshots').glob('*.png'))-seen):
                        seen.add(path)
                        try:
                            checked = evidence.verify_image(path, (guest/'session/app/palette.bin').read_bytes(), index, expected)
                        except ValueError as error:
                            emit('unqualified_human_readback', path=str(path.relative_to(out)), error=str(error))
                            continue
                        captures.append(dict(**checked, path=str(path.relative_to(out))))
                        emit('image_verified', sequence=index, path=str(path.relative_to(out)))
                        completed += 1
                        progress(state='phase_verified', stage=index, label=plan[index][0])
                        if guide and args.disconnect_authorized: guide.disconnect(commands)
                        elif guide and completed < len(plan): guide.issue(completed,commands)
                        break
                if not args.disconnect_authorized and completed == len(plan):
                    closing = True
                    progress(state='ready_for_human_window_close')
                    if guide: guide.finish()
                time.sleep(.025)
            code = child.wait(timeout=5)
        finally:
            if child is not None and child.poll() is None:
                cleanup_deadline = time.monotonic()+8
                while child.poll() is None and time.monotonic()<cleanup_deadline:
                    # Startup may not have created its work directory when the
                    # test fails. Request stop as soon as that owned path exists.
                    if (guest/'session').exists(): (guest/'session/stop.request').touch(exist_ok=True)
                    time.sleep(.025)
                if child.poll() is None: child.kill(); child.wait(timeout=5)
            if observer is not None:
                (out/'physical-stop.request').touch(exist_ok=True)
                try: observer.wait(timeout=5)
                except subprocess.TimeoutExpired: observer.kill(); observer.wait(timeout=5)
    result = json.loads((guest/'session-result.json').read_text(encoding='utf-8'))
    transport = result['transport']
    if not transport['tree_cleanup'] or not transport['root_exit_verified']:
        raise RuntimeError('Owned engine cleanup not verified')
    physical_records = records(out/'physical.jsonl')
    if args.disconnect_authorized:
        classified = physical.classify_disconnect(physical_records,result,code,
            authorized=command_count==2,neutral_qualified=completed==1,observation_seconds=disconnect_observation_seconds)
        return dict(disconnect_test_authorized=True, reconnect_attempted=False, guest_result=result,
                    disconnect_observation=classified,
                    captures=captures, keyboard_injection_performed=False)
    if code or result['status'] != 'closed' or not result['normal_exit_verified'] or result['audit']['unresolved']:
        raise RuntimeError('Physical guest did not close normally')
    if observer.returncode or len(captures) != len(plan): raise RuntimeError('Incomplete physical observer/images')
    raw = (guest/'session/user/data/live-input.bin').read_bytes()
    verified = physical.verify_physical(physical_records, result['samples'], raw, captures, controls=args.controls)
    verified['guest_input'] = evidence.verify_input(guest/'session/user/data/live-input.bin', result['samples'], captures)
    log = (guest/'session/user/log/shad_log.txt').read_text(encoding='utf-8')
    counts = list(map(int, re.findall(r'(\d+) controllers are currently connected', log)))
    if not counts or any(n!=1 for n in counts) or not re.search(r'Gamepad registered for slot 0! Handle: \d+', log):
        raise RuntimeError('Engine did not select the sole recognized controller for guest slot zero')
    if list(out.rglob('*.raw')): raise RuntimeError('Physical input test unexpectedly captured PCM')
    return dict(physical_verification=verified, guest_result=result, captures=captures,
                window_observation=state.summary(), engine_controller_counts=counts,
                no_engine_or_fixture_modification=True, hardware_acoustic_output_tested=False,
                automated_gameplay_or_diagnostic_key_events_sent=False)


if __name__=='__main__': main()
