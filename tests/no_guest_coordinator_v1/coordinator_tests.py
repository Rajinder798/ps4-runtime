# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
"""Explicitly synthetic providers. No device, SDL, audio COM, guest or USB access."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'tools'))
import no_guest_coordinator_v1 as c
from no_guest_session_v1 import Session,analyze_endpoint
from coordinator_windows_v1 import cleanup_jobs
from boundary_cleanup_v2 import Members
DRIVER=sys.argv.pop(1)


class Clock:
    def __init__(self):self.t=100.0
    def now(self):return self.t
    def pause(self,delta):self.t+=delta


def write_rows(path,rows):path.write_text(''.join(json.dumps(r,separators=(',',':'))+'\n' for r in rows),encoding='utf-8')
def device():return dict(instance_id=1,vendor=1356,product=3302,identity_redacted=False,real_type=6,virtual=False,is_gamepad=True)
def sdl_rows(frequency,pid=11,base=100):
    rows=[];step=max(10,frequency//10000)
    def add(event,**fields):
        at=int(base*frequency)+(len(rows)+1)*step
        if event in ('windows_presence','sdl_clock_anchor','sdl_inventory'):fields.update(qpc_begin=at-2,qpc_end=at-1)
        rows.append(dict(schema='arrival-v1',sequence=len(rows),qpc=at,event=event,**fields))
    add('header',origin='host-test',process_id=pid,qpc_frequency=frequency,max_bytes=8388608,max_records=20000)
    for kind in ('usb','hid'):add('windows_registration',interface=kind,code=0)
    add('windows_presence',interface='hid',tokens=[1]);add('sdl_init',ok=True)
    add('sdl_clock_anchor',sdl_ns=10);add('sdl_gamepads_query',devices=[device()])
    add('candidate_assessment',instance_id=1,reason='candidate');add('sdl_open_attempt',instance_id=1)
    add('sdl_open_result',instance_id=1,ok=True,wired=True)
    add('sdl_inventory',joysticks=[device()],gamepads=[device()]);add('poll_heartbeat')
    return rows
def strict_rows(frequency,base=100):
    at=int((base+.002)*frequency)
    return [dict(event='opened',instance_id=1,qpc=at,qpc_frequency=frequency,connection='wired',vendor=1356,product=3302,virtual=False),
            dict(event='hotplug_opened',instance_id=1,episode=0,qpc=at+1,qpc_frequency=frequency,sdl_timestamp_ns=0,connection='wired',vendor=1356,product=3302,real_type=6,virtual=False,sole=True),
            dict(event='hotplug_state',qpc=at+2,instance_id=1,episode=0,connected=True,input_valid=True,buttons=0,axes=[0]*4)]
def endpoint_rows(frequency,base=100,pid=12):
    at=int(base*frequency)
    return [dict(schema='endpoint-clock-v1',sequence=0,qpc=at,event='header',origin='host-test',qpc_frequency=frequency,process_id=pid),
            dict(schema='endpoint-clock-v1',sequence=1,qpc=at+3,event='sample',qpc_begin=at+1,qpc_end=at+2,
                 default_token=0,default_changed=False,endpoints=[dict(token=0,available=True,device_state=1,muted=True,volume=.32,same_device_volume=True)])]
def move(rows,base,pid,frequency):
    out=copy.deepcopy(rows);offset=int(base*frequency)-out[0]['qpc']
    for r in out:
        for key in ('qpc','qpc_begin','qpc_end','received_qpc'):
            if key in r:r[key]+=offset
        if r['event']=='header':r['process_id']=pid
    return out


class Contracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.fixture=Path(cls.tmp.name)/'native'
        subprocess.run([DRIVER,'--host-test',str(cls.fixture)],check=True,capture_output=True,timeout=35)
        cls.native={p.stem:c.pnp.load(p) for p in cls.fixture.glob('*.jsonl')}
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def setUp(self):
        self.clock=Clock();self.events=[];self.f=self.native['intended'][0]['qpc_frequency']
        self.protocol=c.Protocol(lambda event,**fields:self.events.append(dict(event=event,**fields)),self.clock.now,host_test=True)
        prefix=[r for r in self.native['intended'] if r['event'] not in ('queue','unregistration','stopped','cleanup','summary')]
        self.streams=dict(pnp=move(prefix,99.99,10,self.f),sdl=sdl_rows(self.f,base=99.99),strict=strict_rows(self.f,base=99.99),endpoint=endpoint_rows(self.f,99.999))
        self.markers=dict(pnp=True,sdl=True,endpoint=True)
    def update(self):self.protocol.update(self.streams,self.markers,self.f)
    def test_normal_joint_readiness_requires_both_markers_and_proof(self):
        self.update();self.assertEqual(self.protocol.phase,'confirm_unplug')
        self.assertFalse(any(r['event']=='manual_instruction' for r in self.events))
        self.protocol.confirm('CONFIRM_UNPLUG')
        self.assertEqual([r['event'] for r in self.events][-2:],['human_confirmation','manual_instruction'])
    def test_pnp_failure_before_sdl_ready_and_late_open_never_instructs(self):
        self.streams['pnp'].append(dict(event='first_failure',reason=1,qpc=100));self.streams['sdl']=[];self.streams['strict']=[]
        self.update();original=copy.deepcopy(self.protocol.global_first)
        self.streams['sdl']=sdl_rows(self.f);self.streams['strict']=strict_rows(self.f);self.update()
        self.assertEqual(self.protocol.global_first,original);self.assertEqual(self.protocol.phase,'failed')
        self.assertFalse(any(r['event']=='manual_instruction' for r in self.events))
    def test_missing_hid_and_real_unknown_coverage_stop_before_usb(self):
        for name in ('observed-installed-root','observed-unknown-hid','parent-unavailable'):
            with self.subTest(name=name):
                p=c.Protocol(lambda *_a,**_k:None,self.clock.now,host_test=True)
                streams=copy.deepcopy(self.streams);streams['pnp']=move(self.native[name],self.clock.t-.01,10,self.f)
                p.update(streams,self.markers,self.f);self.assertEqual(p.phase,'failed')
    def test_inactive_nonpresent_root_does_not_break_proven_joint_readiness(self):
        self.streams['pnp']=move(self.native['observed-with-hid'],self.clock.t-.01,10,self.f);self.update()
        self.assertEqual(self.protocol.phase,'confirm_unplug')
        self.assertEqual(next(r for r in self.streams['pnp'] if r['event']=='snapshot')['installed_inactive_roots'],1)
    def test_fixture_clock_mapping_is_independent_of_host_boot_clock_origin(self):
        for boot in (.01,1000000):
            rows=move(self.native['observed-with-hid'],boot,10,self.f)
            mapped=move(rows,self.clock.t-.01,10,self.f)
            streams=copy.deepcopy(self.streams);streams['pnp']=mapped
            protocol=c.Protocol(lambda *_a,**_k:None,self.clock.now,host_test=True)
            protocol.update(streams,self.markers,self.f)
            self.assertEqual(protocol.phase,'confirm_unplug')
    def test_marker_missing_never_authorizes_action(self):
        self.markers['sdl']=False;self.update();self.assertEqual(self.protocol.phase,'initial')
        self.clock.t+=9;self.update();self.assertEqual(self.protocol.phase,'failed')
        self.assertFalse(any(r['event']=='manual_instruction' for r in self.events))
    def test_stale_wrong_and_symlinked_markers_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'ready';p.write_bytes(b'');os.utime(p,ns=(1,1))
            with self.assertRaisesRegex(ValueError,'stale'):c.marker(p,time.time_ns(),b'')
            p.write_bytes(b'not ready')
            with self.assertRaises(ValueError):c.marker(p,0,b'')
            p.write_bytes(b'wired DualSense ready\r\n');self.assertTrue(c.marker(p,0,(b'wired DualSense ready\n',b'wired DualSense ready\r\n')))
    def test_wrong_identity_schema_origin_and_corrupt_evidence(self):
        for mutate in (lambda r:r.update(process_id=999),lambda r:r.update(schema='pnp-coverage-v1'),lambda r:r.update(origin='live'),lambda r:r.update(extra=True)):
            with tempfile.TemporaryDirectory() as t:
                row=copy.deepcopy(self.streams['pnp'][0]);mutate(row);p=Path(t)/'data';write_rows(p,[row])
                with self.assertRaises(ValueError):c.Tail(p,'pnp',10,self.f,host_test=True).read()
        with tempfile.TemporaryDirectory() as t:
            path=Path(t)/'bad';path.write_bytes(b'{broken}\n')
            with self.assertRaises(ValueError):c.Tail(path,'pnp',10,self.f,host_test=True).read()
            path.write_bytes(b'{"event":"x","event":"y"}\n')
            with self.assertRaises(ValueError):c.Tail(path,'pnp',10,self.f,host_test=True).read()
    def test_partial_record_is_not_readiness_and_final_truncation_fails(self):
        with tempfile.TemporaryDirectory() as t:
            path=Path(t)/'partial';raw=json.dumps(self.streams['pnp'][0]).encode();path.write_bytes(raw)
            tail=c.Tail(path,'pnp',10,self.f,host_test=True);self.assertEqual(tail.read(),[])
            with self.assertRaises(ValueError):tail.read(final=True)
            with path.open('ab') as f:f.write(b'\n')
            self.assertEqual(len(tail.read()),1)
    def test_rewritten_prefix_is_independently_detected_at_close(self):
        with tempfile.TemporaryDirectory() as t:
            path=Path(t)/'rows';write_rows(path,[self.streams['pnp'][0]])
            tail=c.Tail(path,'pnp',10,self.f,host_test=True);tail.read()
            original=path.read_bytes();path.write_bytes(original.replace(b'host-test',b'fake-test'))
            with self.assertRaisesRegex(ValueError,'rewritten'):tail.read(final=True)
    def test_controller_confirmation_order_and_no_automatic_retry(self):
        self.protocol.confirm('CONFIRM_UNPLUG');self.assertEqual(self.protocol.phase,'failed')
        self.protocol.confirm('CONFIRM_RECONNECT');self.assertFalse(any(r['event']=='manual_instruction' for r in self.events))
    def test_deadline_expires_without_any_usb_action(self):
        self.clock.t+=110;self.update();self.assertEqual(self.protocol.global_first['reason'],'collection_deadline')
        self.assertFalse(any(r['event']=='manual_instruction' for r in self.events))
    def removal(self):
        self.streams['pnp']=move(self.native['empty-complete'],self.clock.t-.01,10,self.f)
        self.streams['strict']+=[dict(event='hotplug_removed'),dict(event='hotplug_state',connected=False,buttons=0)]
        self.streams['sdl'].append(dict(event='windows_notification',action='removal',qpc=int(self.clock.t*self.f)))
    def test_one_cycle_and_reconnect_deadline_not_reset_by_confirmation(self):
        self.update();self.protocol.confirm('CONFIRM_UNPLUG');self.removal();self.update()
        self.assertEqual(self.protocol.phase,'confirm_reconnect');began=self.protocol.reconnect_at
        self.clock.t+=29
        self.protocol.confirm('CONFIRM_RECONNECT');self.assertEqual(self.protocol.reconnect_at,began)
        self.clock.t+=1;self.update();self.assertEqual(self.protocol.global_first['reason'],'reconnect_deadline')
        self.assertEqual(sum(r['event']=='manual_instruction' for r in self.events),2)
    def test_returning_boundary_is_host_only_and_never_guest_recovery(self):
        self.update();self.protocol.confirm('CONFIRM_UNPLUG');self.removal();self.update();self.protocol.confirm('CONFIRM_RECONNECT')
        self.streams['pnp']=move(self.native['observed-with-hid'],self.clock.t-.01,10,self.f)
        second=copy.deepcopy(self.streams['strict'][1]);second.update(episode=1,instance_id=2)
        self.streams['strict'].append(second)
        self.streams['sdl'].append(dict(event='windows_notification',action='arrival',qpc=int(self.clock.t*self.f)))
        self.update();self.assertEqual(self.protocol.phase,'await_reconnect');self.assertTrue(self.protocol.return_observed)
        self.clock.t+=30;self.streams['endpoint']=endpoint_rows(self.f,self.clock.t-.00001)
        self.streams['pnp']=move(self.native['observed-with-hid'],self.clock.t-.01,10,self.f)
        self.streams['sdl'].append(dict(event='poll_heartbeat',qpc=int(self.clock.t*self.f)))
        self.update();self.assertEqual(self.protocol.phase,'finished')
        self.assertTrue(self.events[-1]['synthetic']);self.assertFalse(self.events[-1]['recovery_accepted'])
    def test_reconnect_without_separate_confirmation_fails(self):
        self.update();self.protocol.confirm('CONFIRM_UNPLUG');self.removal();self.update()
        second=copy.deepcopy(self.streams['strict'][1]);second.update(episode=1,instance_id=2)
        self.streams['strict'].append(second);self.update()
        self.assertEqual(self.protocol.global_first['reason'],'reconnect_before_confirmation')
    def test_missing_removal_cannot_get_reconnect_instruction(self):
        self.update();self.protocol.confirm('CONFIRM_UNPLUG');self.update()
        self.assertEqual(self.protocol.phase,'await_removal')
        self.protocol.confirm('CONFIRM_RECONNECT');self.assertEqual(self.protocol.phase,'failed')
    def test_buttons_and_wrong_sdl_identity_fail(self):
        self.streams['strict'][1]['virtual']=True;self.update();self.assertEqual(self.protocol.phase,'failed')
        self.assertFalse(any(r['event']=='manual_instruction' for r in self.events))
    def test_first_failure_per_observer_and_cleanup_preserved(self):
        for channel in ('pnp','sdl','endpoint'):
            self.streams[channel].append(dict(event='first_failure',reason='original_'+channel))
        self.update();first=copy.deepcopy(self.protocol.global_first)
        self.protocol.fail('cleanup','unknown_job');self.protocol.fail('pnp','later')
        self.assertEqual(self.protocol.global_first,first)
        self.assertEqual(self.protocol.first['pnp']['original']['reason'],'original_pnp')
        self.assertEqual(set(self.protocol.first),{'pnp','sdl','endpoint','cleanup'})
    def test_unauthorized_entry_never_imports_live_adapter(self):
        import builtins
        real=builtins.__import__;calls=[]
        def spy(name,*a,**k):calls.append(name);return real(name,*a,**k)
        with patch('builtins.__import__',side_effect=spy),self.assertRaises(SystemExit):
            c.main(['--run-no-guest-v1','--bundle','missing','--bundle-sha256','0'*64])
        self.assertNotIn('no_guest_session_v1',calls);self.assertNotIn('coordinator_windows_v1',calls)
    def test_bundle_hash_identity_and_host_origin_are_strict(self):
        with tempfile.TemporaryDirectory() as t:
            # Hosted Windows can return a RUNNER~1 temp path; production ROOT is
            # canonical already. Exercise the same canonical-root contract here.
            root=Path(t).resolve();binary=root/'inert';binary.write_bytes(b'not executable')
            bundle=dict(schema='no-guest-build-v1',origin='host-test',inputs={'inert':dict(sha256=c.digest(binary),bytes=binary.stat().st_size)},
                        executables=dict(pnp='inert',sdl='inert',endpoint='inert'),guard_metadata='inert',source_commit='host')
            path=root/'bundle';path.write_text(json.dumps(bundle));h=c.digest(path)
            self.assertEqual(c.verify_bundle(path,h,root=root,allow_host_test=True)['origin'],'host-test')
            with self.assertRaises(ValueError):c.verify_bundle(path,h,root=root)
            binary.write_bytes(b'changed')
            with self.assertRaises(ValueError):c.verify_bundle(path,h,root=root,allow_host_test=True)
            with self.assertRaises(ValueError):c.verify_bundle(path,'0'*64,root=root,allow_host_test=True)
    def test_writer_reserves_first_failure_and_cleanup_capacity(self):
        with tempfile.TemporaryDirectory() as t:
            journal=c.Journal(Path(t)/'journal',self.clock.now,host_test=True)
            journal.bytes=2*1024*1024-128*1024
            with self.assertRaises(ValueError):journal.emit('ordinary_record')
            journal.emit('first_failure',reason='original');journal.emit('forced_containment',job='observers')
            journal.emit('summary',status='HOST_TEST_FAILED');journal.close()
    def test_endpoint_gaps_switch_volume_and_shutdown_order(self):
        rows=endpoint_rows(self.f,100);r=copy.deepcopy(rows[-1]);r.update(qpc=int(100.1*self.f),qpc_begin=int(100.099*self.f),qpc_end=int(100.1*self.f))
        rows.append(r);cleanup=dict(guard_shutdown_observed_at=100.11,observer_shutdown_observed_at=100.2,guard_stopped_early=True)
        report=analyze_endpoint(rows,self.f,99.9,100.3,cleanup)
        self.assertTrue(report['guard_stopped_before_observers']);self.assertFalse(report['continuous_mute_proven'])
        self.assertEqual(report['unknown_continuous_time_coverage'],[[99.9,100.3]])
        self.assertTrue(report['unobserved_or_unverified_intervals'])
    def session_case(self,mode):
        with tempfile.TemporaryDirectory() as t:
            out=Path(t)/'session';out.mkdir();clock=Clock();jobs=(FakeJob(),FakeJob())
            api=SessionFakeAPI(clock,jobs,self.native,mode);bundle=dict(inputs={},source_commit='host-test',executables={k:'fake-'+k+'.exe' for k in ('pnp','sdl','endpoint')})
            session=Session(bundle,out,api,*jobs,clock=clock.now,pause=api.pause,host_test=True);api.session=session
            try:session.collect()
            except Exception:session.fail('coordinator','collection_exception')
            session.finish()
            result=json.loads((out/'result.json').read_text());journal=[json.loads(x) for x in (out/'coordinator.jsonl').read_text().splitlines()]
            self.assertEqual(result['origin'],'host-test');self.assertFalse(result['recovery_accepted'])
            self.assertTrue(all(r['schema']==c.SCHEMA for r in journal))
            self.assertEqual(journal[0]['origin'],'host-test');self.assertTrue((out/'artifact-manifest.json').exists())
            return result,journal
    def test_actual_session_integration_preserves_pnp_failure_despite_late_sdl_open(self):
        r,j=self.session_case('pnp-failure-late-sdl')
        self.assertEqual(r['first_failure']['channel'],'pnp');self.assertEqual(r['first_failure']['original']['reason'],1)
        self.assertFalse(any(e['event']=='manual_instruction' for e in j))
        self.assertTrue(r['validation']['sdl']['collection_complete'])
        self.assertTrue(r['cleanup']['fully_certified'])
    def test_actual_session_joint_ready_and_normal_empty_cleanup_without_usb(self):
        r,j=self.session_case('joint-ready')
        self.assertTrue(any(e['event']=='joint_initial_ready' for e in j))
        self.assertTrue(r['cleanup']['fully_certified']);self.assertEqual(r['first_failure']['reason'],'human_stop')
        self.assertFalse(any(e['event']=='manual_instruction' for e in j))
    def test_actual_session_missing_hid_stops_without_instruction(self):
        r,j=self.session_case('missing-hid')
        self.assertEqual(r['status'],'HOST_TEST_FAILED');self.assertFalse(any(e['event']=='manual_instruction' for e in j))


class FakeRoot:
    def __init__(self,pid):self.pid=pid;self.returncode=None
    def poll(self):return self.returncode
class FakeJob:
    def __init__(self):self.roots={};self.unknown=False;self.child=False;self.closed=False
    def members(self):
        if self.unknown:return Members(None,None,False,5)
        pids=tuple(p.pid for p in self.roots.values() if p.poll() is None)+( (999,) if self.child else ())
        return Members(len(pids),pids,True)
    def release(self,p):pass
    def close(self):self.closed=True
class FakeAPI:
    def contain(self,job):
        for p in job.roots.values():p.returncode=125 if p.returncode is None else p.returncode
        job.child=False


class SessionFakeAPI(FakeAPI):
    def __init__(self,clock,jobs,native,mode):
        self.clock=clock;self.jobs=jobs;self.native=native;self.mode=mode;self.frequency=native['intended'][0]['qpc_frequency'];self.items={};self.session=None
    def qpc(self):return int(self.clock.t*self.frequency)
    def spawn(self,command,job,stdout,stderr):
        name=Path(command[0]).name.removeprefix('fake-').removesuffix('.exe');folder=Path(command[2]).parent
        p=FakeRoot(10+len(self.items));job.roots[name]=p
        base=self.clock.t+.001
        if name=='pnp':
            selected='observed-unknown-hid' if self.mode=='pnp-failure-late-sdl' else 'observed-installed-root' if self.mode=='missing-hid' else 'intended'
            full=move(self.native[selected],base,p.pid,self.frequency)
            prefix=[r for r in full if r['event'] not in ('queue','unregistration','stopped','cleanup','summary')]
            write_rows(folder/'pnp.jsonl',prefix)
            if selected=='intended':(folder/'ready').write_bytes(b'')
            self.items[name]=dict(p=p,folder=folder,full=full)
        elif name=='sdl':
            rows=sdl_rows(self.frequency,p.pid,base);strict=strict_rows(self.frequency,base)
            if self.mode=='pnp-failure-late-sdl':write_rows(folder/'arrival.jsonl',rows[:3])
            else:write_rows(folder/'arrival.jsonl',rows);write_rows(folder/'native.jsonl',strict);(folder/'ready').write_bytes(b'wired DualSense ready\r\n')
            self.items[name]=dict(p=p,folder=folder,full=rows,strict=strict)
        else:
            rows=endpoint_rows(self.frequency,base,p.pid);write_rows(folder/'endpoint.jsonl',rows);(folder/'ready').write_bytes(b'')
            self.items[name]=dict(p=p,folder=folder,full=rows)
        self.clock.t=max(self.clock.t+.01,max(r['qpc'] for r in self.items[name]['full'])/self.frequency+.002)
        return p
    def pause(self,delta):
        self.clock.pause(delta)
        for name,item in self.items.items():
            stop=item['folder']/'stop'
            if stop.exists() and item['p'].poll() is None:
                if name=='pnp':write_rows(item['folder']/'pnp.jsonl',item['full'])
                elif name=='sdl':
                    rows=copy.deepcopy(item['full'])
                    for event,fields in [('windows_unregistration',dict(interface='usb',code=0)),('windows_unregistration',dict(interface='hid',code=0)),('cleanup',dict(ok=True)),('summary',dict(status='passed',records=len(rows)+4))]:
                        rows.append(dict(schema='arrival-v1',sequence=len(rows),qpc=self.qpc(),event=event,**fields))
                    write_rows(item['folder']/'arrival.jsonl',rows)
                    write_rows(item['folder']/'native.jsonl',item['strict']+[dict(event='stopped',qpc=self.qpc())])
                else:
                    rows=item['full'];rows.append(dict(schema='endpoint-clock-v1',sequence=len(rows),qpc=self.qpc(),event='summary',status='passed',samples=len(rows)-1,stop_requested=True));write_rows(item['folder']/'endpoint.jsonl',rows)
                item['p'].returncode=0
            elif name=='endpoint' and item['p'].poll() is None:
                r=endpoint_rows(self.frequency,self.clock.t-.00001,item['p'].pid)[-1];r['sequence']=len(item['full']);item['full'].append(r);write_rows(item['folder']/'endpoint.jsonl',item['full'])
        if self.session and self.mode=='joint-ready' and self.session.protocol.phase=='confirm_unplug':
            self.session.input.put_nowait('STOP')


class CleanupIntegration(unittest.TestCase):
    def run_case(self,unknown=False,child=False,early=False):
        clock=Clock();observer=FakeJob();guard=FakeJob();observer.unknown=unknown;observer.child=child
        observer.roots={n:FakeRoot(i+1) for i,n in enumerate(('pnp','sdl'))};guard.roots={'endpoint':FakeRoot(3)}
        if early:guard.roots['endpoint'].returncode=0
        events=[]
        def stop(name):
            (guard if name=='endpoint' else observer).roots[name].returncode=0;events.append(('stop',name))
        result=cleanup_jobs(FakeAPI(),observer,guard,observer.roots,guard.roots['endpoint'],stop,
             lambda e,**f:events.append((e,f)),clock=clock.now,pause=clock.pause,timeout=3)
        return result,events
    def test_normal_empty_job_and_guard_last(self):
        r,e=self.run_case();self.assertTrue(r['fully_certified']);self.assertEqual([x[1] for x in e if x[0]=='stop'],['pnp','sdl','endpoint'])
    def test_unknown_membership_forced_containment_not_normal_close(self):
        r,e=self.run_case(unknown=True);self.assertFalse(r['fully_certified']);self.assertTrue(r['observer_membership_unknown'])
        self.assertTrue(any(x[0]=='job_close' and x[1]['may_force'] for x in e))
    def test_unexpected_descendant_not_equated_with_root_exit(self):
        r,e=self.run_case(child=True);self.assertFalse(r['fully_certified']);self.assertTrue(r['observer_forced_containment'])
        self.assertTrue(r['observer_shutdown_established'])
    def test_guard_early_exit_fails_certification(self):
        r,_=self.run_case(early=True);self.assertTrue(r['guard_stopped_early']);self.assertFalse(r['fully_certified'])

if __name__=='__main__':unittest.main()
