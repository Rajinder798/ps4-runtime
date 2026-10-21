# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
"""Separate disconnected-close contract. No device/UI access or input generation."""
import math
import pad_hotplug_evidence as hp

PLAN = [('initial-neutral', hp.CONNECTED, 0), ('disconnected', hp.DISCONNECTED, 0),
        ('disconnected-progress', hp.DISCONNECTED, 0)]
TOTAL_SECONDS = 360
CLOSE_SECONDS = 30


def positive(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def matches(row, index, *, native=False):
    # Reuse existing state/neutral semantics, never the seven-stage acceptance plan.
    return hp.matches(row, (0, 2, 3)[index], native=native)


def stable_suffix(rows, index, *, native=False, after=0, frequency=1):
    return hp.stable_suffix(rows, (0, 2, 3)[index], native=native, after=after, frequency=frequency)


def verify_transport(transport):
    expected = dict(reason='exited', exit_code=0, active_before_cleanup=0,
                    forced_termination=False, tree_cleanup=True, root_exit_verified=True,
                    owner_watch_verified=True)
    if any(type(transport.get(k)) is not type(v) or transport[k] != v for k, v in expected.items()):
        raise ValueError('Normal zero/independently empty owned process exit not verified')
    if type(transport.get('root_pid')) is not int or transport['root_pid'] <= 0:
        raise ValueError('Missing retained root process identity')


def verify_engine(log):
    import re
    counts = list(map(int, re.findall(r'(\d+) controllers are currently connected', log)))
    slots = list(map(int, re.findall(r'Gamepad registered for slot (\d+)! Handle: \d+', log)))
    collapsed = [n for i, n in enumerate(counts) if i == 0 or n != counts[i-1]]
    # Initial zero inventory can precede the first controller registration.
    if collapsed not in ([1, 0], [0, 1, 0]) or slots != [0]:
        raise ValueError('One engine slot-zero registration then absence not verified')
    return dict(controller_counts=counts, slots=slots)


def verify_images(output, palette, samples, phases):
    root = output.resolve()
    paths = set()
    for p in phases:
        path = (root/p['path']).resolve()
        if not path.is_relative_to(root) or path in paths:
            raise ValueError('Image outside original session or duplicated')
        paths.add(path)
        image = hp.verify_image(path, palette, samples[p['sequence']])
        if any(p.get(k) != v for k, v in image.items()):
            raise ValueError('Original image changed after qualification')


def verify_confirmations(rows, phases, close):
    ready = [r for r in rows if r.get('event') == 'human_ready_clicked']
    if len(ready) != 1 or not positive(ready[0].get('qpc_seconds')):
        raise ValueError('One human Ready action required')
    previous = 0
    for row in rows:
        now = row.get('qpc_seconds')
        if not positive(now) or now < previous: raise ValueError('Confirmation clock invalid')
        previous = now
    if previous-ready[0]['qpc_seconds'] > TOTAL_SECONDS:
        raise ValueError('Human session exceeded six minutes')
    for i, p in enumerate(phases):
        stage = [r for r in rows if r.get('event') == 'stage_prompt' and r.get('index') == i]
        if len(stage) != 1 or stage[0].get('mode') != ('unplug-permission' if i == 1 else 'action'):
            raise ValueError('Missing/repeated stage instruction')
        confirms = [r for r in rows if r.get('event') == 'human_confirmation' and r.get('index') == i]
        expected = ['action', 'capture'] if i == 0 else ['unplug-permission', 'action', 'capture'] if i == 1 else ['action', 'capture', 'close-permission', 'close']
        if [r.get('confirmed_step') for r in confirms] != expected:
            raise ValueError('Missing/repeated/out-of-order physical confirmation')
        action = next(r for r in confirms if r['confirmed_step'] == 'action')
        capture = next(r for r in confirms if r['confirmed_step'] == 'capture')
        prompts = [r for r in rows if r.get('event') == 'capture_prompt' and r.get('index') == i]
        if (len(prompts) != 1 or not ready[0]['qpc_seconds'] < p['instruction_qpc_seconds'] <= action['qpc_seconds'] <
                prompts[0]['qpc_seconds'] < capture['qpc_seconds'] <= p['capture_qpc_seconds']):
            raise ValueError('Capture/action confirmation outside qualified instruction')
    unplug = [r for r in rows if r.get('event') == 'usb_action_instruction']
    normal_close = [r for r in rows if r.get('event') == 'normal_close_instruction']
    if (len(unplug) != 1 or unplug[0].get('index') != 1 or
            not phases[1]['instruction_qpc_seconds'] <= unplug[0]['qpc_seconds'] < phases[1]['capture_qpc_seconds'] or
            len(normal_close) != 1 or normal_close[0].get('index') != 2 or
            not close['instruction_qpc_seconds'] <= normal_close[0]['qpc_seconds'] < close['confirmed_qpc_seconds']):
        raise ValueError('Missing explicit unplug/normal-close instruction')
    final = [r for r in rows if r.get('event') == 'human_confirmation' and r.get('confirmed_step') == 'close']
    if len(final) != 1 or final[0]['qpc_seconds'] < close['confirmed_qpc_seconds']:
        raise ValueError('Missing final close confirmation')


def verify_native(native):
    opened = [r for r in native if r.get('event') == 'hotplug_opened']
    removed = [r for r in native if r.get('event') == 'hotplug_removed']
    stopped = [r for r in native if r.get('event') == 'stopped']
    if len(opened) != 1 or len(removed) != 1 or len(stopped) != 1 or native[-1] != stopped[0]:
        raise ValueError('Exactly one initial device/removal and complete observer stop required')
    o, r, end = opened[0], removed[0], stopped[0]
    if ((o.get('vendor'), o.get('product'), o.get('real_type')) != (1356, 3302, 6) or
            o.get('connection') != 'wired' or o.get('virtual') is not False or o.get('sole') is not True or
            type(o.get('episode')) is not int or o['episode'] != 0 or
            any(type(o.get(k)) is not int or o[k] <= 0 for k in ('qpc', 'qpc_frequency', 'instance_id')) or
            r.get('instance_id') != o['instance_id'] or type(r.get('episode')) is not int or r['episode'] != 0 or
            type(r.get('sdl_timestamp_ns')) is not int or r['sdl_timestamp_ns'] <= 0 or
            any(type(x.get('qpc')) is not int for x in (r, end)) or not o['qpc'] < r['qpc'] < end['qpc']):
        raise ValueError('Sole wired DualSense removal identity/clock not verified')
    states = [s for s in native if s.get('event') == 'hotplug_state']
    previous = o['qpc']; absent = False
    for s in states:
        if (type(s.get('qpc')) is not int or not previous < s['qpc'] < end['qpc'] or
                (s['qpc']-previous)/o['qpc_frequency'] > .35 or
                type(s.get('instance_id')) is not int or s['instance_id'] != o['instance_id'] or
                type(s.get('episode')) is not int or s['episode'] != 0 or
                type(s.get('connected')) is not bool or type(s.get('input_valid')) is not bool):
            raise ValueError('Native identity, continuity or payload schema changed')
        if s['connected']:
            if (absent or s['qpc'] >= r['qpc'] or not s['input_valid'] or type(s.get('buttons')) is not int or
                    s['buttons'] != 0 or not isinstance(s.get('axes'), list) or len(s['axes']) != 4 or
                    any(type(v) is not int or abs(v) > 2048 for v in s['axes'])):
                raise ValueError('Unexpected native input or connection after removal')
        else:
            absent = True
            if s['qpc'] < r['qpc'] or s['input_valid'] or s.get('buttons') is not None or s.get('axes') is not None:
                raise ValueError('Native absence fabricated as valid neutral input')
        previous = s['qpc']
    if not states or not states[0]['connected'] or not absent or states[-1]['connected']:
        raise ValueError('Connected then sustained absent native observations missing')
    if (end['qpc']-previous)/o['qpc_frequency'] > .35:
        raise ValueError('Native observation stopped with a continuity gap')
    for e in native:
        if e['event'] == 'sdl_button':
            # Removal-generated ups are events only, never human-release evidence.
            if (e.get('instance_id') != o['instance_id'] or e.get('episode') != 0 or
                    e.get('down') is not False or type(e.get('button')) is not int or e['button'] != 0 or
                    type(e.get('qpc')) is not int or not r['qpc']-.35*o['qpc_frequency'] <= e['qpc'] <= r['qpc']+.35*o['qpc_frequency']):
                raise ValueError('Unrequested control edge in neutral-only procedure')
        elif e['event'] not in ('opened', 'hotplug_opened', 'hotplug_removed', 'hotplug_state', 'stopped'):
            raise ValueError('Unexpected native event')
    return o, r, end, states


def verify(native, samples, phases, close, transport, *, disconnect_authorized=False):
    if disconnect_authorized is not True:
        raise ValueError('Explicit physical disconnect authorization required')
    hp.validate_samples(samples)
    verify_transport(transport)
    transitions = []
    for s in samples:
        if not transitions or s['state'] != transitions[-1]: transitions.append(s['state'])
        if s['state'] == hp.CONNECTED and (s['raw_buttons'] != 0 or s['raw_triggers'] != [0, 0] or
                                         any(not 120 <= v <= 136 for v in s['raw_axes'])):
            raise ValueError('Unrequested connected guest input')
    if transitions != [hp.CONNECTED, hp.DISCONNECTED]:
        raise ValueError('Guest must remain disconnected until close; API failure/recovery forbidden')
    if any(b['observed_us']-a['observed_us'] > 350000 for a, b in zip(samples, samples[1:])):
        raise ValueError('Guest observation continuity gap')
    o, removal, end, states = verify_native(native)
    frequency = o['qpc_frequency']
    if len(phases) != 3:
        raise ValueError('Three independently verified images required')
    previous_seq = -1; previous_capture = 0
    for i, p in enumerate(phases):
        seq = p.get('sequence'); start = p.get('instruction_qpc_seconds'); stop = p.get('capture_qpc_seconds')
        if (type(p.get('index')) is not int or p['index'] != i or p.get('label') != PLAN[i][0] or
                type(seq) is not int or not previous_seq < seq < len(samples) or
                not positive(start) or not positive(stop) or not previous_capture < start < stop or
                p.get('pixels_verified') != 640*360 or p.get('state') != PLAN[i][1] or
                type(p.get('guest_after_observed_us')) is not int or p['guest_after_observed_us'] < 0):
            raise ValueError('Missing, stale or mislabelled disconnected-close image')
        guest, duration = stable_suffix(samples[:seq+1], i, after=p['guest_after_observed_us']/1e6)
        sdl, seconds = stable_suffix([r for r in states if r['qpc']/frequency <= stop], i,
                                     native=True, after=start, frequency=frequency)
        if min(duration, seconds) < 3 or min(len(guest), len(sdl)) < 20:
            raise ValueError('Three-second/20-sample independent state not established')
        if i == 0 and stop >= removal['qpc']/frequency:
            raise ValueError('Neutral capture after removal')
        if i == 1 and not start < removal['qpc']/frequency < stop:
            raise ValueError('Removal outside explicit unplug instruction')
        if i == 2 and start <= removal['qpc']/frequency:
            raise ValueError('Progress stage before actual removal')
        previous_seq, previous_capture = seq, stop
    a, b = (samples[phases[i]['sequence']] for i in (1, 2))
    if b['observed_us']-a['observed_us'] < 5000000 or b['flip'] <= a['flip'] or b['audio_blocks'] <= a['audio_blocks']:
        raise ValueError('Five-second disconnected graphics/audio-block progress missing')
    times = ('last_owned_qpc_seconds', 'instruction_qpc_seconds', 'root_exit_qpc_seconds',
             'supervision_finished_qpc_seconds', 'confirmed_qpc_seconds')
    if any(not positive(close.get(k)) for k in times):
        raise ValueError('Incomplete human-close/root-exit timing')
    last, instructed, exited, finished, confirmed = (close[k] for k in times)
    if (not previous_capture <= last <= instructed < exited <= finished or confirmed <= instructed or
            exited-instructed > CLOSE_SECONDS or instructed-last > .35 or
            states[-1]['qpc']/frequency < max(finished, confirmed) or
            type(close.get('root_pid')) is not int or close['root_pid'] != transport['root_pid'] or
            type(close.get('bound_window')) is not int or close['bound_window'] <= 0 or
            close.get('root_exit_before_instruction') is not False or close.get('ownership_failed') is not False):
        raise ValueError('Premature, unowned, unconfirmed or unbounded window close')
    # The final journal entry must still be fresh when normal close is instructed.
    if (close.get('last_guest_observed_us') != samples[-1]['observed_us'] or
            not positive(close.get('last_guest_seen_qpc_seconds')) or
            not instructed <= close['last_guest_seen_qpc_seconds'] <= finished or
            exited-close['last_guest_seen_qpc_seconds'] > .35):
        raise ValueError('Guest progress not observed through the close interval')
    return dict(qualified_phases=3, removals=1, reconnections=0, normal_exit_verified=True,
                scope='single disconnected user-close; no guest thread join, PCM or acoustic qualification')
