# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
"""Strict isolated hot-plug evidence. No device access or input generation."""
import re
import struct

import run_homebrew_startup as startup
import videoout_evidence as video

CROSS = 0x4000
HEADER = struct.pack('<8sII', b'PADHP1\0\0', 1, 72)
RECORD = struct.Struct('<IiiIQQQIII16B4s')
CONNECTED, DISCONNECTED, API_ERROR, BAD_TIMESTAMP, STALE = range(1, 6)
PLAN = [('initial-neutral', CONNECTED, 0), ('before-cross', CONNECTED, CROSS),
        ('disconnected', DISCONNECTED, 0), ('disconnected-progress', DISCONNECTED, 0),
        ('reconnected-neutral', CONNECTED, 0), ('reconnected-cross', CONNECTED, CROSS),
        ('reconnected-release', CONNECTED, 0)]
SCALARS = ['sequence','handle','rc','audio_command','observed_us','timestamp','flip',
           'audio_blocks','raw_buttons','effective_buttons']
LINE = re.compile(r'pad-hotplug-av: sample=(\d+) handle=(-?\d+) rc=(-?\d+) command=(\d+) '
    r'observed=(\d+) timestamp=(\d+) flip=(\d+) audio_blocks=(\d+) raw_buttons=(\d+) effective_buttons=(\d+) '
    r'raw_axes=(\d+),(\d+),(\d+),(\d+) effective_axes=(\d+),(\d+),(\d+),(\d+) '
    r'connected=(\d+) count=(\d+) raw_triggers=(\d+),(\d+) effective_triggers=(\d+),(\d+) valid=(\d+) state=(\d+)')


def pack_record(s):
    return RECORD.pack(*(s[k] for k in SCALARS), *s['raw_axes'], *s['effective_axes'],
        s['connected'], s['count'], *s['raw_triggers'], *s['effective_triggers'], s['payload_valid'], s['state'], b'\0'*4)


def validate_samples(samples):
    if not samples: raise ValueError('No actual guest hotplug observations')
    last_stamp = 0
    available = False
    previous = None
    for i,s in enumerate(samples):
        values = [s[k] for k in SCALARS] + s['raw_axes'] + s['effective_axes'] + [s['connected'],s['count']] + \
            s['raw_triggers'] + s['effective_triggers'] + [s['payload_valid'],s['state']]
        if (any(type(v) is not int for v in values) or len(s['raw_axes'])!=4 or len(s['effective_axes'])!=4 or
                len(s['raw_triggers'])!=2 or len(s['effective_triggers'])!=2 or
                s['sequence']!=i or i>=4096 or not 0<s['handle']<=0x7fffffff or
                not -0x80000000<=s['rc']<=0x7fffffff or s['audio_command'] not in (0,1) or
                s['payload_valid'] != int(s['rc']==0) or s['connected'] not in (0,1) or
                any(not 0<=s[k]<=0xffffffffffffffff for k in ('observed_us','timestamp','flip')) or
                s['observed_us']==0 or any(not 0<=s[k]<=0xffffffff for k in ('audio_blocks','raw_buttons','effective_buttons')) or
                any(not 0<=v<=255 for v in values[10:])):
            raise ValueError('Hotplug schema, range, payload validity or sequence mismatch')
        # Byte-range checks above deliberately exclude the three uint32 fields.
        if previous and (s['handle']!=previous['handle'] or s['observed_us']<=previous['observed_us'] or
                         s['audio_blocks']<previous['audio_blocks'] or previous['state']>=API_ERROR):
            raise ValueError('Guest handle reopened, clock/progress reversed or continued after fatal report')
        expected = CONNECTED
        if s['rc']!=0: expected=API_ERROR
        elif not s['connected']: expected=DISCONNECTED
        elif s['timestamp']==0: expected=BAD_TIMESTAMP
        elif s['timestamp']<last_stamp or (not available and s['timestamp']<=last_stamp): expected=STALE
        if s['state']!=expected: raise ValueError('Raw Pad result was misclassified')
        usable=expected==CONNECTED
        if (s['effective_buttons']!=(s['raw_buttons'] if usable else 0) or
                s['effective_axes']!=(s['raw_axes'] if usable else [128]*4) or
                s['effective_triggers']!=(s['raw_triggers'] if usable else [0,0]) or
                s['audio_command']!=int(usable and bool(s['raw_buttons']&CROSS)) or
                s['flip']!=(i+1 if expected<API_ERROR else 0)):
            raise ValueError('Effective input/audio/flip contradicts raw Pad result')
        if usable: last_stamp=s['timestamp']
        available=usable
        previous=s
    return dict(records=len(samples),fatal_report=samples[-1]['state']>=API_ERROR)


def progress(events, *, allow_failure=False):
    strict=startup.evaluate(events)
    begun=ready=entered=False
    samples=[];failure=None
    for e in events:
        if e['event']=='guest_entry': entered=True
        if e['event']!='guest_output': continue
        text=e['text']
        if not text.startswith('pad-hotplug-av:'): continue
        if failure is not None: raise ValueError('Guest continued after hotplug failure')
        if text=='pad-hotplug-av: begin schema=1':
            if not entered or begun: raise ValueError('Invalid hotplug begin')
            begun=True
        elif text=='pad-hotplug-av: ready schema=1':
            if not begun or ready: raise ValueError('Invalid hotplug readiness')
            ready=True
        elif text.startswith('pad-hotplug-av: FAIL '):
            if not begun: raise ValueError('Hotplug failure before begin')
            failure=text
        else:
            match=LINE.fullmatch(text)
            if not ready or match is None: raise ValueError('Malformed hotplug guest output: '+text)
            v=list(map(int,match.groups()))
            samples.append(dict(zip(SCALARS,v[:10]),raw_axes=v[10:14],effective_axes=v[14:18],
                connected=v[18],count=v[19],raw_triggers=v[20:22],effective_triggers=v[22:24],
                payload_valid=v[24],state=v[25],elapsed_us=e['elapsed_us']))
    if samples:
        checked=validate_samples(samples)
        if checked['fatal_report']: failure=failure or 'Fatal Pad result recorded before failure marker'
    if failure and not allow_failure: raise ValueError(failure)
    return dict(guest_entry_observed=strict['guest_entry_observed'],running_observed=ready and bool(samples) and not failure,
                samples=samples,failure=failure)


def verify_records(raw,samples):
    checked=validate_samples(samples)
    if raw!=HEADER+b''.join(map(pack_record,samples)):
        raise ValueError('Hotplug guest binary/header/reserved bytes and strict audit disagree')
    return dict(**checked,bytes_verified=len(raw),schema_version=1)


def expected_pixels(palette,s):
    if len(palette)!=4 or len(set(palette))!=4 or any(not 0<=v<=7 for v in palette):
        raise ValueError('Invalid hotplug palette')
    if s['state'] not in (CONNECTED,DISCONNECTED) or s['flip']!=s['sequence']+1:
        raise ValueError('Fatal report cannot be presented as completed graphics')
    indicator=bytes((255,0,0,255) if s['state']==DISCONNECTED else (0,255,0,255))
    colors=[bytes((255 if c&1 else 0,255 if c&2 else 0,255 if c&4 else 0,255)) for c in palette]
    pixels=bytearray(indicator*640*24)
    for y in range(24,360):
        pixels.extend(b''.join(colors[(x+y//45+s['audio_command'])%4]*80 for x in range(8)))
    encoded=pack_record(s)
    for bit in range(72*8):
        value=255 if encoded[bit//8]&(1<<(bit%8)) else 0
        pixels[bit*4:bit*4+4]=bytes((value,value,value,255))
    return bytes(pixels)


def image_sequence(path):
    if not path.is_file() or not 0<path.stat().st_size<=video.MAX_PNG_BYTES: raise ValueError('Missing/oversized hotplug PNG')
    pixels=video.decode_png(path.read_bytes()); sequence=0
    for bit in range(32):
        p=pixels[bit*4:bit*4+4]
        if p not in (b'\0\0\0\xff',b'\xff\xff\xff\xff'): raise ValueError('Invalid hotplug image identity')
        if p[0]: sequence |= 1<<bit
    if sequence>=4096: raise ValueError('Hotplug image sequence out of bounds')
    return sequence


def verify_image(path,palette,sample):
    if image_sequence(path)!=sample['sequence'] or video.decode_png(path.read_bytes())!=expected_pixels(palette,sample):
        raise ValueError('Hotplug Vulkan pixels disagree with exact guest report')
    return dict(sequence=sample['sequence'],state=sample['state'],pixels_verified=640*360,sha256=startup.digest(path))


def matches(s,index,*,native=False):
    _,state,buttons=PLAN[index]
    if native:
        if not s['connected']: return state==DISCONNECTED and s['input_valid'] is False and s['buttons'] is None and s['axes'] is None
        return (state==CONNECTED and s['input_valid'] is True and s['buttons']==(1 if buttons else 0) and
                len(s['axes'])==4 and all(abs(v)<=2048 for v in s['axes']) and s['episode']==(1 if index>=4 else 0))
    return s['state']==state and s['effective_buttons']==buttons and (state==DISCONNECTED or
        (s['connected']==1 and all(120<=v<=136 for v in s['raw_axes']) and s['raw_triggers']==[0,0]))


def stable_suffix(rows,index,*,native=False,after=0,frequency=1):
    key,rate=('qpc',frequency) if native else ('observed_us',1000000)
    good=[]
    for s in reversed(rows):
        if s[key]/rate<=after or not matches(s,index,native=native): break
        if good and (good[-1][key]-s[key])/rate>.35: break
        good.append(s)
    good.reverse()
    return good,(good[-1][key]-good[0][key])/rate if len(good)>1 else 0


def verify_phases(native,samples,phases,*,disconnect_authorized=False,reconnect_authorized=False):
    if disconnect_authorized is not True or reconnect_authorized is not True:
        raise ValueError('Separate explicit disconnect and reconnect authorization required')
    validate_samples(samples)
    if any(s['state']>=API_ERROR for s in samples): raise ValueError('Fatal guest observation cannot pass physical acceptance')
    transitions=[]
    for s in samples:
        if not transitions or transitions[-1]!=s['state']: transitions.append(s['state'])
        if s['state']==CONNECTED and (s['raw_buttons'] not in (0,CROSS) or s['raw_triggers']!=[0,0] or
                                     any(not 120<=v<=136 for v in s['raw_axes'])):
            raise ValueError('Unexpected guest control outside the Cross-only hotplug plan')
    if transitions!=[CONNECTED,DISCONNECTED,CONNECTED]: raise ValueError('Missing/repeated guest disconnect/reconnect transition')
    opened=[r for r in native if r['event']=='hotplug_opened']
    removed=[r for r in native if r['event']=='hotplug_removed']
    if len(opened)!=2 or len(removed)!=1: raise ValueError('Exactly one actual removal/new-device cycle required')
    for i,r in enumerate(opened):
        if (r['episode']!=i or r['connection']!='wired' or r['virtual'] is not False or r['sole'] is not True or
                (r['vendor'],r['product'],r['real_type'])!=(1356,3302,6) or
                any(type(r[k]) is not int or r[k]<=0 for k in ('qpc','qpc_frequency','instance_id')) or
                (i==1 and (type(r['sdl_timestamp_ns']) is not int or r['sdl_timestamp_ns']<=0))):
            raise ValueError('Sole wired nonvirtual DualSense episode not verified')
    frequency=opened[0]['qpc_frequency']
    if (opened[1]['qpc_frequency']!=frequency or opened[0]['instance_id']==opened[1]['instance_id'] or
            removed[0]['instance_id']!=opened[0]['instance_id'] or removed[0]['episode']!=0 or
            not opened[0]['qpc']<removed[0]['qpc']<opened[1]['qpc']):
        raise ValueError('Invalid removal/reconnection instance identity or ordering')
    if len(phases)!=7: raise ValueError('Seven distinct hotplug images/stages required')
    states=[r for r in native if r['event']=='hotplug_state']
    previous_qpc=0
    for r in states:
        ep=r['episode']
        if (type(ep) is not int or ep not in (0,1) or r['instance_id']!=opened[ep]['instance_id'] or
                type(r['qpc']) is not int or r['qpc']<=previous_qpc or r['qpc']<opened[ep]['qpc'] or
                type(r['connected']) is not bool or type(r['input_valid']) is not bool):
            raise ValueError('Invalid native observation identity/clock')
        if r['connected']:
            if (not r['input_valid'] or type(r['buttons']) is not int or not 0<=r['buttons']<=0xffffffff or
                    not isinstance(r['axes'],list) or len(r['axes'])!=4 or
                    any(type(v) is not int or not -32768<=v<=32767 for v in r['axes']) or
                    (ep==0 and r['qpc']>=removed[0]['qpc'])):
                raise ValueError('Invalid connected native payload')
        elif ep!=0 or r['input_valid'] or r['buttons'] is not None or r['axes'] is not None:
            raise ValueError('Native absence was fabricated as valid input, or a second loss occurred')
        previous_qpc=r['qpc']
    if any(r['connected'] and (r['buttons'] not in (0,1) or any(abs(v)>2048 for v in r['axes'])) for r in states):
        raise ValueError('Unexpected native control outside the Cross-only plan')
    edges=[r for r in native if r['event']=='sdl_button']
    for r in edges:
        ep=r['episode']
        if (type(ep) is not int or ep not in (0,1) or r['instance_id']!=opened[ep]['instance_id'] or
                type(r['down']) is not bool or r['qpc']<opened[ep]['qpc'] or
                (ep==0 and r['qpc']>removed[0]['qpc'])):
            raise ValueError('SDL control edge from wrong episode/device')
    if any(r['button']!=0 for r in edges) or sum(r['down'] is True for r in edges)!=2 or \
            sum(r['episode']==1 and r['down'] is False for r in edges)!=1:
        raise ValueError('Unexpected/missing separately instructed physical control edge')
    previous_sequence=-1;previous_capture=0
    for i,p in enumerate(phases):
        seq=p['sequence'];start=p['instruction_qpc_seconds'];stop=p['capture_qpc_seconds']
        if (p['index']!=i or p['label']!=PLAN[i][0] or type(seq) is not int or not previous_sequence<seq<len(samples) or
                not previous_capture<start<stop or p['pixels_verified']!=640*360): raise ValueError('Stale/missing hotplug stage')
        guest,duration=stable_suffix(samples[:seq+1],i,after=p['guest_after_observed_us']/1e6)
        sdl,seconds=stable_suffix([s for s in states if s['qpc']/frequency<=stop],i,native=True,after=start,frequency=frequency)
        if min(duration,seconds)<3 or min(len(guest),len(sdl))<20:
            raise ValueError('Missing sustained independent guest/SDL state')
        if i<2 and stop>=removed[0]['qpc']/frequency: raise ValueError('Pre-removal image is too late')
        if i==2 and not start<removed[0]['qpc']/frequency<stop<opened[1]['qpc']/frequency:
            raise ValueError('Removal preceded the explicit unplug instruction')
        if i==3 and not removed[0]['qpc']/frequency<start<stop<opened[1]['qpc']/frequency:
            raise ValueError('Disconnected stage outside actual removal interval')
        if i==4 and not start<opened[1]['qpc']/frequency<stop:
            raise ValueError('Addition preceded the explicit reconnect instruction')
        if i>4 and start<=opened[1]['qpc']/frequency: raise ValueError('Reconnect image before actual new SDL episode')
        if i in (1,5,6):
            episode=0 if i==1 else 1
            # These edges need a later human instruction/hold, never the removal-generated release.
            if not any(r['event']=='sdl_button' and r['episode']==episode and r['instance_id']==opened[episode]['instance_id'] and
                       r['button']==0 and r['down'] is (i!=6) and start<r['qpc']/frequency<=stop for r in native):
                raise ValueError('Missing separately instructed physical control edge')
            if guest[-1]['timestamp']-guest[0]['timestamp']<3000000: raise ValueError('Pad timestamp did not advance during hold')
        previous_sequence,previous_capture=seq,stop
    a,b=(samples[phases[i]['sequence']] for i in (2,3))
    if b['observed_us']-a['observed_us']<5000000 or b['audio_blocks']<=a['audio_blocks'] or b['flip']<=a['flip']:
        raise ValueError('Disconnected guest graphics/audio progress not verified')
    if any(b['observed_us']-a['observed_us']>350000 for a,b in zip(samples,samples[1:])):
        raise ValueError('Guest observation continuity gap')
    return dict(qualified_phases=7,connection_cycles=1,evidence_requirements_satisfied=True,
                scope='single USB cycle in isolated fixture; not general hotplug, PCM or acoustic qualification')
