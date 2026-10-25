# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
"""Independent raw guest Pad/SDL/graphics checks; no input generation."""
import re
import struct

import run_homebrew_startup as startup
import videoout_evidence as video

HEADER = struct.pack('<8sII', b'PADAX1\0\0', 1, 32)
RECORD = struct.Struct('<IIQQ4BB3x')
SAMPLE = re.compile(r'pad-axes: sample=(\d{1,4}) buttons=(\d{1,10}) timestamp=(\d{1,20}) '
                    r'flip=(\d{1,20}) lx=(\d{1,3}) ly=(\d{1,3}) rx=(\d{1,3}) ry=(\d{1,3}) connected=(\d)')
PLAN = [('center', None, 0)]
for stick, offset in (('left', 0), ('right', 2)):
    for direction, axis, sign in (('left', 0, -1), ('right', 0, 1), ('up', 1, -1), ('down', 1, 1)):
        PLAN.extend([(f'{stick}-stick-{direction}', offset + axis, sign), (f'{stick}-return-center-{direction}', None, 0)])


def matches(axes, buttons, connected, phase, *, sdl=False):
    if (len(axes) != 4 or type(buttons) is not int or buttons != 0 or connected not in (True, 1) or
            any(type(v) is not int for v in axes)):
        return False
    _, target, sign = phase
    for i, value in enumerate(axes):
        if sdl:
            if not -32768 <= value <= 32767: return False
            if i == target:
                if sign * value < 28672: return False
            elif abs(value) > 2048: return False
        else:
            if not 0 <= value <= 255: return False
            if i == target:
                if not (value <= 32 if sign < 0 else value >= 223): return False
            elif not 120 <= value <= 136: return False
    return True


def progress(events):
    strict = startup.evaluate(events)
    entered = begun = ready = False
    samples = []
    for event in events:
        if event['event'] == 'guest_entry': entered = True
        if event['event'] != 'guest_output': continue
        text = event['text']
        if text == 'pad-axes: begin schema=1':
            if not entered or begun: raise ValueError('Invalid axes begin')
            begun = True
        elif text == 'pad-axes: ready schema=1':
            if not begun or ready: raise ValueError('Invalid axes readiness')
            ready = True
        elif text.startswith('pad-axes:'):
            match = SAMPLE.fullmatch(text)
            if not ready or match is None: raise ValueError('Invalid/failing axes guest output: '+text)
            sequence, buttons, stamp, flip, *values = map(int, match.groups())
            axes, connected = values[:4], values[4]
            if (sequence != len(samples) or sequence >= 6000 or buttons > 0xffffffff or connected != 1 or
                    max(axes) > 255 or not 0 < stamp <= 0xffffffffffffffff or flip != sequence+1 or
                    (samples and stamp < samples[-1]['timestamp'])):
                raise ValueError('Invalid axes record identity/range/connection/timestamp')
            samples.append(dict(sequence=sequence, buttons=buttons, timestamp=stamp, flip=flip,
                                axes=axes, connected=connected, elapsed_us=event['elapsed_us']))
    return dict(guest_entry_observed=strict['guest_entry_observed'], running_observed=ready and bool(samples), samples=samples)


def verify_records(raw, samples):
    if not samples or raw[:16] != HEADER or len(raw) != 16 + len(samples)*32:
        raise ValueError('Wrong axes schema/record count')
    for sample, record, offset in zip(samples, RECORD.iter_unpack(raw[16:]), range(16, len(raw), 32)):
        expected = (sample['sequence'], sample['buttons'], sample['timestamp'], sample['flip'], *sample['axes'], sample['connected'])
        if record != expected or raw[offset+29:offset+32] != b'\0\0\0':
            raise ValueError('Axes guest binary and strict audit disagree')
    return dict(records=len(samples), bytes_verified=len(raw), schema_version=1)


def expected_pixels(palette, sample):
    if len(palette) != 4 or len(set(palette)) != 4 or any(not 0 <= v <= 7 for v in palette):
        raise ValueError('Invalid axes palette')
    pixels = bytearray()
    for axis, value in enumerate(sample['axes']):
        end = value * 639 // 255
        color = palette[axis]
        rgba = bytes((255 if color & 1 else 0, 255 if color & 2 else 0, 255 if color & 4 else 0, 255))
        pixels.extend((rgba*(end+1)+bytes((32,32,32,255))*(639-end))*90)
    words = (sample['sequence'], sum(value << (8*i) for i,value in enumerate(sample['axes'])), sample['buttons'])
    for word_index, word in enumerate(words):
        for bit in range(32):
            pos = (word_index*32+bit)*4
            pixels[pos:pos+4] = bytes([255 if word & (1 << bit) else 0]*3+[255])
    pixels[384:388] = bytes([255 if sample['connected'] else 0]*3+[255])
    return bytes(pixels)


def image_sequence(path):
    if not path.is_file() or not 0 < path.stat().st_size <= video.MAX_PNG_BYTES:
        raise ValueError('Missing/oversized axes PNG')
    pixels = video.decode_png(path.read_bytes())
    word = 0
    for bit in range(32):
        pixel = pixels[bit*4:bit*4+4]
        if pixel not in (b'\0\0\0\xff', b'\xff\xff\xff\xff'):
            raise ValueError('Invalid image observation identity')
        if pixel[0]: word |= 1 << bit
    if word >= 6000: raise ValueError('Out-of-range image observation')
    return word


def verify_image(path, palette, sample):
    if image_sequence(path) != sample['sequence'] or video.decode_png(path.read_bytes()) != expected_pixels(palette,sample):
        raise ValueError('Axes Vulkan pixels disagree with exact guest observation')
    return dict(sequence=sample['sequence'], axes=sample['axes'], buttons=sample['buttons'], connected=sample['connected'],
                pixels_verified=640*360, sha256=startup.digest(path))


def stable_suffix(samples, phase, *, sdl=False, after=0, frequency=1):
    good = []
    key = 'qpc' if sdl else 'elapsed_us'
    rate = frequency if sdl else 1000000
    for sample in reversed(samples):
        if sample[key]/rate < after or not matches(sample['axes'],sample['buttons'],sample['connected'],phase,sdl=sdl): break
        if good and (good[-1][key]-sample[key])/rate > .35: break
        good.append(sample)
    good.reverse()
    seconds = (good[-1][key]-good[0][key])/rate if len(good)>1 else 0
    return good, seconds


def sdl_cutoff_covered(records, frequency, cutoff):
    """A serialized SDL sample at/after cutoff seals its earlier sample prefix."""
    previous = -1
    for row in records:
        if row['event'] != 'axis_state': continue
        stamp = row['qpc']
        if type(stamp) is not int or stamp <= previous:
            raise ValueError('Non-monotonic SDL axes snapshot')
        previous = stamp
    return previous >= 0 and previous/frequency >= cutoff


def verify_capture(opened, records, samples, qualified):
    """The existing final phase rule, shared with live capture qualification."""
    phase = PLAN[qualified['index']]
    frequency = opened['qpc_frequency']
    states = [r for r in records if r['event']=='axis_state']
    sequence = qualified['sequence']
    stop = qualified['capture_qpc_seconds']
    sdl, seconds = stable_suffix([s for s in states if s['qpc']/frequency <= stop],phase,sdl=True,
                                after=qualified['instruction_qpc_seconds'],frequency=frequency)
    sample = samples[sequence]
    guest, duration = stable_suffix(samples[:sample['sequence']+1],phase,after=qualified['guest_after_elapsed_seconds'])
    if seconds<3 or duration<3 or len(sdl)<20 or len(guest)<20 or not qualified['pixels_verified']==640*360:
        raise ValueError('Missing sustained independent SDL/guest/image phase evidence')
    if phase[1] is not None:
        motions = [r for r in records if r['event']=='physical_axis' and r['instance_id']==opened['instance_id'] and
                   r['axis']==phase[1] and qualified['instruction_qpc_seconds']<=r['qpc']/frequency<=stop and phase[2]*r['value']>=28672]
        if not motions: raise ValueError('Missing real SDL axis-motion event for requested direction')
    return dict(stable_sdl_seconds=seconds, stable_guest_seconds=duration)


def verify_phases(records, samples, phases):
    opened = [r for r in records if r['event']=='opened']
    if (len(opened)!=1 or opened[0]['connection']!='wired' or opened[0]['virtual'] is not False or
            (opened[0]['vendor'],opened[0]['product'])!=(0x054c,0x0ce6) or opened[0]['qpc_frequency']<=0 or
            any(r['event']=='removed' or (r['event'] in ('state','axis_state') and not r['connected']) for r in records)):
        raise ValueError('Missing sole physical wired DualSense continuity')
    if len(phases)!=len(PLAN): raise ValueError('Missing physical axes phases')
    previous_sequence = -1
    previous_capture = 0
    for index, (phase, qualified) in enumerate(zip(PLAN,phases)):
        if qualified['index']!=index or qualified['label']!=phase[0]: raise ValueError('Wrong axes phase order')
        sequence = qualified['sequence']
        if (type(sequence) is not int or not previous_sequence < sequence < len(samples) or
                not previous_capture < qualified['instruction_qpc_seconds'] < qualified['capture_qpc_seconds']):
            raise ValueError('Stale/out-of-order axes observation or instruction')
        verify_capture(opened[0], records, samples, qualified)
        stop = qualified['capture_qpc_seconds']
        previous_sequence, previous_capture = sequence, stop
    return dict(sticks=['left','right'], directions=['left','right','up','down'], qualified_phases=len(phases),
                raw_guest_axes_verified=True, center_and_returns_verified=True, keyboard_injection_performed=False,
                scope='cardinal movement/center only; no calibration, full-range linearity, diagonals or Bluetooth claim')
