# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
"""Independent diagnostic evidence. Never supplies native events or guest acceptance."""
import json
import math
import time
from pathlib import Path

SCHEMA='arrival-v1'
MAX_BYTES=8*1024*1024
MAX_RECORDS=20000
RAW_TYPES={0x605:'joystick_added',0x606:'joystick_removed',0x653:'gamepad_added',
           0x654:'gamepad_removed',0x655:'gamepad_remapped'}
FIELDS={
    'header':{'origin','qpc_frequency','max_bytes','max_records','process_id'},
    'windows_registration':{'interface','code'},
    'windows_unregistration':{'interface','code'},
    'windows_notification':{'interface','action','token','received_qpc'},
    'windows_presence':{'interface','tokens','qpc_begin','qpc_end'},
    'windows_callback_error':{'code'},
    'windows_enumeration_error':{'interface','code'},
    'sdl_init':{'ok'},'sdl_clock_anchor':{'qpc_begin','sdl_ns','qpc_end'},
    'sdl_inventory':{'qpc_begin','qpc_end','joysticks','gamepads'},
    'sdl_gamepads_query':{'devices'},'candidate_assessment':{'instance_id','reason'},
    'sdl_open_attempt':{'instance_id'},'sdl_open_result':{'instance_id','ok','wired'},
    'raw_sdl_event':{'type','instance_id','sdl_timestamp_ns'},'poll_heartbeat':set(),
    'sdl_event_assessment':{'instance_id','reason'},
    'first_failure':{'reason'},'cleanup':{'ok'},'summary':{'status','records'},
    'host_callback_checks':{'passed'},
}
DEVICE={'instance_id','vendor','product','identity_redacted','real_type','virtual','is_gamepad'}
def integer(value,low=0,high=2**63-1):
    if type(value) is not int or not low<=value<=high:raise ValueError('Diagnostic integer/range mismatch')
    return value
def boolean(value):
    if type(value) is not bool:raise ValueError('Diagnostic boolean mismatch')
def seconds(value):
    if type(value) not in (float,int) or not math.isfinite(value) or value<=0:raise ValueError('Invalid QPC seconds')
    return value
def unique_object(pairs):
    result={}
    for name,value in pairs:
        if name in result:raise ValueError('Duplicate diagnostic field')
        result[name]=value
    return result
def invalid_constant(_):raise ValueError('Non-finite JSON diagnostic value')
def load(path,limit=MAX_BYTES):
    raw=Path(path).read_bytes()
    if not raw or len(raw)>limit or not raw.endswith(b'\n'):raise ValueError('Missing, truncated or oversized diagnostic evidence')
    rows=[json.loads(line,object_pairs_hook=unique_object,parse_constant=invalid_constant) for line in raw.splitlines()]
    if any(type(r) is not dict for r in rows):raise ValueError('Diagnostic record is not an object')
    if len(rows)>MAX_RECORDS:raise ValueError('Diagnostic record budget exceeded')
    if rows and rows[0].get('schema')==SCHEMA and (type(rows[0].get('max_bytes')) is not int or len(raw)>rows[0]['max_bytes']):
        raise ValueError('Declared diagnostic storage budget exceeded')
    return rows
def devices(rows):
    if type(rows) is not list or len(rows)>16:raise ValueError('Invalid SDL inventory')
    seen=set()
    for row in rows:
        if type(row) is not dict or set(row)!=DEVICE:raise ValueError('SDL identity schema mismatch')
        ident=integer(row['instance_id'],1,2**32-1)
        if ident in seen:raise ValueError('Repeated SDL instance')
        seen.add(ident)
        for k in ('virtual','identity_redacted','is_gamepad'):boolean(row[k])
        integer(row['vendor'],0,65535);integer(row['product'],0,65535)
        integer(row['real_type'],0,64)
        if (row['vendor'],row['product'])!=((0,0) if row['identity_redacted'] else (1356,3302)):
            raise ValueError('Conflicting/redacted SDL identity')
    return rows
def candidate(rows,previous=0,added=0):
    if len(rows)!=1:return 'device_count'
    d=rows[0]
    if d['virtual']:return 'virtual_device'
    if (d['vendor'],d['product'],d['real_type'])!=(1356,3302,6):return 'wrong_device'
    if d['instance_id']==previous:return 'stale_instance'
    if added and d['instance_id']!=added:return 'event_instance_mismatch'
    return 'candidate'
def validate_native(rows,*,allow_host_test=False,require_complete=True):
    if not rows or len(rows)>MAX_RECORDS:raise ValueError('Missing/bounded native diagnostics')
    previous=0;header=None;failure=[];cleanup=[];summary=[];registered={};unregistered={};attempt=None
    query=None;assessed=None;initial=0;removed=False;added=0;opened=[];raw=[];notifications=[];heartbeats=[]
    anchor=False;initialized=False;init_seen=False;pending_event=None;last_sdl_ns=0;token_kinds={};last_notice=0
    for i,r in enumerate(rows):
        if type(r) is not dict or r.get('event') not in FIELDS:raise ValueError('Unknown diagnostic record')
        event=r['event']
        if cleanup and event!='summary':raise ValueError('Record after diagnostic cleanup')
        if pending_event is not None and event!='sdl_event_assessment':raise ValueError('Missing raw SDL event assessment')
        if set(r)!=FIELDS[event]|{'schema','sequence','qpc','event'} or r['schema']!=SCHEMA or type(r['sequence']) is not int or r['sequence']!=i:
            raise ValueError('Diagnostic schema/sequence mismatch')
        stamp=integer(r['qpc'],1)
        if stamp<previous:raise ValueError('Out-of-order diagnostic clock')
        previous=stamp
        if event=='header':
            if i or r['origin'] not in ('host-test','live'):raise ValueError('Repeated/invalid diagnostic header')
            if r['origin']=='host-test' and not allow_host_test:raise ValueError('Generated host records are not hardware evidence')
            integer(r['qpc_frequency'],1);integer(r['max_bytes'],2048,MAX_BYTES);integer(r['max_records'],8,MAX_RECORDS)
            integer(r['process_id'],1,2**32-1)
            header=r
        elif header is None:raise ValueError('Missing diagnostic clock header')
        if 'interface' in r and r['interface'] not in ('usb','hid'):raise ValueError('Unsupported interface class')
        if 'interface' in r and event!='windows_registration' and r['interface'] not in registered and header['origin']!='host-test':
            raise ValueError('Windows evidence before registration')
        if event=='windows_registration':
            if r['interface'] in registered or initialized:raise ValueError('Repeated/late notification registration')
            registered[r['interface']]=integer(r['code'],0,2**32-1)
        elif event=='windows_unregistration':
            if r['interface'] in unregistered or registered.get(r['interface'])!=0:raise ValueError('Unexpected notification unregistration')
            unregistered[r['interface']]=integer(r['code'],0,2**32-1)
        elif event=='windows_notification':
            if r['action'] not in ('arrival','removal'):raise ValueError('Unsupported notification action')
            integer(r['token'],1,64)
            if integer(r['received_qpc'],1)>stamp:raise ValueError('Notification received after publication')
            if r['received_qpc']<last_notice:raise ValueError('Out-of-order Windows callback observation')
            last_notice=r['received_qpc']
            if token_kinds.setdefault(r['token'],r['interface'])!=r['interface']:raise ValueError('Conflicting Windows token identity')
            notifications.append(r)
        elif event in ('windows_presence','sdl_inventory','sdl_clock_anchor'):
            if not integer(r['qpc_begin'],1)<=integer(r['qpc_end'],1)<=stamp:raise ValueError('Diagnostic query clock reversed')
            if event=='windows_presence':
                tokens=r['tokens']
                if type(tokens) is not list or len(tokens)>64 or len(set(tokens))!=len(tokens):raise ValueError('Invalid interface tokens')
                for token in tokens:
                    integer(token,1,64)
                    if token_kinds.setdefault(token,r['interface'])!=r['interface']:raise ValueError('Conflicting interface token')
            elif event=='sdl_inventory':devices(r['joysticks']);devices(r['gamepads'])
            else:
                if anchor or not initialized:raise ValueError('Unsupported SDL clock-anchor ordering')
                integer(r['sdl_ns']);anchor=True
        elif event=='sdl_init':
            if init_seen:raise ValueError('Repeated SDL initialization')
            boolean(r['ok']);initialized=r['ok'];init_seen=True
        elif event=='raw_sdl_event':
            if not initialized or r['type'] not in RAW_TYPES:raise ValueError('Unsupported raw SDL event/order')
            integer(r['instance_id'],1,2**32-1);integer(r['sdl_timestamp_ns'])
            if r['sdl_timestamp_ns']<last_sdl_ns:raise ValueError('Out-of-order raw SDL timestamp')
            last_sdl_ns=r['sdl_timestamp_ns']
            raw.append(r)
            kind=r['type'];reason='joystick_only'
            if kind==0x653:
                reason='initial_announcement' if not removed and len(opened)==1 and r['instance_id']==initial else (
                    'enumeration_required' if removed and len(opened)==1 else 'unexpected_addition')
            elif kind==0x654:reason='selected_removal' if not removed and len(opened)==1 and r['instance_id']==initial else 'unexpected_removal'
            elif kind==0x655:reason='remap_rejected'
            pending_event=(r['instance_id'],reason)
            if r['type']==0x653:added=r['instance_id']
            if r['type']==0x654 and r['instance_id']==initial:removed=True
        elif event=='sdl_event_assessment':
            if pending_event!=(r['instance_id'],r['reason']):raise ValueError('Raw SDL classification disagreement')
            pending_event=None
        elif event=='sdl_gamepads_query':
            if not initialized:raise ValueError('SDL enumeration before initialization')
            query=devices(r['devices']);assessed=None
        elif event=='candidate_assessment':
            if query is None or assessed is not None:raise ValueError('Assessment without fresh enumeration')
            ident=query[0]['instance_id'] if len(query)==1 else 0
            if r['instance_id']!=ident or r['reason']!=candidate(query,initial if removed else 0,added):
                raise ValueError('Conflicting strict candidate diagnosis')
            assessed=r['reason']
        elif event=='sdl_open_attempt':
            if attempt is not None or assessed!='candidate' or query is None or r['instance_id']!=query[0]['instance_id']:
                raise ValueError('Unqualified/repeated SDL open attempt')
            if initial and (not removed or r['instance_id']==initial or r['instance_id']!=added):
                raise ValueError('Automatic reopen or missing fresh raw arrival')
            attempt=r['instance_id'];assessed=None
        elif event=='sdl_open_result':
            boolean(r['ok']);boolean(r['wired'])
            if r['instance_id']!=attempt or attempt is None or (r['wired'] and not r['ok']):raise ValueError('Open-result disagreement')
            if r['ok']:
                if not initial:initial=attempt
                opened.append(r)
                if len(opened)>2:raise ValueError('Repeated/extra opened controller')
            attempt=None
        elif event=='poll_heartbeat':heartbeats.append(stamp)
        elif event=='first_failure':
            if failure or type(r['reason']) is not str or not 0<len(r['reason'])<=128:raise ValueError('Invalid/replaced first failure')
            failure.append(r)
        elif event in ('windows_callback_error','windows_enumeration_error'):integer(r['code'],1,2**32-1)
        elif event=='cleanup':
            boolean(r['ok'])
            if cleanup:raise ValueError('Repeated cleanup')
            cleanup.append(r)
        elif event=='summary':
            if summary or i!=len(rows)-1 or r['records']!=len(rows) or r['status'] not in ('passed','failed'):
                raise ValueError('Incomplete/repeated diagnostic summary')
            summary.append(r)
        elif event=='host_callback_checks':
            if header['origin']!='host-test' or r['passed'] is not True:raise ValueError('Host callback record in live evidence')
    if not header or not summary or len(cleanup)!=1:raise ValueError('Truncated diagnostic lifecycle')
    if len(rows)>header['max_records'] or (attempt is not None and not failure):raise ValueError('Incomplete SDL open lifecycle')
    errors=bool(failure) or not cleanup[0]['ok'] or any(r['event'].endswith('_error') for r in rows) or any(registered.values()) or any(unregistered.values()) or init_seen and not initialized
    if summary[0]['status']!=('failed' if errors else 'passed'):raise ValueError('Diagnostic failure hidden by summary')
    heartbeat_gap=max((b-a for a,b in zip(heartbeats,heartbeats[1:])),default=0)/header['qpc_frequency']
    complete=(not errors and registered==unregistered=={'usb':0,'hid':0} and initialized and anchor and bool(heartbeats) and heartbeat_gap<=2)
    callback_host_test=header['origin']=='host-test' and any(r['event']=='host_callback_checks' for r in rows) and not initialized
    if require_complete and (summary[0]['status']!='passed' or (not callback_host_test and not complete)):
        raise ValueError('Diagnostic boundary coverage failed/incomplete')
    return dict(status=summary[0]['status'],origin=header['origin'],collection_complete=complete,
                qpc_frequency=header['qpc_frequency'],max_heartbeat_gap_seconds=heartbeat_gap,
                windows_notifications=notifications,raw_sdl_events=raw,open_results=opened,first_failure=failure,
                recovery_accepted=False)

class GuestTrace:
    """Bounded append-only witnesses of existing audit reads; not new Pad reads."""
    def __init__(self,path,*,clock=time.perf_counter,wall=time.time_ns,max_bytes=1024*1024,max_records=8192,host_test=False):
        integer(max_bytes,4096,1024*1024);integer(max_records,4,8192)
        self.path=Path(path);self.clock=clock;self.max_bytes=max_bytes;self.max_records=max_records
        self.file=self.path.open('x',encoding='utf-8');self.bytes=0;self.sequence=0;self.failed=False
        self.last_sequence=-1;self.last_control=None;self.last_witness=0;self.finished=False
        before=clock();unix=wall();after=clock()
        try:self.emit('header',qpc_begin=before,qpc_end=after,unix_ns=unix,origin='host-test' if host_test else 'live')
        except BaseException:self.file.close();raise
    def emit(self,event,**fields):
        if self.finished:raise ValueError('Guest diagnostic already finalized')
        record=dict(schema='arrival-guest-v1',sequence=self.sequence,event=event,qpc_seconds=self.clock(),**fields)
        line=json.dumps(record,allow_nan=False)+'\n';size=len(line.encode('utf-8'))
        reserved=event in ('first_failure','cleanup')
        if self.bytes+size>self.max_bytes-(0 if reserved else 2048) or self.sequence>=self.max_records-(0 if reserved else 2):
            raise ValueError('Guest diagnostic budget exhausted')
        if self.file.write(line)!=len(line):raise OSError('Incomplete guest diagnostic append')
        self.file.flush();self.bytes+=size;self.sequence+=1
    def observe(self,samples,begin,end):
        if self.failed:raise ValueError('Guest observation after first failure')
        if len(samples)<=self.last_sequence:raise ValueError('Guest diagnostic sequence regressed')
        for sample in samples[self.last_sequence+1:]:
            control=tuple(sample[k] for k in ('handle','rc','connected','state','raw_buttons','effective_buttons','audio_command'))
            if control!=self.last_control or sample is samples[-1] and end-self.last_witness>=1:
                self.emit('guest_audit_observed',read_begin_qpc=begin,read_end_qpc=end,sample=sample)
                self.last_control=control;self.last_witness=end
            self.last_sequence=sample['sequence']
    def fail(self,error):
        if not self.failed:
            self.failed=True;self.emit('first_failure',error_type=type(error).__name__,message=str(error)[:1024])
    def close(self):
        if self.finished:return
        try:self.emit('cleanup',status='failed' if self.failed else 'passed')
        finally:self.finished=True;self.file.close()

def validate_guest(rows,samples,*,allow_host_test=False):
    import live_av_v2_evidence as ev
    ev.validate_samples(samples)
    if not rows or len(rows)>8192:raise ValueError('Guest witness record budget exceeded')
    previous=0;sequence=-1;failure=0;ended=False;header=False
    for i,r in enumerate(rows):
        event=r.get('event');stamp=r.get('qpc_seconds')
        if (r.get('schema')!='arrival-guest-v1' or type(r.get('sequence')) is not int or r.get('sequence')!=i or type(stamp) not in (int,float) or
            not math.isfinite(stamp) or stamp<previous or stamp<=0 or ended):raise ValueError('Guest witness clock/schema/order mismatch')
        previous=stamp
        base={'schema','sequence','event','qpc_seconds'}
        if event=='header':
            if i or header or not seconds(r['qpc_begin'])<=seconds(r['qpc_end'])<=stamp:
                raise ValueError('Guest clock anchor invalid')
            integer(r['unix_ns'],1)
            if r['origin'] not in ('live','host-test') or r['origin']=='host-test' and not allow_host_test:
                raise ValueError('Generated guest witnesses are not hardware evidence')
            expected={'qpc_begin','qpc_end','unix_ns','origin'};header=True
        elif not header:raise ValueError('Missing guest witness header')
        elif event=='guest_audit_observed':
            expected={'read_begin_qpc','read_end_qpc','sample'}
            if not seconds(r['read_begin_qpc'])<=seconds(r['read_end_qpc'])<=stamp:raise ValueError('Audit observation bracket invalid')
            s=r['sample'];seq=s.get('sequence')
            if type(seq) is not int or not sequence<seq<len(samples) or s!=samples[seq]:raise ValueError('Guest witness not in actual audit')
            sequence=seq
        elif event=='first_failure':
            expected={'error_type','message'};failure+=1
            if failure>1 or not isinstance(r['error_type'],str) or not isinstance(r['message'],str) or len(r['message'])>1024:
                raise ValueError('First failure replaced/malformed')
        elif event=='cleanup':
            expected={'status'};ended=True
            if r['status']!=('failed' if failure else 'passed'):raise ValueError('Guest witness failure suppressed')
        else:raise ValueError('Unknown guest witness event')
        if set(r)!=base|expected:raise ValueError('Unknown guest witness fields')
    if not header or not ended or sequence<0:raise ValueError('Missing/truncated guest witness')
    return dict(status='failed' if failure else 'passed',last_witnessed_sequence=sequence,recovery_accepted=False)

def boundaries(native,guest_rows,samples,strict_rows,*,allow_host_test=False):
    """Report observed boundaries only. Strict physical acceptance remains external."""
    n=validate_native(native,require_complete=False,allow_host_test=allow_host_test)
    g=validate_guest(guest_rows,samples,allow_host_test=allow_host_test)
    if native[0]['origin']!=guest_rows[0]['origin']:raise ValueError('Mixed diagnostic evidence origins')
    removed=[r for r in strict_rows if r.get('event')=='hotplug_removed']
    opened=[r for r in strict_rows if r.get('event')=='hotplug_opened']
    if opened:
        if any(r.get('qpc_frequency')!=n['qpc_frequency'] or (r.get('vendor'),r.get('product'),r.get('real_type'))!=(1356,3302,6) or
               r.get('connection')!='wired' or r.get('virtual') is not False or r.get('sole') is not True for r in opened):
            raise ValueError('Conflicting strict/diagnostic identity or clock')
        if len(opened)!=len(n['open_results']):raise ValueError('Strict/native diagnostic open count mismatch')
        for s,d in zip(opened,n['open_results']):
            if d['instance_id']!=s['instance_id'] or not d['wired'] or d['qpc']>s['qpc']:
                raise ValueError('Strict/diagnostic open evidence disagrees')
    first_disconnected=next((i for i,s in enumerate(samples) if not s['connected']),len(samples))
    arrived=any(r['action']=='arrival' for r in n['windows_notifications'])
    recovered=any(s['connected'] for s in samples[first_disconnected:])
    raw_added=sorted(set(r['instance_id'] for r in n['raw_sdl_events'] if r['type']==0x653))
    removal_qpc=removed[0].get('qpc',0) if len(removed)==1 else 0
    returning_windows=any(r['action']=='arrival' and r['received_qpc']>removal_qpc for r in n['windows_notifications'])
    coverage=(n['collection_complete'] and g['status']=='passed' and returning_windows and
              len(opened)==2 and opened[1]['instance_id'] in raw_added and recovered)
    return dict(origin=n['origin'],diagnostic_status=n['status'],guest_witness_status=g['status'],
        windows_arrival_observed=arrived,windows_arrival_after_native_removal=returning_windows,
        raw_sdl_gamepad_added=raw_added,
        wired_sdl_open_results=[r['instance_id'] for r in n['open_results'] if r['ok'] and r['wired']],
        strict_removals=len(removed),strict_opened_episodes=len(opened),
        guest_connected_after_disconnect=recovered,boundary_coverage_complete=coverage,
        recovery_accepted=False,note='No diagnostic observation qualifies missing strict native/guest/image/close evidence')
