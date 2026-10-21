# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
"""Opt-in physical disconnected-close session. NOT a host CI or implementation test.

Requires new explicit physical-test, unplug and endpoint-protocol permission.
No input injection, automatic close, reconnect, retry or system settings changes.
"""
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
sys.path[:0] = [str(ROOT/'tools'), str(ROOT/'tests')]
import pad_hotplug_evidence as hp
import pad_disconnected_close_evidence as dc
import run_homebrew_startup as startup
import videoout_capture as windows
from pad_hotplug_guest_tests import read_lines
from dualsense_evidence import readback_ready
from hotplug_endpoint import MutedEndpoint, validate_report
from owned_window_trace import OwnedWindowTrace
from pad_disconnected_close_guide import CloseGuide


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('engine', 'engine-report', 'fixture', 'supervisor', 'sdl-observer', 'muted-endpoint-observer', 'output'):
        parser.add_argument('--'+key, type=Path, required=True)
    for key in ('physical-test-authorized', 'disconnect-authorized', 'hotplug-endpoint-protocol-authorized'):
        parser.add_argument('--'+key, action='store_true')
    args = parser.parse_args()
    if not (args.physical_test_authorized and args.disconnect_authorized and args.hotplug_endpoint_protocol_authorized):
        parser.error('New explicit physical-test, disconnect and hotplug endpoint protocol authorization required; no session started')
    if sys.platform != 'win32': parser.error('Physical session requires Windows')
    for key, value in vars(args).items():
        if isinstance(value, Path): setattr(args, key, value.resolve())
    args.output.mkdir(parents=True, exist_ok=False)
    out = args.output; guide = None
    result = dict(profile='pad-hotplug-av', scenario='disconnected-close', status='failed',
                  guest_completed=False, physical_test_authorized=True, disconnect_authorized=True,
                  reconnect_authorized=False, keyboard_injection_performed=False,
                  automated_window_close_sent=False, automatic_retry_performed=False,
                  hardware_acoustic_output_tested=False, pcm_correctness_tested=False)
    try:
        result['build'] = startup.verify_inputs(args.engine, args.engine_report, args.fixture, 'pad-hotplug-av')
        metadata = json.loads((args.sdl_observer.parent/'build.json').read_text())
        source = ROOT/'tests/dualsense_sdl_probe.cpp'
        library = args.engine.parent/'externals/sdl3/SDL3-static.lib'
        if (metadata['source_lf_sha256'] != hashlib.sha256(source.read_bytes().replace(b'\r\n', b'\n')).hexdigest() or
                metadata['probe_sha256'] != startup.digest(args.sdl_observer) or
                metadata['engine_sha256'] != startup.digest(args.engine) or
                metadata['sdl_static_library_sha256'] != startup.digest(library)):
            raise ValueError('SDL observer source/build/engine/library identity mismatch')
        inputs = {k: dict(path=str(getattr(args, k)), sha256=startup.digest(getattr(args, k))) for k in
                  ('engine', 'engine_report', 'fixture', 'supervisor', 'sdl_observer', 'muted_endpoint_observer')}
        sources = [Path(__file__), ROOT/'tools/pad_disconnected_close_evidence.py',
                   ROOT/'tests/pad_disconnected_close_guide.py', source,
                   ROOT/'research/homebrew/pad_hotplug_av/main.cpp', ROOT/'tools/pad_hotplug_evidence.py',
                   ROOT/'tests/owned_window_trace.py', ROOT/'tests/window_identity_diagnostics.py',
                   ROOT/'tests/dualsense_guide.py', ROOT/'tests/hotplug_endpoint.py',
                   ROOT/'tests/hotplug_endpoint_observer.cpp', ROOT/'tests/muted_endpoint.py',
                   ROOT/'tests/pad_hotplug_guest_tests.py', ROOT/'tools/run_homebrew_startup.py',
                   ROOT/'tools/videoout_capture.py', ROOT/'tools/videoout_evidence.py',
                   ROOT/'tools/dualsense_evidence.py']
        hashes = {}
        for path in sources:
            target = out/'test-source-snapshot'/path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(path, target)
            hashes[path.relative_to(ROOT).as_posix()] = startup.digest(path)
        (out/'collection-context.json').write_text(json.dumps(dict(inputs=inputs, source_sha256=hashes,
                    scenario='disconnected-close', reconnect_authorized=False), indent=2)+'\n', encoding='utf-8')
        guide = CloseGuide(out, dc.PLAN)
        guide.wait_ready()
        with MutedEndpoint(args.muted_endpoint_observer, out) as endpoint:
            run(args, result, guide, endpoint)
        result['endpoint_observation'] = validate_report(out/'endpoint.jsonl')
        result['status'] = 'passed'
    except BaseException as error:
        result['error'] = str(error)
        raise
    finally:
        try:
            if (out/'session').exists(): startup.collect_failure_evidence(out, result)
        finally:
            (out/'result.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
            if guide: guide.close()
    print(json.dumps(dict(status=result['status'], qualified_phases=len(result['phases']))))


def run(args, result, guide, endpoint):
    out = args.output; work = out/'session'; startup.prepare_session(work)
    (work/'user/config.json').write_text(json.dumps(dict(Log=dict(filter='*:info', flush_level='trace'))))
    app = work/'app'; app.mkdir(); staged = app/'pad_hotplug_av.oelf'; shutil.copyfile(args.fixture, staged)
    if startup.digest(staged) != startup.digest(args.fixture): raise ValueError('Staged fixture differs')
    palette = bytes(secrets.SystemRandom().sample(range(8), 4))
    (app/'palette.bin').write_bytes(palette)
    (app/'audio.bin').write_bytes(bytes(secrets.SystemRandom().sample(range(4), 4)))
    result['palette'] = list(palette)
    trace = work/'startup-audit.jsonl'
    owner = []; observer = state = phase = None
    phases = []; latest = []; seen = set(); pending = {}
    announced = failed = False
    close = dict(root_exit_before_instruction=False, ownership_failed=False)
    last_seen_qpc = None; last_sequence = -1; last_owned_qpc = None

    def emit(event, **fields):
        with (out/'host-trace.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(dict(event=event, host_qpc_seconds=time.perf_counter(), **fields))+'\n')

    def root_exited():
        wait = state.diagnostics.kernel.WaitForSingleObject(state.diagnostics.process, 0)
        if wait not in (0, 258): raise ValueError('Retained root process wait failed')
        return wait == 0

    def budget():
        guide.pump(); endpoint.check()
        if time.perf_counter()-guide.started_qpc > dc.TOTAL_SECONDS:
            raise ValueError('Six-minute test budget expired; no retry')
        if observer is not None and observer.poll() is not None:
            raise ValueError('SDL observer stopped; preserve its stderr, no retry')

    def update_guest(*, final=False):
        nonlocal latest, last_seen_qpc, last_sequence
        current = hp.progress(startup.read_events(trace, final=final))
        latest = current['samples']
        if latest and latest[-1]['sequence'] != last_sequence:
            last_sequence = latest[-1]['sequence']; last_seen_qpc = time.perf_counter()
        if latest:
            transitions = [s['state'] for i, s in enumerate(latest) if not i or s['state'] != latest[i-1]['state']]
            if transitions not in ([hp.CONNECTED], [hp.CONNECTED, hp.DISCONNECTED]):
                raise ValueError('Guest failure, unexpected initial absence or reconnection')
            if any(s['state'] == hp.CONNECTED and not dc.matches(s, 0) for s in latest):
                raise ValueError('Unrequested controller input')
        return current['running_observed']

    def owned_poll():
        nonlocal last_owned_qpc
        if root_exited():
            close['root_exit_before_instruction'] = True
            raise ValueError('Root exited before the human close instruction')
        try: state.poll()
        except (OSError, RuntimeError):
            close['ownership_failed'] = True
            raise
        last_owned_qpc = time.perf_counter()

    def before_close():
        # Runs inside a Tk callback: do not recursively pump its message loop.
        endpoint.check(); update_guest(); owned_poll()
        if not latest or latest[-1]['state'] != hp.DISCONNECTED or time.perf_counter()-last_seen_qpc > .35:
            raise ValueError('Fresh disconnected guest not established before close instruction')
        close.update(last_owned_qpc_seconds=last_owned_qpc, root_pid=state.pid, bound_window=state.window)

    def issue(index):
        nonlocal phase, announced
        announced = False
        phase = dict(index=index, label=dc.PLAN[index][0], guest_after_observed_us=latest[-1]['observed_us'])
        guide.stage(index)

    def poll():
        nonlocal state, announced, failed
        if failed: return True
        try:
            budget(); running = update_guest()
            native = read_lines(out/'native.jsonl')
            opened = [r for r in native if r['event'] == 'hotplug_opened']
            removed = [r for r in native if r['event'] == 'hotplug_removed']
            if len(opened) > 1 or len(removed) > 1: raise ValueError('Extra USB device/cycle forbidden')
            if removed and (guide.unplug_instruction_qpc is None or
                            removed[0]['qpc']/opened[0]['qpc_frequency'] <= guide.unplug_instruction_qpc):
                raise ValueError('Removal before explicit human instruction')
            if not running:
                if time.perf_counter()-guide.started_qpc > 30: raise ValueError('Startup exceeded 30 seconds')
                return False
            if state is None:
                state = OwnedWindowTrace(windows._owned_window(owner[0], args.engine), emit, lifecycle=True)
                issue(0)
            if guide.close_instruction_qpc is not None:
                state.diagnostics.drain()
                close['instruction_qpc_seconds'] = guide.close_instruction_qpc
                if root_exited():
                    close.setdefault('root_exit_qpc_seconds', time.perf_counter())
                elif time.perf_counter()-guide.close_instruction_qpc > dc.CLOSE_SECONDS:
                    raise ValueError('Normal close did not exit within 30 seconds; cleanup is failure')
                return False
            owned_poll()
            if len(phases) == 3: return False  # Waiting for explicit close readiness, still owned.
            if guide.action_instruction_qpc is None: return False
            phase['instruction_qpc_seconds'] = guide.action_instruction_qpc
            index = phase['index']; frequency = opened[0]['qpc_frequency']
            rows = [r for r in native if r['event'] == 'hotplug_state']
            sdl, seconds = dc.stable_suffix(rows, index, native=True, after=phase['instruction_qpc_seconds'], frequency=frequency)
            guest, duration = dc.stable_suffix(latest, index, after=phase['guest_after_observed_us']/1e6)
            spacing = index != 2 or latest[-1]['observed_us']-latest[phases[1]['sequence']]['observed_us'] >= 5000000
            if guide.action_confirmed and not announced and spacing and min(seconds, duration) >= 3 and min(len(sdl), len(guest)) >= 20:
                announced = True; guide.capture()
            images = sorted(set((work/'user/screenshots').glob('*.png'))-seen)
            if len(images) > 1: raise ValueError('Extra screenshot; no automatic retry')
            for path in images:
                if not readback_ready(path, pending): continue
                if not announced: raise ValueError('Screenshot before qualification')
                if not guide.capture_confirmed: continue
                seq = hp.image_sequence(path)
                if seq >= len(latest): continue
                sample = latest[seq]; image = hp.verify_image(path, palette, sample)
                _, held = dc.stable_suffix(latest[:seq+1], index, after=phase['guest_after_observed_us']/1e6)
                if held < 3 or not dc.matches(sample, index): raise ValueError('Wrong/short-held capture')
                if index == 2 and sample['observed_us']-latest[phases[1]['sequence']]['observed_us'] < 5000000:
                    raise ValueError('Five guest seconds not established')
                phases.append(dict(**phase, **image, capture_qpc_seconds=time.perf_counter(), path=str(path.relative_to(out))))
                seen.add(path); emit('image_verified', **phases[-1])
                if len(phases) == 3: guide.finish(before_close)
                else: issue(len(phases))
            return False
        except BaseException as error:
            failed = True; emit('test_failure', error=str(error))
            if isinstance(error, (KeyboardInterrupt, SystemExit)): raise
            raise ValueError(str(error)) from error

    try:
        with (out/'native-stdout.json').open('wb') as so, (out/'native-stderr.txt').open('wb') as se:
            observer = subprocess.Popen([str(args.sdl_observer), '--watch-disconnect', str(out/'native.jsonl'),
                str(out/'native-stop.request'), str(out/'native-ready.txt'), '390000', '--disconnect-authorized'],
                stdout=so, stderr=se, **startup.background_process_options())
            deadline = time.perf_counter()+10
            while not (out/'native-ready.txt').exists():
                budget()
                if time.perf_counter() > deadline: raise ValueError('Native observer readiness exceeded 10 seconds')
                time.sleep(.025)
            command = [args.engine, '--game', staged, '--ignore-game-patch', '--startup-audit', trace]
            result['command'] = list(map(str, command))
            result['transport'] = startup.supervise(args.supervisor, command, work, None, poll, on_started=owner.append)
            finished = time.perf_counter()
            dc.verify_transport(result['transport'])
            if state is None or guide.close_instruction_qpc is None or not root_exited():
                raise ValueError('Process exited without the instructed owned-window close')
            close.setdefault('root_exit_qpc_seconds', finished)
            close['instruction_qpc_seconds'] = guide.close_instruction_qpc
            update_guest(final=True)
            close['supervision_finished_qpc_seconds'] = time.perf_counter()
            finished = close['supervision_finished_qpc_seconds']
            close.update(last_guest_observed_us=latest[-1]['observed_us'], last_guest_seen_qpc_seconds=last_seen_qpc)
            # Keep independent absence/mute observation running through root exit and human confirmation.
            while True:
                budget()
                rows = read_lines(out/'native.jsonl')
                states = [r for r in rows if r['event'] == 'hotplug_state']
                opened = [r for r in rows if r['event'] == 'hotplug_opened']
                if len(opened) != 1 or not states or states[-1]['connected']:
                    raise ValueError('Native absence lost before final cleanup verification')
                if guide.closed_confirmed_qpc and states[-1]['qpc']/opened[0]['qpc_frequency'] >= max(finished, guide.closed_confirmed_qpc):
                    break
                time.sleep(.025)
            close['confirmed_qpc_seconds'] = guide.closed_confirmed_qpc
    finally:
        result['phases'] = phases; result['close'] = close
        primary = sys.exc_info()[1]; errors = []
        if (work/'supervisor.json').exists() and 'transport' not in result:
            result['transport'] = json.loads((work/'supervisor.json').read_text())
        try:
            if state:
                result['window_observation'] = state.summary()
                try: state.diagnostics.snapshot('supervision_finished')
                except (OSError, RuntimeError) as error: errors.append(str(error))
                try: state.close()
                except (OSError, RuntimeError) as error: errors.append(str(error))
        finally:
            if observer:
                (out/'native-stop.request').touch(exist_ok=True)
                try: observer.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    observer.kill(); observer.wait(timeout=5); errors.append('SDL observer needed forced termination')
            if errors:
                result['diagnostic_cleanup_errors'] = errors
                if primary is None: raise ValueError('; '.join(errors))
    if observer.returncode != 0: raise ValueError('SDL observer failed; preserve stderr')
    result['samples'] = latest
    result['guest_records'] = hp.verify_records((work/'user/data/pad-hotplug.bin').read_bytes(), latest)
    dc.verify_images(out, palette, latest, phases)
    dc.verify_confirmations(read_lines(out/'human-confirmations.jsonl', final=True), phases, close)
    if set((work/'user/screenshots').glob('*.png')) != seen:
        raise ValueError('Unexpected extra screenshot retained; attempt fails')
    result['evidence_requirements'] = dc.verify(read_lines(out/'native.jsonl', final=True), latest, phases,
                            close, result['transport'], disconnect_authorized=True)
    result['engine_observation'] = dc.verify_engine((work/'user/log/shad_log.txt').read_text(encoding='utf-8'))


if __name__ == '__main__': main()
