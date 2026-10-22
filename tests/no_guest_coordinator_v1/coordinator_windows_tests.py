# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
"""Windows host tests use only an inert worker and the guard's fake provider."""
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools'))
from coordinator_windows_v1 import ProcessAPI,WindowsJob,cleanup_jobs
from no_guest_coordinator_v1 import Tail

WORKER,GUARD=sys.argv[1:3];del sys.argv[1:3]

@unittest.skipUnless(os.name=='nt','Native Windows ownership APIs')
class OwnershipTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.folder=Path(self.tmp.name)
        self.api=ProcessAPI();self.observers=WindowsJob();self.guard_job=WindowsJob();self.processes={};self.files=[];self.events=[]
    def tearDown(self):
        for job in (self.observers,self.guard_job):
            if job.handle:self.api.contain(job);job.close()
        for p in self.processes.values():
            if p._handle is not None:
                self.api.k.WaitForSingleObject(int(p._handle),3000);p.poll();p._handle.Close()
        for f in self.files:f.close()
        self.tmp.cleanup()
    def spawn(self,name,mode='worker',hook=None):
        stdout=(self.folder/(name+'.stdout')).open('xb');stderr=(self.folder/(name+'.stderr')).open('xb');self.files.extend((stdout,stderr))
        p=self.api.spawn([WORKER,mode,self.folder/(name+'.entered'),self.folder/(name+'.stop')],
                         self.guard_job if name=='endpoint' else self.observers,stdout,stderr,before_resume=hook)
        self.processes[name]=p;return p
    def wait(self,test):
        end=time.monotonic()+3
        while time.monotonic()<end:
            if test():return
            time.sleep(.005)
        self.fail('Inert host gate deadline')
    def stop(self,name):
        (self.folder/(name+'.stop')).touch(exist_ok=False)
        self.events.append(('stop',name,time.perf_counter()))
    def record(self,event,**fields):self.events.append((event,fields,time.perf_counter()))
    def cleanup(self):
        return cleanup_jobs(self.api,self.observers,self.guard_job,
            {k:p for k,p in self.processes.items() if k!='endpoint'},self.processes.get('endpoint'),
            self.stop,self.record,clock=time.perf_counter,pause=time.sleep,timeout=3)
    def save(self,name,result):
        folder=os.environ.get('NO_GUEST_HOST_REPORT_DIR')
        if folder:
            with (Path(folder)/(name+'.json')).open('x') as f:json.dump(dict(origin='host-test',result=result,events=self.events),f,indent=2)
    def test_atomic_job_assignment_precedes_any_worker_execution(self):
        def before(p):
            self.assertFalse((self.folder/'pnp.entered').exists())
            m=self.observers.members();self.assertTrue(m.exact);self.assertIn(p.pid,m.pids)
        self.spawn('pnp',hook=before);self.spawn('endpoint')
        self.wait(lambda:(self.folder/'pnp.entered').exists())
        result=self.cleanup();self.assertTrue(result['fully_certified'],result)
        self.save('atomic-ownership',result)
    def test_complete_normal_shutdown_retains_guard_until_observer_job_empty(self):
        self.spawn('pnp');self.spawn('sdl');self.spawn('endpoint')
        result=self.cleanup();self.assertTrue(result['fully_certified'],result)
        stops=[e[1] for e in self.events if e[0]=='stop'];self.assertEqual(stops,['pnp','sdl','endpoint'])
        self.assertTrue(any(e[0]=='job_members' and e[1]['job']=='observers' and e[1]['pids']==() for e in self.events))
        self.save('normal-empty-jobs',result)
    def test_unexpected_descendant_requires_explicit_containment(self):
        p=self.spawn('pnp','tree');self.spawn('endpoint')
        self.wait(lambda:p.poll()==0 and (self.folder/'pnp.entered.child').exists())
        m=self.observers.members();self.assertTrue(m.exact);self.assertEqual(m.active,1)
        result=self.cleanup();self.assertFalse(result['fully_certified']);self.assertTrue(result['observer_forced_containment'])
        self.assertTrue(result['observer_shutdown_established']);self.save('unexpected-descendant',result)
    def test_guard_early_exit_prevents_certification(self):
        self.spawn('pnp');g=self.spawn('endpoint','exit');self.wait(lambda:g.poll()==0)
        result=self.cleanup();self.assertTrue(result['guard_stopped_early']);self.assertFalse(result['fully_certified'])
        self.save('guard-early-exit',result)
    def test_assignment_or_resume_failure_cannot_run_unowned_work(self):
        def reject(_):raise OSError('inert injected before-resume failure')
        with self.assertRaises(OSError):self.spawn('pnp',hook=reject)
        self.assertFalse((self.folder/'pnp.entered').exists())
        self.wait(lambda:self.observers.members().empty)
    def test_file_pins_deny_changes_until_released(self):
        path=self.folder/'pinned';path.write_bytes(b'original');pin=self.api.pin_read(path)
        try:
            with self.assertRaises(OSError):path.write_bytes(b'changed')
            with self.assertRaises(OSError):path.unlink()
        finally:pin.Close()
        self.assertEqual(path.read_bytes(),b'original')
    def test_clocked_guard_fake_provider_has_real_qpc_but_is_never_live_evidence(self):
        stdout=(self.folder/'guard.stdout').open('xb');stderr=(self.folder/'guard.stderr').open('xb');self.files.extend((stdout,stderr))
        report=self.folder/'endpoint.jsonl';stop=self.folder/'endpoint.stop';ready=self.folder/'endpoint.ready'
        p=self.api.spawn([GUARD,'--host-test-clock-v1',report,stop,ready,3000],self.guard_job,stdout,stderr);self.processes['endpoint']=p
        self.wait(ready.exists);stop.touch();self.wait(lambda:p.poll() is not None)
        tail=Tail(report,'endpoint',p.pid,self.api.frequency,host_test=True);tail.read(final=True)
        self.assertEqual(tail.rows[0]['origin'],'host-test');self.assertEqual(tail.rows[-1]['status'],'passed')
        self.assertTrue(all(r['qpc_begin']<=r['qpc_end']<=r['qpc'] for r in tail.rows if r['event']=='sample'))
        with self.assertRaises(ValueError):Tail(report,'endpoint',p.pid,self.api.frequency).read(final=True)
        self.guard_job.release(p);self.wait(lambda:self.guard_job.members().empty)
        self.save('clocked-guard-fake-provider',dict(rows=tail.rows,physical_evidence=False))

if __name__=='__main__':unittest.main()
