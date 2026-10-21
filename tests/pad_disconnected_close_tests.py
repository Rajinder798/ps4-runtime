# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
"""Generated host evidence only. Never starts SDL, a guest or a controller session."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
import pad_hotplug_evidence as hp
import pad_disconnected_close_evidence as dc
from pad_disconnected_close_guide import CloseGuide
from videoout_tests import png, unfiltered


def fixture():
    native = [dict(event='hotplug_opened', qpc=100000, qpc_frequency=1000000, episode=0,
                   instance_id=11, connection='wired', vendor=1356, product=3302, real_type=6,
                   virtual=False, sole=True, sdl_timestamp_ns=0)]
    samples = []
    for tick in range(2, 161):
        us = tick*100000; connected = tick < 50
        samples.append(dict(sequence=len(samples), handle=1, rc=0, audio_command=0, observed_us=us,
            timestamp=us if connected else 0, flip=len(samples)+1, audio_blocks=tick*2, raw_buttons=0,
            effective_buttons=0, raw_axes=[128]*4 if connected else [0]*4, effective_axes=[128]*4,
            connected=int(connected), count=int(connected), raw_triggers=[0, 0], effective_triggers=[0, 0],
            payload_valid=1, state=hp.CONNECTED if connected else hp.DISCONNECTED))
        native.append(dict(event='hotplug_state', qpc=us, instance_id=11, episode=0, connected=connected,
                           input_valid=connected, buttons=0 if connected else None, axes=[0]*4 if connected else None))
    native.insert(49, dict(event='hotplug_removed', qpc=4950000, episode=0, instance_id=11, sdl_timestamp_ns=4950000000))
    native.append(dict(event='hotplug_state', qpc=16100000, instance_id=11, episode=0, connected=False,
                       input_valid=False, buttons=None, axes=None))
    native.append(dict(event='stopped', qpc=16150000))
    phases = []
    for i, (start, stop, sample_us) in enumerate(((.3, 3.6, 3500000), (4, 8.3, 8200000), (8.4, 14, 13800000))):
        phases.append(dict(index=i, label=dc.PLAN[i][0], instruction_qpc_seconds=start,
            guest_after_observed_us=int(start*1e6), capture_qpc_seconds=stop,
            sequence=sample_us//100000-2, state=dc.PLAN[i][1], pixels_verified=640*360))
    close = dict(last_owned_qpc_seconds=14.9, instruction_qpc_seconds=15,
        root_exit_qpc_seconds=16.05, supervision_finished_qpc_seconds=16.06, confirmed_qpc_seconds=16.08,
        root_pid=99, bound_window=1234, root_exit_before_instruction=False, ownership_failed=False,
        last_guest_observed_us=16000000, last_guest_seen_qpc_seconds=16)
    transport = dict(reason='exited', exit_code=0, active_before_cleanup=0, forced_termination=False,
                     tree_cleanup=True, root_exit_verified=True, owner_watch_verified=True, root_pid=99)
    return native, samples, phases, close, transport


def verify(args): return dc.verify(*args, disconnect_authorized=True)


class Value:
    def set(self, value): self.value = value
class Button:
    def configure(self, **values): self.values = values


class DisconnectedCloseTests(unittest.TestCase):
    def test_complete_generated_evidence_and_original_seven_stage_plan_remains_separate(self):
        self.assertEqual(verify(fixture())['qualified_phases'], 3)
        self.assertEqual(len(hp.PLAN), 7)
        with self.assertRaises(ValueError): hp.verify_phases(*fixture()[:3], disconnect_authorized=True, reconnect_authorized=True)

    def test_authorization_is_required_and_cli_cannot_start_output_or_ui_without_it(self):
        with self.assertRaises(ValueError): dc.verify(*fixture())
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)/'must-not-exist'
            base = [sys.executable, str(ROOT/'tests/pad_disconnected_close_guest_tests.py')]
            for key in ('engine', 'engine-report', 'fixture', 'supervisor', 'sdl-observer', 'muted-endpoint-observer'):
                base += ['--'+key, 'missing']
            base += ['--output', str(output)]
            flags = ['--physical-test-authorized', '--disconnect-authorized', '--hotplug-endpoint-protocol-authorized']
            for missing in flags:
                result = subprocess.run(base+[f for f in flags if f != missing], capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0); self.assertIn('no session started', result.stderr)
                self.assertFalse(output.exists())
            result = subprocess.run(base+flags+['--reconnect-authorized'], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0); self.assertFalse(output.exists())

    def test_removal_repeated_added_wrong_device_and_native_invalid_payload_rejected(self):
        for mutation in ('removed', 'added', 'wireless', 'virtual', 'wrong-id', 'fabricated-neutral', 'gap', 'press'):
            with self.subTest(mutation=mutation):
                data = copy.deepcopy(fixture()); rows = data[0]
                if mutation == 'removed': rows.insert(-1, dict(event='hotplug_removed', qpc=16050000))
                elif mutation == 'added': rows.insert(-1, copy.deepcopy(rows[0]))
                elif mutation == 'wireless': rows[0]['connection'] = 'wireless'
                elif mutation == 'virtual': rows[0]['virtual'] = True
                elif mutation == 'wrong-id': rows[1]['instance_id'] = 12
                elif mutation == 'fabricated-neutral': next(r for r in rows if r.get('connected') is False)['buttons'] = 0
                elif mutation == 'gap': del rows[12:17]
                else: rows.insert(-1, dict(event='sdl_button', instance_id=11, episode=0, button=0, down=True, qpc=4000000))
                with self.assertRaises(ValueError): verify(data)

    def test_raw_error_disconnection_recovery_and_unrequested_guest_input_rejected(self):
        for mutation in ('api', 'effective', 'recovery', 'cross', 'trigger', 'axis', 'clock', 'gap'):
            with self.subTest(mutation=mutation):
                data = copy.deepcopy(fixture()); samples = data[1]; s = samples[60]
                if mutation == 'api': s.update(rc=-1, payload_valid=0, state=hp.API_ERROR, flip=0)
                elif mutation == 'effective': s['effective_axes'] = [0]*4
                elif mutation == 'recovery':
                    s.update(connected=1, timestamp=s['observed_us'], state=hp.CONNECTED, raw_axes=[128]*4)
                elif mutation == 'cross': samples[0].update(raw_buttons=hp.CROSS, effective_buttons=hp.CROSS, audio_command=1)
                elif mutation == 'trigger': samples[0]['raw_triggers'] = samples[0]['effective_triggers'] = [1, 0]
                elif mutation == 'axis': samples[0]['raw_axes'] = samples[0]['effective_axes'] = [255]*4
                elif mutation == 'clock': s['observed_us'] = samples[59]['observed_us']
                else:
                    for item in samples[60:]: item['observed_us'] += 400000
                with self.assertRaises(ValueError): verify(data)

    def test_short_progress_and_stalled_audio_or_graphics_rejected(self):
        for kind in ('short', 'audio', 'flip', 'hold', 'missing'):
            data = copy.deepcopy(fixture()); samples, phases = data[1:3]
            if kind == 'short': phases[2]['sequence'] = phases[1]['sequence']+40
            elif kind == 'audio':
                for s in samples[phases[1]['sequence']:]: s['audio_blocks'] = samples[phases[1]['sequence']]['audio_blocks']
            elif kind == 'flip': samples[phases[2]['sequence']]['flip'] -= 1
            elif kind == 'hold': phases[0]['guest_after_observed_us'] = 2000000
            else: phases.pop()
            with self.subTest(kind=kind), self.assertRaises(ValueError): verify(data)

    def test_premature_unowned_or_unbounded_close_rejected(self):
        for key, value in [('instruction_qpc_seconds', 13), ('root_exit_qpc_seconds', 14),
                           ('root_exit_qpc_seconds', 46), ('confirmed_qpc_seconds', 0),
                           ('last_owned_qpc_seconds', 14), ('ownership_failed', True),
                           ('root_exit_before_instruction', True), ('root_pid', 100),
                           ('bound_window', 0), ('last_guest_observed_us', 1),
                           ('last_guest_seen_qpc_seconds', 15.1), ('instruction_qpc_seconds', float('nan'))]:
            data = copy.deepcopy(fixture()); data[3][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError): verify(data)

    def test_forced_nonzero_owner_death_timeout_or_remaining_descendant_rejected(self):
        for key, value in [('reason', 'requested'), ('reason', 'timeout'), ('reason', 'owner_exited'),
                           ('exit_code', 1), ('exit_code', False), ('active_before_cleanup', 1),
                           ('forced_termination', True), ('tree_cleanup', False),
                           ('root_exit_verified', False), ('owner_watch_verified', False)]:
            data = copy.deepcopy(fixture()); data[4][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError): verify(data)

    def test_native_absence_must_continue_after_root_exit_and_human_close_confirmation(self):
        data = copy.deepcopy(fixture()); data[3]['confirmed_qpc_seconds'] = 16.12
        with self.assertRaises(ValueError): verify(data)
        data = copy.deepcopy(fixture()); data[0][-2].update(connected=True, input_valid=True, buttons=0, axes=[0]*4)
        with self.assertRaises(ValueError): verify(data)

    def test_removal_generated_up_is_not_required_or_classified_as_human_release(self):
        data = copy.deepcopy(fixture())
        data[0].insert(-1, dict(event='sdl_button', instance_id=11, episode=0, button=0, down=False, qpc=4960000))
        self.assertEqual(verify(data)['reconnections'], 0)

    def test_journal_must_match_raw_records_and_reserved_bytes(self):
        samples = fixture()[1]; raw = hp.HEADER+b''.join(map(hp.pack_record, samples))
        self.assertEqual(hp.verify_records(raw, samples)['records'], len(samples))
        for damaged in (raw[:-1], raw[:50]+b'\xff'+raw[51:]):
            with self.assertRaises(ValueError): hp.verify_records(damaged, samples)

    def test_three_original_images_are_exact_and_cannot_be_reused_or_modified(self):
        _, samples, phases, _, _ = fixture(); palette = bytes([1, 2, 3, 4])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for i, p in enumerate(phases):
                path = root/f'{i}.png'; path.write_bytes(png(unfiltered(hp.expected_pixels(palette, samples[p['sequence']]))))
                p.update(hp.verify_image(path, palette, samples[p['sequence']]), path=path.name)
            dc.verify_images(root, palette, samples, phases)
            phases[1]['path'] = phases[0]['path']
            with self.assertRaises(ValueError): dc.verify_images(root, palette, samples, phases)
            phases[1]['path'] = '1.png'; (root/'1.png').write_bytes((root/'0.png').read_bytes())
            with self.assertRaises(ValueError): dc.verify_images(root, palette, samples, phases)

    def test_engine_slot_and_count_cannot_recover_or_register_another_device(self):
        good = '1 controllers are currently connected\nGamepad registered for slot 0! Handle: 4\n0 controllers are currently connected'
        self.assertEqual(dc.verify_engine(good)['slots'], [0])
        for bad in ('', good+'\n1 controllers are currently connected', good.replace('slot 0', 'slot 1'),
                    good+'\nGamepad registered for slot 0! Handle: 5'):
            with self.assertRaises(ValueError): dc.verify_engine(bad)

    def test_real_guide_confirmation_order_encoding_close_gate_and_no_reconnect(self):
        with tempfile.TemporaryDirectory() as tmp:
            g = CloseGuide.__new__(CloseGuide)
            g.output = Path(tmp); g.index = None; g.mode = 'ready'; g.action_instruction_qpc = None
            g.unplug_instruction_qpc = g.close_instruction_qpc = g.closed_confirmed_qpc = None
            g.title = Value(); g.text = Value(); g.confirm_button = Button(); g.pump = lambda: None
            g.log('human_ready_clicked')
            phases = []; callback = []
            for index in range(3):
                g.stage(index)
                with self.assertRaises(ValueError): g.capture()
                if index == 1:
                    self.assertIn('Do NOT unplug yet', g.text.value); g.confirm()
                    self.assertIsNotNone(g.unplug_instruction_qpc)
                    self.assertIn('UNPLUG USB', g.title.value)
                g.confirm(); g.capture(); self.assertIn('F12', g.title.value); g.confirm()
                phases.append(dict(instruction_qpc_seconds=g.action_instruction_qpc, capture_qpc_seconds=__import__('time').perf_counter()))
            g.finish(lambda: callback.append(True)); self.assertIsNone(g.close_instruction_qpc)
            g.confirm(); self.assertEqual(callback, [True]); self.assertIn('DISCONNECTED', g.text.value)
            self.assertIsNotNone(g.close_instruction_qpc); g.confirm(); self.assertIsNotNone(g.closed_confirmed_qpc)
            rows = [json.loads(s) for s in (g.output/'human-confirmations.jsonl').read_text(encoding='utf-8').splitlines()]
            dc.verify_confirmations(rows, phases, dict(instruction_qpc_seconds=g.close_instruction_qpc,
                                                       confirmed_qpc_seconds=g.closed_confirmed_qpc))
            for index in (1, 3, len(rows)-1):
                broken = copy.deepcopy(rows); broken.pop(index)
                with self.assertRaises(ValueError): dc.verify_confirmations(broken, phases, dict(
                    instruction_qpc_seconds=g.close_instruction_qpc, confirmed_qpc_seconds=g.closed_confirmed_qpc))
            with self.assertRaises(ValueError): g.confirm()

    def test_optional_native_arguments_fail_before_sdl_or_output(self):
        helper = os.environ.get('PS4_DISCONNECTED_CLOSE_OBSERVER_CLI')
        if not helper: self.skipTest('Optional prebuilt local SDL helper not supplied')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            command = [helper, '--watch-disconnect', str(root/'report'), str(root/'stop'), str(root/'ready'), '390000']
            for extra in ([], ['--reconnect-authorized'], ['--disconnect-authorized', '--reconnect-authorized']):
                result = subprocess.run(command+extra, capture_output=True, timeout=5)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(any(root.iterdir()))
            command[-1] = 'invalid'
            result = subprocess.run(command+['--disconnect-authorized'], capture_output=True, timeout=5)
            self.assertNotEqual(result.returncode, 0); self.assertFalse(any(root.iterdir()))

    def test_real_runner_with_inert_process_window_and_generated_io(self):
        # Exercise the real coordination/cleanup loop. All process/window/clock
        # boundaries are inert; generated output is never hardware acceptance.
        import pad_disconnected_close_guest_tests as runner
        from pad_hotplug_tests import audit
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp); source = out/'host-only-placeholder'; source.write_bytes(b'host test only')
            args = SimpleNamespace(output=out, fixture=source, engine=source, supervisor=source, sdl_observer=source)
            clock = [10.0]; gone = [False]; samples = []; rows = []; stopped = [False]
            result = {}; g = CloseGuide.__new__(CloseGuide)
            g.output = out; g.index = None; g.mode = 'ready'; g.started_qpc = 10
            g.unplug_instruction_qpc = g.close_instruction_qpc = g.closed_confirmed_qpc = None
            g.action_instruction_qpc = None; g.title = Value(); g.text = Value(); g.confirm_button = Button()
            g.action_confirmed = g.capture_confirmed = False; pumping = [False]
            def now():
                clock[0] += .000001
                return clock[0]
            def advance(seconds):
                clock[0] += max(seconds, .1)
                connected = not gone[0]; us = int(clock[0]*1e6)
                sample = dict(sequence=len(samples), handle=1, rc=0, audio_command=0, observed_us=us,
                    timestamp=us if connected else 0, flip=len(samples)+1, audio_blocks=len(samples)*3,
                    raw_buttons=0, effective_buttons=0, raw_axes=[128]*4 if connected else [0]*4,
                    effective_axes=[128]*4, connected=int(connected), count=int(connected),
                    raw_triggers=[0,0], effective_triggers=[0,0], payload_valid=1,
                    state=hp.CONNECTED if connected else hp.DISCONNECTED, elapsed_us=us)
                if not (g.close_instruction_qpc and clock[0]-g.close_instruction_qpc > .15):
                    samples.append(sample)
                    (out/'session/startup-audit.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in audit(samples)), encoding='utf-8')
                rows.append(dict(event='hotplug_state', qpc=us, instance_id=11, episode=0,
                    connected=connected, input_valid=connected, buttons=0 if connected else None, axes=[0]*4 if connected else None))
                (out/'native.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows), encoding='utf-8')
            def root_done(): return g.close_instruction_qpc is not None and clock[0]-g.close_instruction_qpc > .15
            def pump():
                if pumping[0]: return
                pumping[0] = True
                try:
                    if g.mode in ('action','unplug-permission','close-permission'):
                        old = g.mode; g.confirm()
                        if old == 'unplug-permission':
                            gone[0] = True
                            rows.append(dict(event='hotplug_removed', qpc=int(now()*1e6), episode=0,
                                             instance_id=11, sdl_timestamp_ns=int(clock[0]*1e9)))
                    elif g.mode == 'capture':
                        path = out/'session/user/screenshots'/f'{g.index}.png'
                        path.parent.mkdir(exist_ok=True)
                        palette = (out/'session/app/palette.bin').read_bytes()
                        path.write_bytes(png(unfiltered(hp.expected_pixels(palette, samples[-1]))))
                        g.confirm()
                    elif g.mode == 'close' and root_done(): g.confirm()
                finally: pumping[0] = False
            g.pump = pump
            class Observer:
                returncode = None
                def __init__(self, command, **kwargs):
                    if command[1] != '--watch-disconnect' or '--reconnect-authorized' in command:
                        raise AssertionError('Unexpected process operation in host-only test')
                    rows.append(dict(event='hotplug_opened', qpc=int(now()*1e6), qpc_frequency=1000000,
                        episode=0, instance_id=11, connection='wired', vendor=1356, product=3302,
                        real_type=6, virtual=False, sole=True, sdl_timestamp_ns=0))
                    (out/'native-ready.txt').touch()
                def poll(self): return self.returncode
                def wait(self, **kwargs):
                    rows.append(dict(event='stopped', qpc=int(now()*1e6)))
                    (out/'native.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows), encoding='utf-8')
                    self.returncode = 0; stopped[0] = True
            class Window:
                pid = 99; window = 1234
                def __init__(self, binding, emit, **kwargs):
                    self.diagnostics = SimpleNamespace(kernel=SimpleNamespace(WaitForSingleObject=lambda *args:0 if root_done() else 258),
                        process=object(), drain=lambda:None, snapshot=lambda *args:None)
                def poll(self):
                    if root_done(): raise AssertionError('Ownership query after expected root exit')
                def summary(self): return dict(host_only=True)
                def close(self): pass
            def supervise(supervisor, command, work, timeout, on_poll, on_started):
                on_started(88)
                for _ in range(250):
                    advance(.1); self.assertFalse(on_poll())
                    if root_done(): break
                else: self.fail('Host-only runner simulation did not reach normal close')
                (work/'user/data').mkdir(exist_ok=True)
                (work/'user/data/pad-hotplug.bin').write_bytes(hp.HEADER+b''.join(map(hp.pack_record,samples)))
                (work/'user/log').mkdir(exist_ok=True)
                (work/'user/log/shad_log.txt').write_text('1 controllers are currently connected\nGamepad registered for slot 0! Handle: 4\n0 controllers are currently connected')
                return fixture()[4]
            with patch.object(runner.subprocess,'Popen',Observer), patch.object(runner.startup,'supervise',supervise), \
                    patch.object(runner.windows,'_owned_window',lambda *args:None), patch.object(runner,'OwnedWindowTrace',Window), \
                    patch.object(runner.time,'perf_counter',now), patch.object(runner.time,'sleep',advance):
                g.log('human_ready_clicked')
                runner.run(args, result, g, SimpleNamespace(check=lambda:None))
            self.assertTrue(stopped[0]); self.assertEqual(result['evidence_requirements']['qualified_phases'],3)
            self.assertFalse(result['transport']['forced_termination'])


if __name__ == '__main__': unittest.main()
