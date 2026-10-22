# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
"""Separate opt-in NO-GUEST coordinator. Import/--help/--verify never monitors devices."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import queue
import sys
import threading
import time
import pnp_coverage_v2 as pnp
import arrival_diagnostics_v1 as arrival
from boundary_cleanup_v2 import endpoint_coverage

ROOT=Path(__file__).resolve().parents[1]
SCHEMA='no-guest-coordinator-v1'
COLLECTION_SECONDS=110
RECONNECT_SECONDS=30
def synchronized(method):
    def call(self,*args,**kwargs):
        with self.lock:return method(self,*args,**kwargs)
    return call
ENDPOINT_FIELDS={'header':{'origin','qpc_frequency','process_id'},
    'sample':{'qpc_begin','qpc_end','default_token','default_changed','endpoints'},
    'first_failure':{'reason'},'summary':{'status','samples','stop_requested'}}
STRICT_FIELDS={
    'opened':set('instance_id qpc qpc_frequency connection vendor product virtual'.split()),
    'hotplug_opened':set('instance_id episode qpc qpc_frequency sdl_timestamp_ns connection vendor product real_type virtual sole'.split()),
    'hotplug_removed':set('instance_id episode qpc sdl_timestamp_ns'.split()),
    'hotplug_state':set('qpc instance_id episode connected input_valid buttons axes'.split()),
    'sdl_button':set('qpc instance_id episode sdl_timestamp_ns button down origin'.split()),
    'state':set('qpc connected buttons'.split()),'stopped':{'qpc'}}


def need(value,reason):
    if not value:raise ValueError(reason)


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for part in iter(lambda:f.read(1024*1024),b''):h.update(part)
    return h.hexdigest()


def relative_file(root,name):
    need(type(name) is str and not Path(name).is_absolute() and '..' not in Path(name).parts,'invalid_input_path')
    path=(root/name).resolve(strict=True)
    need(path.is_relative_to(root) and path.is_file(),'input_outside_repository')
    # Junctions/symlinks must not move an attested name to a different input.
    need(path==root/Path(name),'aliased_input')
    return path


def verify_bundle(path,expected,*,root=ROOT,allow_host_test=False):
    need(type(expected) is str and len(expected)==64 and digest(path)==expected,'bundle_digest_mismatch')
    raw=Path(path).read_bytes();need(len(raw)<=1024*1024,'bundle_limit')
    bundle=json.loads(raw,object_pairs_hook=arrival.unique_object,parse_constant=arrival.invalid_constant)
    need(set(bundle)=={'schema','origin','inputs','executables','guard_metadata','source_commit'},'bundle_schema')
    need(bundle['schema']=='no-guest-build-v1' and bundle['origin'] in ('host-test','offline-build'),'bundle_origin')
    need(allow_host_test or bundle['origin']=='offline-build','host_bundle_not_live')
    need(type(bundle['inputs']) is dict and 1<=len(bundle['inputs'])<=1200,'input_limit')
    for name,item in bundle['inputs'].items():
        need(type(item) is dict and set(item)=={'sha256','bytes'},'input_schema')
        p=relative_file(root,name)
        need(type(item['bytes']) is int and p.stat().st_size==item['bytes'] and digest(p)==item['sha256'],'input_hash_mismatch')
    need(set(bundle['executables'])=={'pnp','sdl','endpoint'},'executable_roles')
    need(all(p in bundle['inputs'] for p in bundle['executables'].values()),'unattested_executable')
    if not allow_host_test:
        pins=json.loads((root/'config/no-guest-coordinator-v1.json').read_text())
        need(digest(Path(sys.executable))==pins['python_sha256'],'coordinator_python_identity')
        required={'tools/no_guest_coordinator_v1.py','tools/coordinator_windows_v1.py','tools/build_no_guest_coordinator_v1.py',
                  'config/no-guest-coordinator-v1.json','tools/no_guest_session_v1.py','tests/no_guest_coordinator_v1/endpoint_clock_v1.cpp',
                  'tools/pnp_coverage_v2.py','tools/arrival_diagnostics_v1.py','tools/boundary_cleanup_v2.py'}
        need(required<=bundle['inputs'].keys(),'source_closure_missing')
        for role in ('pnp','sdl'):
            need(bundle['executables'][role]==pins[role]['path'],'incorrect_observer_version')
            for name,item in pins[role]['inputs'].items():
                need(bundle['inputs'].get(name)==item,'frozen_observer_attestation_mismatch')
        from build_arrival_probe_v1 import verify_probe
        verify_probe(root/pins['sdl']['path'],root/pins['engine'],root/pins['engine_report'])
        old=json.loads((root/pins['pnp']['build_attestation']).read_text())
        need(old['source_commit']=='25fc5f5b86f253a8ceb17166ea6214707855b80f','pnp_build_commit')
        for name,item in old['source_files'].items():
            need(hashlib.sha256((root/name).read_bytes().replace(b'\r\n',b'\n')).hexdigest()==item['lf_sha256'],'pnp_source_attestation')
        metadata=relative_file(root,bundle['guard_metadata'])
        need(bundle['guard_metadata'] in bundle['inputs'],'guard_metadata_not_pinned')
        guard=json.loads(metadata.read_text())
        need(guard['schema']=='endpoint-clock-build-v1' and guard['live_execution_performed'] is False,'guard_build_schema')
        need(guard['binary']==bundle['executables']['endpoint'] and guard['sha256']==digest(root/guard['binary']),'guard_binary_mismatch')
        need(guard['source_lf_sha256']==hashlib.sha256((root/'tests/no_guest_coordinator_v1/endpoint_clock_v1.cpp').read_bytes().replace(b'\r\n',b'\n')).hexdigest(),'guard_source_mismatch')
    return bundle


class Tail:
    """Incremental closed-schema reader. Partial final lines never count as readiness."""
    def __init__(self,path,kind,pid,frequency,*,host_test=False):
        self.path=Path(path);self.kind=kind;self.pid=pid;self.frequency=frequency;self.host_test=host_test
        self.offset=0;self.pending=b'';self.rows=[];self.last_qpc=0
        self.hasher=hashlib.sha256();self.file_id=None
        self.endpoint_baseline={};self.endpoint_previous=None;self.endpoint_count=0
        self.cap=2*1024*1024 if kind=='strict' else 8*1024*1024
    def read(self,*,final=False):
        if not self.path.exists():
            need(not final,'missing_evidence');return []
        need(self.path.is_file() and not self.path.is_symlink(),'aliased_evidence')
        stat=self.path.stat();size=stat.st_size;ident=(stat.st_dev,stat.st_ino)
        if self.file_id is None:self.file_id=ident
        need(self.file_id==ident,'replaced_evidence')
        need(self.offset<=size<=self.cap,'evidence_size_or_replacement')
        with self.path.open('rb') as f:
            f.seek(self.offset);raw=f.read(self.cap-self.offset+1);self.offset=f.tell()
        self.hasher.update(raw)
        pieces=(self.pending+raw).split(b'\n');self.pending=pieces.pop()
        need(len(self.pending)<=16384,'line_limit')
        fresh=[]
        for line in pieces:
            need(line and len(line)<=16384 and len(self.rows)<20000,'record_limit')
            row=json.loads(line,object_pairs_hook=arrival.unique_object,parse_constant=arrival.invalid_constant)
            self.check(row);self.rows.append(row);fresh.append(row)
        need(not final or not self.pending,'truncated_evidence')
        if final:need(digest(self.path)==self.hasher.hexdigest(),'rewritten_evidence_prefix')
        return fresh
    def check(self,r):
        need(type(r) is dict,'record_not_object');event=r.get('event')
        if self.kind=='strict':
            need(event in STRICT_FIELDS and set(r)==STRICT_FIELDS[event]|{'event'},'strict_native_schema')
        else:
            fields={'pnp':pnp.FIELDS,'sdl':arrival.FIELDS,'endpoint':ENDPOINT_FIELDS}[self.kind]
            schema={'pnp':pnp.SCHEMA,'sdl':arrival.SCHEMA,'endpoint':'endpoint-clock-v1'}[self.kind]
            need(event in fields and set(r)==fields[event]|{'schema','sequence','qpc','event'} and r['schema']==schema,'observer_schema')
            need(type(r['sequence']) is int and r['sequence']==len(self.rows),'observer_sequence')
            if not self.rows:
                need(event=='header' and r['origin']==('host-test' if self.host_test else 'live'),'observer_origin')
                need(r['process_id']==self.pid and r['qpc_frequency']==self.frequency,'observer_identity_or_clock')
            else:need(event!='header','repeated_header')
        need(type(r['qpc']) is int and r['qpc']>0 and r['qpc']>=self.last_qpc,'observer_clock')
        self.last_qpc=r['qpc']
        for name in ('qpc_begin','qpc_end'):
            if name in r:need(type(r[name]) is int and 0<r[name]<=r['qpc'],'query_clock')
        if 'qpc_begin' in r and 'qpc_end' in r:need(r['qpc_begin']<=r['qpc_end'],'query_clock')
        if self.kind=='pnp':
            for key,value in r.items():
                if key in pnp.BOOLS:need(type(value) is bool,'pnp_boolean')
                elif key in pnp.STRINGS:need(type(value) is str,'pnp_enum')
                elif key in pnp.ARRAYS:need(type(value) is list,'pnp_array')
                else:pnp.integer(value,-1 if key in {'present','root_present','started','problem','root_started','root_problem'} else 0)
            for key in ('subreason','hardware_subreason','ancestry_property_subreason'):
                if key in r:need(r[key] in pnp.REASONS,'pnp_reason')
        if self.kind=='sdl':
            for key in ('joysticks','gamepads','devices'):
                if key in r:arrival.devices(r[key])
        if self.kind=='endpoint' and event=='sample':
            endpoint_sample(r);count=len(r['endpoints'])
            need(count in (self.endpoint_count,self.endpoint_count+1) and count>=self.endpoint_count,'endpoint_identity_history')
            if count>self.endpoint_count:need(r['default_token']==count-1,'endpoint_new_default')
            need(r['default_changed']==(self.endpoint_previous is not None and self.endpoint_previous!=r['default_token']),'endpoint_change_flag')
            for e in r['endpoints']:
                if e['available']:
                    self.endpoint_baseline.setdefault(e['token'],e['volume'])
                    need(e['same_device_volume']==(e['volume']==self.endpoint_baseline[e['token']]),'endpoint_volume_flag')
            self.endpoint_previous=r['default_token'];self.endpoint_count=count


def endpoint_sample(row):
    points=row['endpoints'];need(type(points) is list and 1<=len(points)<=4,'endpoint_count')
    need(type(row['default_changed']) is bool and type(row['default_token']) is int and row['default_token'] in range(len(points)),'endpoint_default')
    for i,e in enumerate(points):
        need(type(e) is dict and set(e)=={'token','available','device_state','muted','volume','same_device_volume'} and type(e['token']) is int and e['token']==i,'endpoint_schema')
        need(type(e['available']) is bool and type(e['device_state']) is int,'endpoint_state')
        if e['available']:
            need(e['device_state']==1 and type(e['muted']) is bool and type(e['same_device_volume']) is bool,'endpoint_state')
            need(type(e['volume']) in (int,float) and math.isfinite(e['volume']) and 0<=e['volume']<=1,'endpoint_volume')
        else:need(e['muted'] is e['volume'] is e['same_device_volume'] is None and e['device_state']!=1,'endpoint_unavailable')
    return all(not e['available'] or (e['muted'] and e['same_device_volume']) for e in points) and points[row['default_token']]['available']


def marker(path,launched_ns,content):
    path=Path(path)
    if not path.exists():return False
    need(path.is_file() and not path.is_symlink() and path.stat().st_mtime_ns>=launched_ns,'stale_readiness_marker')
    allowed=content if isinstance(content,tuple) else (content,)
    need(path.stat().st_size<=64 and path.read_bytes() in allowed,'invalid_readiness_marker')
    return True


def pnp_ready(rows):
    scans=[r for r in rows if r['event']=='snapshot']
    if not scans:return False
    s=scans[-1]
    # Missing HID/unknown qualification must fail immediately, not wait for SDL.
    need(s['coverage_complete'] and s['initial_ready'] and not s['incomplete_identity_coverage'] and
         s['roots']==s['present_qualified_roots']==1 and s['multiple_present_candidates']==0 and
         s['unresolved_roots']==s['indeterminate']==s['interface_indeterminate']==0 and
         s['active_usb']>=1 and s['active_hid']>=1 and not s['ambiguous'],'initial_pnp_readiness_failed')
    nodes=[r for r in rows if r['event']=='devnode' and r['sample']==s['sample']]
    for r in nodes:
        need(r['outcome']=='intended' and r['enumerator_valid'] and r['hardware_valid'] and
             r['hardware_code']==r['enumerator_code']==r['root_hardware_code']==r['root_enumerator_code']==0 and
             r['ancestry_complete'] and r['subreason']=='none' and r['token']>0 and r['root_token']>0,'invalid_pnp_property_proof')
    need(any(r['role']=='usb_parent' and r['present']==r['root_present']==r['started']==1 and r['problem']==0 for r in nodes),'missing_present_parent')
    need(any(r['role']=='hid_child' and r['hardware']=='target_hid' and r['present']==r['root_present']==r['started']==1 and
             r['ancestry_complete'] and r['ancestry_code']==r['status_code']==r['problem']==0 for r in nodes),'missing_hid_relationship')
    need({r['interface']:r['code'] for r in rows if r['event']=='registration'}=={'usb':0,'hid':0},'pnp_registration')
    return True


def sdl_ready(rows,strict,frequency):
    if not rows:return False
    registered={r['interface']:r['code'] for r in rows if r['event']=='windows_registration'}
    need(set(registered)<= {'usb','hid'} and not any(registered.values()),'sdl_registration')
    if set(registered)!={'usb','hid'}:return False
    opens=[r for r in strict if r['event']=='hotplug_opened']
    if not opens:return False
    need(len(opens)==1,'extra_initial_open');o=opens[0]
    original=[r for r in strict if r['event']=='opened']
    need(len(original)==1 and original[0]['instance_id']==o['instance_id'] and original[0]['connection']=='wired' and
         original[0]['virtual'] is False and (original[0]['vendor'],original[0]['product'])==(1356,3302),'strict_initial_open_identity')
    need(o['episode']==0 and o['connection']=='wired' and o['virtual'] is False and o['sole'] is True and
         (o['vendor'],o['product'],o['real_type'])==(1356,3302,6) and o['qpc_frequency']==frequency,'incorrect_sdl_identity')
    inventories=[r for r in rows if r['event']=='sdl_inventory']
    if not inventories or not any(r['event']=='poll_heartbeat' for r in rows):return False
    for devices in (inventories[-1]['joysticks'],inventories[-1]['gamepads']):
        need(arrival.candidate(devices)=='candidate' and devices[0]['instance_id']==o['instance_id'],'sdl_inventory_identity')
    return any(r['event']=='sdl_open_result' and r['instance_id']==o['instance_id'] and r['ok'] is True and r['wired'] is True for r in rows) and any(r['event']=='sdl_clock_anchor' for r in rows)


class Protocol:
    """Pure human/observation state machine. No UI, subprocess or hardware actions."""
    def __init__(self,record,clock,*,host_test=False):
        self.record=record;self.clock=clock;self.host_test=host_test;self.started=clock()
        self.phase='initial';self.first={};self.global_first=None;self.reconnect_at=None;self.return_observed=False;self.phase_at=self.started;self.lock=threading.RLock()
    @synchronized
    def fail(self,channel,reason,original=None):
        if channel not in self.first:
            row=dict(channel=channel,reason=reason,original=original,observed_at=self.clock())
            self.first[channel]=row
            if self.global_first is None:self.global_first=row
            self.record('first_failure',**row)
        self.phase='failed'
    @synchronized
    def update(self,streams,markers,frequency):
        need(set(markers)=={'pnp','sdl','endpoint'} and all(type(v) is bool for v in markers.values()),'marker_contract')
        for channel in ('pnp','sdl','endpoint'):
            for r in streams[channel]:
                if r['event']=='first_failure':self.fail(channel,'native_first_failure',r)
        if self.phase in ('failed','finished'):return
        now=self.clock()
        if now-self.started>=COLLECTION_SECONDS:self.fail('coordinator','collection_deadline');return
        expired=self.reconnect_at is not None and now-self.reconnect_at>=RECONNECT_SECONDS
        if expired and not self.return_observed:
            self.fail('coordinator','reconnect_deadline');return
        if self.phase=='confirm_unplug' and now-self.phase_at>=25:
            self.fail('coordinator','unplug_confirmation_deadline');return
        if self.phase=='await_removal' and now-self.phase_at>=20:
            self.fail('coordinator','removal_observation_deadline');return
        scans=[r for r in streams['pnp'] if r['event']=='snapshot']
        beats=[r for r in streams['sdl'] if r['event']=='poll_heartbeat']
        if scans and now-scans[-1]['qpc_end']/frequency>2.35:self.fail('pnp','pnp_observation_stale');return
        if beats and now-beats[-1]['qpc']/frequency>2:self.fail('sdl','sdl_observation_stale');return
        if self.first:return
        for r in streams['strict']:
            if r['event']=='sdl_button' or (r['event'] in ('hotplug_state','state') and r['buttons']!=0):
                self.fail('sdl','button_observed',r);return
        ep=[r for r in streams['endpoint'] if r['event']=='sample']
        if ep:
            if not endpoint_sample(ep[-1]):self.fail('endpoint','mute_or_volume_failure',ep[-1]);return
            if now-ep[-1]['qpc_end']/frequency>0.25:self.fail('endpoint','guard_observation_stale');return
        if self.phase=='initial':
            if now-self.started>8:self.fail('coordinator','initial_readiness_deadline');return
            try:
                a=pnp_ready(streams['pnp'])
                b=sdl_ready(streams['sdl'],streams['strict'],frequency) if streams['sdl'] else False
            except ValueError as e:self.fail('coordinator',str(e));return
            if a and b and ep and all(markers.values()):
                self.phase='confirm_unplug';self.phase_at=now;self.record('joint_initial_ready',synthetic=self.host_test)
                self.record('confirmation_required',action='unplug',instruction='Type CONFIRM_UNPLUG to confirm. Do not touch USB until the following instruction.')
        elif self.phase=='confirm_unplug':
            try:pnp_ready(streams['pnp'])
            except ValueError as e:self.fail('pnp',str(e));return
        removed=any(r['event']=='hotplug_removed' for r in streams['strict'])
        opens=[r for r in streams['strict'] if r['event']=='hotplug_opened']
        if len(opens)>1 and self.phase!='await_reconnect':
            self.fail('coordinator','reconnect_before_confirmation');return
        if removed and self.phase in ('initial','confirm_unplug'):
            self.fail('coordinator','removal_before_confirmation');return
        if self.phase=='await_removal':
            snapshots=[r for r in streams['pnp'] if r['event']=='snapshot']
            absent=bool(snapshots and snapshots[-1]['coverage_complete'] and snapshots[-1]['presence']=='no_qualifying_node' and snapshots[-1]['roots']==0)
            disconnected=any(r['event']=='hotplug_state' and r['connected'] is False for r in streams['strict'])
            windows_removed=any(r['event']=='windows_notification' and r['action']=='removal' for r in streams['sdl'])
            if removed and disconnected and absent and windows_removed:
                self.phase='confirm_reconnect';self.reconnect_at=now
                self.record('confirmation_required',action='reconnect',deadline_at=now+30,
                            instruction='Type CONFIRM_RECONNECT to confirm. Do not reconnect until instructed. Thirty seconds starts now and is never reset.')
        if self.phase=='await_reconnect':
            opens=[r for r in streams['strict'] if r['event']=='hotplug_opened']
            if len(opens)>2:self.fail('sdl','extra_reopen');return
            if len(opens)==2:
                r=opens[1]
                need(r['episode']==1 and r['instance_id']!=opens[0]['instance_id'] and r['connection']=='wired' and r['sole'] is True and r['virtual'] is False and (r['vendor'],r['product'],r['real_type'])==(1356,3302,6),'reopen_identity')
                if pnp_ready(streams['pnp']) and any(r['event']=='windows_notification' and r['action']=='arrival' and r['qpc']/frequency>=self.reconnect_at for r in streams['sdl']):
                    if not self.return_observed:
                        self.return_observed=True;self.record('returning_boundary_candidate',synthetic=self.host_test,recovery_accepted=False)
                    if expired:
                        self.phase='finished';self.record('boundary_observed',synthetic=self.host_test,recovery_accepted=False)
    @synchronized
    def confirm(self,command):
        expected={'confirm_unplug':'CONFIRM_UNPLUG','confirm_reconnect':'CONFIRM_RECONNECT'}
        if self.phase in ('failed','finished'):return
        if expected.get(self.phase)!=command:self.fail('coordinator','confirmation_out_of_order');return
        now=self.clock()
        if now-self.started>=COLLECTION_SECONDS or self.reconnect_at is not None and now-self.reconnect_at>=30:
            self.fail('coordinator','confirmation_after_deadline');return
        if self.phase=='confirm_unplug' and now-self.phase_at>=25:
            self.fail('coordinator','unplug_confirmation_deadline');return
        action='unplug' if self.phase=='confirm_unplug' else 'reconnect'
        self.record('human_confirmation',action=action,source='explicit operator command')
        self.record('manual_instruction',action=action,synthetic=self.host_test,
                    instruction='Manually '+action+' USB exactly once now; leave every button untouched')
        self.phase='await_removal' if action=='unplug' else 'await_reconnect'
        self.phase_at=now


class Journal:
    def __init__(self,path,clock,*,host_test=False):
        self.file=Path(path).open('x',encoding='utf-8',newline='\n');self.clock=clock;self.sequence=0;self.bytes=0;self.lock=threading.RLock()
        self.emit('header',origin='host-test' if host_test else 'human-assisted-live',guest_sessions=0,collection_seconds=110,reconnect_seconds=30)
    @synchronized
    def emit(self,event,**fields):
        line=json.dumps(dict(schema=SCHEMA,sequence=self.sequence,event=event,monotonic=self.clock(),**fields),allow_nan=False,separators=(',',':'))+'\n'
        reserved=event in {'first_failure','summary','forced_containment','job_close'}
        need(self.sequence+(0 if reserved else 16)<4000 and self.bytes+len(line.encode())+(0 if reserved else 128*1024)<2*1024*1024,'coordinator_evidence_limit')
        self.file.write(line);self.file.flush();self.sequence+=1;self.bytes+=len(line.encode())
        if event=='first_failure':os.fsync(self.file.fileno())
    def close(self):self.file.close()


def commands(executables,paths):
    p,s,e=paths['pnp'],paths['sdl'],paths['endpoint']
    return {
        'pnp':[executables['pnp'],'--observe-pnp-coverage-v2',p/'pnp.jsonl',p/'stop',p/'ready',110000,'--pnp-coverage-authorized'],
        'sdl':[executables['sdl'],'--watch-arrival-v1',s/'native.jsonl',s/'stop',s/'ready',110000,s/'arrival.jsonl',
               '--disconnect-authorized','--reconnect-authorized','--arrival-diagnostics-authorized'],
        'endpoint':[executables['endpoint'],'--observe-endpoint-clock-v1',e/'endpoint.jsonl',e/'stop',e/'ready',120000,'--endpoint-monitoring-authorized']}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--verify-bundle',action='store_true');mode.add_argument('--run-no-guest-v1',action='store_true')
    parser.add_argument('--bundle',type=Path,required=True);parser.add_argument('--bundle-sha256',required=True)
    parser.add_argument('--output',type=Path)
    for name in ('physical-usb-authorized','monitoring-authorized','read-only-audio-authorized'):
        parser.add_argument('--'+name,action='store_true')
    args=parser.parse_args(argv)
    # This precedes Windows adapter imports, any job creation or live initialization.
    if args.run_no_guest_v1 and not all((args.physical_usb_authorized,args.monitoring_authorized,args.read_only_audio_authorized)):
        parser.error('All three explicit authorizations are required; nothing initialized')
    bundle=verify_bundle(args.bundle,args.bundle_sha256)
    if args.verify_bundle:
        print(json.dumps(dict(schema=SCHEMA,verified=True,live_initialized=False,inputs=len(bundle['inputs']))));return 0
    need(args.output is not None,'fresh_output_required')
    from no_guest_session_v1 import run_live
    return run_live(bundle,args.output)


if __name__=='__main__':
    try:raise SystemExit(main())
    except (ValueError,OSError):
        print('Coordinator preflight or collection failed; preserve evidence. No retry.',file=sys.stderr)
        raise SystemExit(1)
