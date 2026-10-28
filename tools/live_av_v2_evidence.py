# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
"""Independent live AV v2 journal/image evidence. No device access or input generation."""
import re
import struct

import run_homebrew_startup as startup
import videoout_evidence as video

MAX_JOURNAL_BYTES = 4 * 1024 * 1024
MAX_RECORDS = (MAX_JOURNAL_BYTES - 16) // 72
CROSS = 0x4000
HEADER = struct.pack('<8sII', b'LAV2\0\0\0\0', 2, 72)
RECORD = struct.Struct('<IiiIQQQIII16B4s')
CONNECTED, DISCONNECTED, API_ERROR, BAD_TIMESTAMP, STALE = range(1, 6)
SCALARS = ['sequence','handle','rc','audio_command','observed_us','timestamp','flip',
           'audio_blocks','raw_buttons','effective_buttons']
LINE = re.compile(r'live-av-v2: sample=(\d+) handle=(-?\d+) rc=(-?\d+) command=(\d+) '
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
                s['sequence']!=i or i>=MAX_RECORDS or not 0<s['handle']<=0x7fffffff or
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
        if not text.startswith('live-av-v2:'): continue
        if failure is not None: raise ValueError('Guest continued after hotplug failure')
        if text=='live-av-v2: begin schema=2':
            if not entered or begun: raise ValueError('Invalid hotplug begin')
            begun=True
        elif text=='live-av-v2: ready schema=2':
            if not begun or ready: raise ValueError('Invalid hotplug readiness')
            ready=True
        elif text.startswith('live-av-v2: FAIL '):
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
    if len(raw)>MAX_JOURNAL_BYTES: raise ValueError('V2 journal exceeds fixed storage budget')
    if raw!=HEADER+b''.join(map(pack_record,samples)):
        raise ValueError('Hotplug guest binary/header/reserved bytes and strict audit disagree')
    return dict(**checked,bytes_verified=len(raw),schema_version=2)


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
    if sequence>=MAX_RECORDS: raise ValueError('Hotplug image sequence out of bounds')
    return sequence


def verify_image(path,palette,sample):
    if image_sequence(path)!=sample['sequence'] or video.decode_png(path.read_bytes())!=expected_pixels(palette,sample):
        raise ValueError('Hotplug Vulkan pixels disagree with exact guest report')
    return dict(sequence=sample['sequence'],state=sample['state'],pixels_verified=640*360,sha256=startup.digest(path))



def verify_transport(transport):
    expected = dict(reason='exited', exit_code=0, active_before_cleanup=0,
        forced_termination=False, tree_cleanup=True, root_exit_verified=True,
        owner_watch_verified=True, lifetime='until_exit')
    if any(type(transport.get(k)) is not type(v) or transport[k]!=v for k,v in expected.items()):
        raise ValueError('V2 normal zero/owned/empty process exit not verified')
    if type(transport.get('root_pid')) is not int or transport['root_pid']<=0:
        raise ValueError('Missing exact root identity')


def verify_continuity(samples):
    validate_samples(samples)
    if any(b['observed_us']-a['observed_us']>350000 for a,b in zip(samples,samples[1:])):
        raise ValueError('V2 observation continuity gap')


def verify_disconnected_progress(a,b):
    if (a['state']!=DISCONNECTED or b['state']!=DISCONNECTED or
        b['observed_us']-a['observed_us']<5000000 or b['flip']<=a['flip'] or
        b['audio_blocks']<=a['audio_blocks']):
        raise ValueError('Five guest seconds of disconnected graphics/audio-block progress missing')


def expected_control(label):
    return (DISCONNECTED if label.startswith('disconnected') else CONNECTED,
        CROSS if label in ('cross','held-before-unplug','reconnected-cross') else 0)


def matches(row,label,*,native=False):
    state,buttons=expected_control(label)
    if native:
        if not row['connected']:
            return state==DISCONNECTED and row['input_valid'] is False and row['buttons'] is None and row['axes'] is None
        return (state==CONNECTED and row['input_valid'] is True and row['buttons']==int(bool(buttons)) and
            len(row['axes'])==4 and all(abs(v)<=2048 for v in row['axes']))
    return (row['state']==state and row['effective_buttons']==buttons and (state==DISCONNECTED or
        (all(120<=v<=136 for v in row['raw_axes']) and row['raw_triggers']==[0,0])))


def stable_suffix(rows,label,*,native=False,after=0,frequency=1):
    key,rate=('qpc',frequency) if native else ('observed_us',1000000)
    good=[]
    for row in reversed(rows):
        if row[key]/rate<=after or not matches(row,label,native=native):break
        if good and (good[-1][key]-row[key])/rate>.35:break
        good.append(row)
    good.reverse()
    return good,(good[-1][key]-good[0][key])/rate if len(good)>1 else 0


def verify_confirmations(events,phases,labels,close):
    import math
    previous=0
    for e in events:
        stamp=e.get('qpc_seconds')
        if type(stamp) not in (float,int) or not math.isfinite(stamp) or stamp<=0 or stamp<previous:
            raise ValueError('Invalid human confirmation clock')
        previous=stamp
    ready=[e for e in events if e['event']=='human_ready_clicked']
    if len(ready)!=1 or previous-ready[0]['qpc_seconds']>360:raise ValueError('Missing Ready or expired physical budget')
    for i,p in enumerate(phases):
        rows=[e for e in events if e['index']==i]
        usb=labels[i] in ('disconnected','reconnected-neutral')
        expected=['usb-permission','usb_action_instruction','human_action_confirmed','capture_prompt','human_f12_confirmed'] if usb else \
            ['action','human_action_confirmed','capture_prompt','human_f12_confirmed']
        if [r['event'] for r in rows]!=expected:raise ValueError('Missing/repeated/out-of-order human action')
        instruction=rows[1 if usb else 0]['qpc_seconds']
        if not ready[0]['qpc_seconds']<instruction==p['instruction_qpc_seconds']<rows[-3]['qpc_seconds']<rows[-2]['qpc_seconds']<rows[-1]['qpc_seconds']<=p['capture_qpc_seconds']:
            raise ValueError('Human action/capture not bound to exact phase')
    final=[e for e in events if e['index']==len(labels)]
    if [e['event'] for e in final]!=['close-permission','normal_close_instruction','human_close_confirmed'] or \
        final[1]['qpc_seconds']!=close['instruction_qpc_seconds'] or final[2]['qpc_seconds']!=close['confirmed_qpc_seconds']:
        raise ValueError('Human normal close not confirmed')


def verify_physical(native,samples,phases,labels,transport,close):
    """Independent v2 acceptance, never accepting an older fixture's records."""
    verify_continuity(samples);verify_transport(transport)
    recovery='reconnected-neutral' in labels
    if tuple(labels)!=(('initial-neutral','cross','release','held-before-unplug','disconnected',
        'disconnected-progress','reconnected-neutral','reconnected-cross','reconnected-release') if recovery else
        ('initial-neutral','disconnected','disconnected-progress')):
        raise ValueError('Unsupported physical acceptance plan')
    transitions=[]
    for s in samples:
        if not transitions or transitions[-1]!=s['state']:transitions.append(s['state'])
        if s['state']==CONNECTED and (s['raw_buttons'] not in (0,CROSS) or
            s['raw_triggers']!=[0,0] or any(not 120<=v<=136 for v in s['raw_axes'])):
            raise ValueError('Unexpected guest controls')
        if not recovery and s['raw_buttons'] and s['state']==CONNECTED:raise ValueError('Unrequested disconnected-close control')
    if transitions!=([CONNECTED,DISCONNECTED,CONNECTED] if recovery else [CONNECTED,DISCONNECTED]):
        raise ValueError('Wrong connection episode sequence')
    opened=[r for r in native if r['event']=='hotplug_opened'];removed=[r for r in native if r['event']=='hotplug_removed']
    if len(opened)!=(2 if recovery else 1) or len(removed)!=1 or native[-1]['event']!='stopped':
        raise ValueError('Wrong native device/removal/reconnect count or missing stop')
    f=opened[0]['qpc_frequency'];removal=removed[0]['qpc']/f
    for i,r in enumerate(opened):
        if (r['episode']!=i or r['connection']!='wired' or r['virtual'] is not False or r['sole'] is not True or
            (r['vendor'],r['product'],r['real_type'])!=(1356,3302,6) or r['qpc_frequency']!=f or
            r['instance_id']<=0 or (i and (r['instance_id']==opened[0]['instance_id'] or r['qpc']/f<=removal))):
            raise ValueError('Native wired DualSense identity/order mismatch')
    if removed[0]['episode']!=0 or removed[0]['instance_id']!=opened[0]['instance_id']:
        raise ValueError('Removal is not initial controller')
    edges=[]
    for r in native:
        if r['event'] not in ('opened','hotplug_opened','hotplug_removed','hotplug_state','sdl_button','stopped'):
            raise ValueError('Unknown native event')
        if r['event']!='sdl_button':continue
        ep=r['episode']
        if (type(ep) is not int or not 0<=ep<len(opened) or r['instance_id']!=opened[ep]['instance_id'] or
            r['button']!=0 or type(r['down']) is not bool):raise ValueError('Wrong native control/episode')
        if ep==0 and r['down'] is False and abs(r['qpc']/f-removal)<=.35:
            continue # Explicitly excluded removal-generated release; never a human edge.
        if r['qpc']<opened[ep]['qpc'] or (ep==0 and r['qpc']/f>=removal):raise ValueError('Stale native control edge')
        edges.append(r)
    if (sum(r['down'] for r in edges),sum(not r['down'] for r in edges))!=((3,2) if recovery else (0,0)):
        raise ValueError('Missing/repeated human Cross actions')
    states=[r for r in native if r['event']=='hotplug_state'];previous=0
    for r in states:
        ep=r['episode']
        if (type(ep) is not int or not 0<=ep<len(opened) or r['instance_id']!=opened[ep]['instance_id'] or
            r['qpc']<=previous or (previous and (r['qpc']-previous)/f>.35) or
            type(r['connected']) is not bool or type(r['input_valid']) is not bool):
            raise ValueError('Native identity/continuity failure')
        if r['connected']:
            if (not r['input_valid'] or r['buttons'] not in (0,1) or len(r['axes'])!=4 or
                any(abs(v)>2048 for v in r['axes']) or (ep==0 and r['qpc']/f>=removal)):
                raise ValueError('Unexpected native input or stale initial episode')
        elif r['input_valid'] or r['buttons'] is not None or r['axes'] is not None or r['qpc']/f<removal:
            raise ValueError('Fabricated native absence')
        previous=r['qpc']
    if len(phases)!=len(labels):raise ValueError('Missing distinct physical images')
    last_seq=-1;last_capture=0
    for i,p in enumerate(phases):
        seq=p['sequence'];start=p['instruction_qpc_seconds'];stop=p['capture_qpc_seconds'];label=labels[i]
        if (p['index']!=i or not last_seq<seq<len(samples) or not last_capture<start<stop or
            p['label']!=label or p['pixels_verified']!=230400):
            raise ValueError('Wrong/stale/missing phase identity')
        guest,duration=stable_suffix(samples[:seq+1],label,after=p['guest_after_observed_us']/1e6)
        sdl,seconds=stable_suffix([r for r in states if r['qpc']/f<=stop],label,native=True,after=start,frequency=f)
        if min(duration,seconds)<3 or min(len(guest),len(sdl))<20:
            raise ValueError('Three-second/20-sample independent qualification missing')
        if label=='disconnected' and not start<removal<stop:raise ValueError('Unplug before permission')
        if label=='reconnected-neutral' and not start<opened[1]['qpc']/f<stop:raise ValueError('Reconnect before permission')
        if label in ('cross','release','held-before-unplug','reconnected-cross','reconnected-release'):
            ep=int(label.startswith('reconnected'));down=label not in ('release','reconnected-release')
            if not any(r['event']=='sdl_button' and r['episode']==ep and r['instance_id']==opened[ep]['instance_id'] and
                r['button']==0 and r['down'] is down and start<r['qpc']/f<=stop and
                (ep or r['qpc']/f<removal) for r in edges):
                raise ValueError('Human control edge missing; removal release cannot substitute')
            if guest[-1]['timestamp']-guest[0]['timestamp']<3000000:raise ValueError('Pad timestamp stalled during hold')
        last_seq,last_capture=seq,stop
    a,b=(samples[phases[labels.index(label)]['sequence']] for label in ('disconnected','disconnected-progress'))
    verify_disconnected_progress(a,b)
    if recovery:
        first=next(i for i,s in enumerate(samples) if s['state']==DISCONNECTED)
        if first==0 or samples[first-1]['raw_buttons']!=CROSS or samples[first-1]['audio_command']!=1:
            raise ValueError('Held Cross before removal missing')
    if (close.get('ownership_failed') is not False or not last_capture<=close['last_owned_qpc_seconds']<=
        close['instruction_qpc_seconds']<close['root_exit_qpc_seconds']<=close['finished_qpc_seconds'] or
        close['root_exit_qpc_seconds']-close['instruction_qpc_seconds']>30 or
        close['instruction_qpc_seconds']-close['last_owned_qpc_seconds']>.35 or
        close['confirmed_qpc_seconds']<=close['instruction_qpc_seconds'] or
        close.get('root_pid')!=transport['root_pid'] or type(close.get('bound_window')) is not int or close['bound_window']<=0 or
        close.get('last_guest_observed_us')!=samples[-1]['observed_us'] or
        close['root_exit_qpc_seconds']-close['last_guest_seen_qpc_seconds']>.35 or
        states[-1]['qpc']/f<max(close['confirmed_qpc_seconds'],close['finished_qpc_seconds'])):
        raise ValueError('Premature/unowned/unconfirmed close')
    return dict(qualified_phases=len(phases),removals=1,reconnections=int(recovery),normal_exit_verified=True,
        scope='one versioned-fixture session; no general hotplug, PCM, acoustics or orderly teardown claim')
