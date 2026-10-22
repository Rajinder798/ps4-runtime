# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
"""Deterministic policy tests plus owned inert Windows Job Object regressions."""
import ctypes as C
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools'))
from boundary_cleanup_v2 import Members, WindowsJob, cleanup_owned, endpoint_coverage
INERT_WORKER = sys.argv.pop(1)


class Clock:
    def __init__(self): self.t=0.0
    def now(self): return self.t
    def pause(self, delta): self.t+=delta


class Root:
    def __init__(self,pid,clock): self.pid=pid; self.clock=clock; self.exit_at=1000
    def poll(self): return 0 if self.clock.t >= self.exit_at else None


class FakeJob:
    def __init__(self,roots,clock):
        self.roots=roots;self.clock=clock;self.unknown=False;self.child_until=0;self.released=[];self.closed=False
    def release(self,p): self.released.append(p.pid)
    def members(self):
        if self.unknown: return Members(None,None,False,5)
        pids=tuple(p.pid for p in self.roots.values() if p.poll() is None)
        if self.clock.t < self.child_until: pids+=(999,)
        return Members(len(pids),pids,True)
    def close(self): self.closed=True


class CleanupPolicyTests(unittest.TestCase):
    def setup_case(self):
        self.clock=Clock();self.roots={n:Root(i+1,self.clock) for i,n in enumerate(('pnp','sdl','endpoint'))}
        self.job=FakeJob(self.roots,self.clock);self.stops=[]
    def stop(self,name):
        self.stops.append((name,self.clock.t));self.roots[name].exit_at=min(self.roots[name].exit_at,self.clock.t+0.02)
    def run_case(self,**kw):
        return cleanup_owned(self.job,self.roots,self.stop,clock=self.clock.now,pause=self.clock.pause,timeout=0.3,**kw)
    def test_normal_close_guard_is_last_and_first_failure_survives(self):
        self.setup_case();r=self.run_case(first_failure='initial_pnp_coverage_failed')
        self.assertEqual(r['first_failure'],'initial_pnp_coverage_failed')
        self.assertTrue(r['cleanup_fully_certified']);self.assertFalse(r['job_close_may_force'])
        self.assertEqual([s[0] for s in self.stops],['pnp','sdl','endpoint'])
        self.assertTrue(r['observers_proven_exited_before_guard_stop'])
        self.assertEqual(set(r['root_exit_observed_monotonic']),set(self.roots))
        self.assertTrue(all('member_pids' in s for s in r['member_observations']))
    def test_late_child_is_waited_even_when_known_roots_exited(self):
        self.setup_case();self.job.child_until=0.12;r=self.run_case()
        self.assertGreaterEqual(self.stops[-1][1],0.12)
        self.assertTrue(r['cleanup_fully_certified'])
    def test_remaining_child_can_trigger_job_close(self):
        self.setup_case();self.job.child_until=100;r=self.run_case(first_failure='initial_pnp_coverage_failed')
        self.assertTrue(r['job_close_with_observed_members']);self.assertFalse(r['cleanup_fully_certified'])
        self.assertEqual(r['first_failure'],'initial_pnp_coverage_failed');self.assertTrue(self.job.closed)
    def test_unknown_membership_never_certified(self):
        self.setup_case();self.job.unknown=True;r=self.run_case()
        self.assertTrue(r['job_close_may_force']);self.assertFalse(r['cleanup_fully_certified'])
        self.assertFalse(r['job_empty_before_close'])
    def test_guard_dies_early_is_reported(self):
        self.setup_case();self.roots['endpoint'].exit_at=0;r=self.run_case()
        self.assertIn('guard_stopped_before_observers',r['cleanup_warnings'])
        self.assertFalse(r['cleanup_fully_certified'])
    def test_accounting_nonzero_empty_list_is_not_empty(self):
        self.assertFalse(Members(1,(),True).empty)
        self.assertFalse(Members(0,(),False).empty)
    def test_stop_request_failure_still_closes_job_and_preserves_first_failure(self):
        self.setup_case()
        def fail(_):raise OSError('synthetic stop failure')
        r=cleanup_owned(self.job,self.roots,fail,clock=self.clock.now,pause=self.clock.pause,timeout=0.1,first_failure='initial_pnp_coverage_failed')
        self.assertTrue(self.job.closed);self.assertFalse(r['cleanup_fully_certified'])
        self.assertEqual(r['first_failure'],'initial_pnp_coverage_failed')
        self.assertIn('stop_request_failed',r['cleanup_warnings'])


class EndpointTests(unittest.TestCase):
    def sample(self,t,token=0,volume=0.32,muted=True):
        return dict(time=t,default_token=token,endpoints=[dict(token=token,available=True,muted=muted,volume=volume)])
    def test_startup_shutdown_gaps_and_guard_early_stop(self):
        r=endpoint_coverage([self.sample(0.1),self.sample(0.15),self.sample(0.2)],0,0.4,guard_stop=0.21,observers_end=0.4)
        self.assertEqual(r['unobserved_or_unverified_intervals'],[[0,0.1],[0.2,0.4]])
        self.assertEqual(len(r['sample_supported_muted_intervals']),2)
        self.assertTrue(r['guard_stopped_before_observers']);self.assertFalse(r['settings_changed'])
    def test_identity_switch_and_per_identity_volume(self):
        r=endpoint_coverage([self.sample(0.1),self.sample(0.15,1,0.6),self.sample(0.2,0)],0,0.3)
        self.assertEqual(len(r['identity_change_intervals']),2)
        self.assertTrue(r['per_endpoint_volume_unchanged']);self.assertFalse(r['sample_supported_muted_intervals'])
    def test_volume_changes_unmuted_and_long_gaps_never_verified(self):
        rows=[self.sample(0.1),self.sample(0.15,volume=0.4),self.sample(0.2,muted=False),self.sample(0.9)]
        r=endpoint_coverage(rows,0,1)
        self.assertFalse(r['per_endpoint_volume_unchanged']);self.assertFalse(r['sample_supported_muted_intervals'])
    def test_clock_and_nonfinite_values_rejected(self):
        for samples in ([self.sample(0.1),self.sample(0.1)],[self.sample(float('nan'))],[self.sample(0.1,volume=float('nan'))]):
            with self.assertRaises(ValueError):endpoint_coverage(samples,0,1)


@unittest.skipUnless(os.name=='nt','Owned Windows Job Object APIs only')
class WindowsJobTests(unittest.TestCase):
    def record(self,name,result):
        folder=os.environ.get('PNP_V2_HOST_REPORT_DIR')
        if folder:
            with (Path(folder)/(name+'.json')).open('x',encoding='utf-8') as f:
                json.dump(result,f,indent=2)
    def start(self,job,folder):
        p=subprocess.Popen([INERT_WORKER,'root',str(Path(folder)/'release')],
                           stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        try: job.assign(p)
        except BaseException: p.kill();p.wait();raise
        return p
    def stop(self,p,command='stop'):
        if p.poll() is None:
            p.stdin.write(command+'\n');p.stdin.flush()
    def await_members(self,job,expected):
        end=time.monotonic()+3
        while time.monotonic()<end:
            m=job.members()
            if m.exact and set(m.pids)==set(expected): return m
            time.sleep(0.01)
        self.fail(f'Bounded job membership did not converge: expected={len(expected)}, observed={m}')
    def dispose(self,job,roots):
        job.close()
        for p in roots:
            if p._handle is not None:
                p.wait(timeout=3);job.release(p)
            for f in (p.stdin,p.stdout,p.stderr): f.close()
    def test_supported_layout_full_membership_and_normal_ordered_cleanup(self):
        with tempfile.TemporaryDirectory() as folder:
            job=WindowsJob();roots={}
            try:
                roots={n:self.start(job,folder) for n in ('pnp','sdl','endpoint')}
                m=self.await_members(job,[p.pid for p in roots.values()])
                self.assertEqual(m.active,3)
                r=cleanup_owned(job,roots,lambda n:self.stop(roots[n]),first_failure='initial_pnp_coverage_failed')
                self.assertTrue(r['cleanup_fully_certified'],r)
                self.assertEqual(r['first_failure'],'initial_pnp_coverage_failed')
                self.record('normal-job-close',r)
            finally: self.dispose(job,roots.values())
    def tree_case(self,forced):
        with tempfile.TemporaryDirectory() as folder:
            job=WindowsJob();roots=[];child_handle=None
            k=C.WinDLL('kernel32',use_last_error=True)
            k.OpenProcess.argtypes=[C.c_uint32,C.c_int,C.c_uint32];k.OpenProcess.restype=C.c_void_p
            k.WaitForSingleObject.argtypes=[C.c_void_p,C.c_uint32];k.WaitForSingleObject.restype=C.c_uint32
            k.CloseHandle.argtypes=[C.c_void_p]
            try:
                roots=[self.start(job,folder) for _ in range(3)]
                self.stop(roots[0],'tree')
                # readline is bounded by CTest and the inert child's own 15s cap.
                child_pid=int(roots[0].stdout.readline())
                child_handle=k.OpenProcess(0x100000|0x1000,False,child_pid)
                self.assertTrue(child_handle)
                for p in roots[1:]:self.stop(p)
                for p in roots:p.wait(timeout=3);job.release(p)
                m=self.await_members(job,[child_pid])
                self.assertEqual(m.active,1) # Three known roots exited; descendant remains.
                result=dict(origin='inert Windows host process regression',known_roots=3,
                            known_root_exit_codes=[p.returncode for p in roots],
                            before_close_active=m.active,before_close_member_pids=list(m.pids),
                            exact_membership=m.exact,kill_on_job_close=True)
                if forced:
                    self.assertEqual(k.WaitForSingleObject(child_handle,0),258)
                    job.close() # Last noninherited job handle; KILL_ON_JOB_CLOSE.
                    self.assertEqual(k.WaitForSingleObject(child_handle,3000),0)
                    result.update(child_running_before_close=True,child_signalled_after_job_close=True,
                                  explicit_termination=False,implicit_close_termination_verified=True)
                else:
                    (Path(folder)/'release').touch()
                    self.assertEqual(k.WaitForSingleObject(child_handle,3000),0)
                    k.CloseHandle(child_handle);child_handle=None
                    self.assertTrue(self.await_members(job,[]).empty)
                    result.update(child_normal_exit=True,job_empty_before_close=True,
                                  implicit_close_termination_verified=False)
                self.record('job-close-forced-child' if forced else 'late-child-normal-exit',result)
            finally:
                if child_handle:k.CloseHandle(child_handle)
                self.dispose(job,roots)
    def test_three_roots_exit_with_one_late_child(self):self.tree_case(False)
    def test_three_roots_exit_job_close_forces_remaining_child(self):self.tree_case(True)


if __name__=='__main__':unittest.main()
