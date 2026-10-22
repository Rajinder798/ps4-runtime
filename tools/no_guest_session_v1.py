# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
"""Future live adapter. Not imported until authorization and bundle preflight pass."""
import json
import os
from pathlib import Path
import queue
import sys
import threading
import time
from no_guest_coordinator_v1 import (ROOT,Journal,Protocol,Tail,commands,digest,endpoint_sample,
                                   marker,need,pnp,arrival,endpoint_coverage)


def analyze_endpoint(rows,frequency,start,end,cleanup):
    samples=[r for r in rows if r['event']=='sample'];converted=[];baseline={}
    for r in samples:
        points=[]
        for e in r['endpoints']:
            if e['available']:baseline.setdefault(e['token'],e['volume'])
            points.append(dict(token=e['token'],available=e['available'],muted=e['muted'] is True,
                               volume=e['volume'] if e['available'] else baseline.get(e['token'],0)))
        converted.append(dict(time=r['qpc_end']/frequency,default_token=r['default_token'],endpoints=points))
    result=endpoint_coverage(converted,start,end,guard_stop=cleanup.get('guard_shutdown_observed_at'),
                             observers_end=cleanup.get('observer_shutdown_observed_at'))
    result.update(verified_muted_observations=[dict(query_begin=r['qpc_begin']/frequency,query_end=r['qpc_end']/frequency,
                         every_available_muted=endpoint_sample(r)) for r in samples],
                  unknown_continuous_time_coverage=[[start,end]],
                  observation_semantics='Mute/volume were sampled within native QPC query brackets; sparse observations prove no continuous interval',
                  clock_anchor='native QueryPerformanceCounter / matching QueryPerformanceFrequency',
                  guard_early_during_cleanup=cleanup.get('guard_stopped_early'))
    result['per_endpoint_volume_unchanged']=result['per_endpoint_volume_unchanged'] and all(
        e['same_device_volume'] is True for r in samples for e in r['endpoints'] if e['available'])
    if cleanup.get('guard_stopped_early'):
        result['guard_stopped_before_observers']=True
        result['shutdown_order_meaning']='Guard exit was observed before observer-job emptiness was established; exact OS exit instants remain bounded by polling'
    return result


class Session:
    def __init__(self,bundle,output,api,observer_job,guard_job,*,clock=time.perf_counter,pause=time.sleep,host_test=False):
        self.bundle=bundle;self.output=output;self.api=api;self.observer_job=observer_job;self.guard_job=guard_job
        self.clock=clock;self.pause=pause;self.host_test=host_test;self.journal=Journal(output/'coordinator.jsonl',clock,host_test=host_test)
        self.protocol=Protocol(self.record,clock,host_test=host_test);self.processes={};self.tails={};self.files=[];self.launch={}
        self.paths={name:output/name for name in ('pnp','sdl','endpoint')}
        for path in self.paths.values():path.mkdir()
        self.command=commands({k:ROOT/v for k,v in bundle['executables'].items()},self.paths)
        self.closed=False;self.watchdog=None;self.guard_started=self.clock();self.observers_started=None
        self.input=queue.Queue(maxsize=4);self.record('attestation_verified',inputs=len(bundle['inputs']),source_commit=bundle['source_commit'])
        before=api.qpc();sample=clock();after=api.qpc()
        self.record('clock_anchor',qpc_before=before,perf_counter_seconds=sample,qpc_after=after,frequency=api.frequency)
    def record(self,event,**fields):self.journal.emit(event,**fields)
    def fail(self,channel,reason,original=None):self.protocol.fail(channel,reason,original)
    def start(self,name):
        need(name not in self.processes,'automatic_retry_forbidden')
        handles=[(self.paths[name]/f).open('xb') for f in ('stdout.txt','stderr.txt')];self.files.extend(handles)
        before=self.api.qpc();wall=time.time_ns()
        process=self.api.spawn(self.command[name],self.guard_job if name=='endpoint' else self.observer_job,*handles)
        self.processes[name]=process;self.launch[name]=(wall,before,self.api.qpc())
        kinds={'endpoint':['endpoint'],'pnp':['pnp'],'sdl':['sdl','strict']}[name]
        filenames={'endpoint':'endpoint.jsonl','pnp':'pnp.jsonl','sdl':'arrival.jsonl','strict':'native.jsonl'}
        for kind in kinds:self.tails[kind]=Tail(self.paths[name]/filenames[kind],kind,process.pid,self.api.frequency,host_test=self.host_test)
        self.record('observer_created',observer=name,pid=process.pid,created_suspended=True,assigned_atomically=True,
                    qpc_before=before,qpc_after=self.launch[name][2],frequency=self.api.frequency)
    def drain(self,final=False):
        streams={k:[] for k in ('pnp','sdl','strict','endpoint')}
        for kind,tail in self.tails.items():
            name='sdl' if kind=='strict' else kind
            try:
                tail.read(final=final)
                if tail.rows:
                    need(tail.rows[0]['qpc']>=self.launch[name][1] and tail.last_qpc<=self.api.qpc(),'clock_outside_owned_lifetime')
            except (ValueError,OSError,UnicodeError):
                for r in tail.rows:
                    if r['event']=='first_failure':self.fail(kind,'native_first_failure',r)
                self.fail(kind,'invalid_or_incomplete_evidence')
            streams[kind]=tail.rows
        for channel in ('pnp','sdl','endpoint'):
            for r in streams[channel]:
                if r['event']=='first_failure':self.fail(channel,'native_first_failure',r)
        return streams
    def markers(self):
        result={name:False for name in ('pnp','sdl','endpoint')}
        for name in self.processes:
            result[name]=marker(self.paths[name]/'ready',self.launch[name][0],(b'wired DualSense ready\n',b'wired DualSense ready\r\n') if name=='sdl' else b'')
        if any(t.pending for t in self.tails.values()):return dict.fromkeys(result,False)
        return result
    def stop(self,name):
        path=self.paths[name]/'stop'
        with path.open('xb') as f:f.write(b'single no-guest coordinator stop\n')
        self.record('stop_requested',observer=name)
    def emergency(self):
        # Hard backstop before 120 s even if ordinary coordination stalls.
        if not self.closed:
            try:self.fail('coordinator','hard_watchdog_containment')
            finally:
                self.api.contain(self.observer_job);self.api.contain(self.guard_job)
    def input_loop(self):
        while not self.closed:
            line=sys.stdin.readline(65)
            if not line:
                try:self.input.put_nowait('STOP')
                except queue.Full:pass
                return
            token=line.strip()
            try:self.input.put_nowait(token)
            except queue.Full:
                self.fail('coordinator','human_input_limit');return
    def collect(self):
        self.watchdog=threading.Timer(118,self.emergency);self.watchdog.daemon=True;self.watchdog.start()
        self.start('endpoint')
        if not self.host_test:
            thread=threading.Thread(target=self.input_loop,daemon=True);thread.start()
        while self.protocol.phase not in ('failed','finished'):
            streams=self.drain()
            for kind,rows in streams.items():
                if any(r['event']=='summary' for r in rows):self.fail(kind,'observer_summary_before_stop')
            for name,p in self.processes.items():
                if p.poll() is not None:self.fail(name,'observer_exited_before_stop')
                for filename in ('stdout.txt','stderr.txt'):
                    need((self.paths[name]/filename).stat().st_size<=256*1024,'observer_console_limit')
            marks=self.markers()
            if self.protocol.first:break
            if self.observers_started is None:
                ep=[r for r in streams['endpoint'] if r['event']=='sample']
                if ep and marks['endpoint']:
                    need(endpoint_sample(ep[-1]),'initial_mute_failed')
                    self.start('pnp');self.start('sdl');self.observers_started=self.clock()
                elif self.clock()-self.guard_started>5:self.fail('endpoint','guard_readiness_deadline')
            else:self.protocol.update(streams,marks,self.api.frequency)
            try:command=self.input.get_nowait()
            except queue.Empty:command=None
            if command=='STOP':self.fail('coordinator','human_stop')
            elif command is not None:self.protocol.confirm(command)
            self.pause(0.025)
    def finish(self):
        from coordinator_windows_v1 import cleanup_jobs
        cleanup={};validation={}
        try:
            self.record('cleanup_begin',original_first_failure=self.protocol.global_first)
            cleanup=cleanup_jobs(self.api,self.observer_job,self.guard_job,
                {k:v for k,v in self.processes.items() if k!='endpoint'},self.processes.get('endpoint'),
                self.stop,self.record,clock=self.clock,pause=self.pause)
            if not cleanup['fully_certified']:self.fail('cleanup','job_cleanup_not_fully_certified')
        except Exception:
            self.fail('cleanup','cleanup_exception_unknown_membership')
            cleanup=dict(fully_certified=False,membership_unknown=True,forced_containment_attempted=True,
                         observer_shutdown_established=False,guard_stopped_early=None)
            for label,job in (('observers',self.observer_job),('endpoint',self.guard_job)):
                self.record('forced_containment',job=label,membership_known=False)
                try:self.api.contain(job);job.close()
                except OSError:pass
        finally:
            for file in self.files:file.close()
        streams=self.drain(final=True)
        try:validation['pnp']=pnp.validate(streams['pnp'],allow_host_test=self.host_test,require_complete=False)
        except ValueError:self.fail('pnp','final_pnp_validation_failed')
        try:validation['sdl']=arrival.validate_native(streams['sdl'],allow_host_test=self.host_test,require_complete=False)
        except ValueError:self.fail('sdl','final_sdl_validation_failed')
        ep=streams['endpoint'];samples=[r for r in ep if r['event']=='sample']
        need(not ep or ep[0]['schema']=='endpoint-clock-v1','endpoint_schema')
        if not ep or ep[-1]['event']!='summary' or ep[-1]['status']!='passed' or ep[-1]['samples']!=len(samples):
            self.fail('endpoint','final_endpoint_validation_failed')
        for name,process in self.processes.items():
            if process.poll()!=0:self.fail(name,'nonzero_or_unknown_observer_exit')
        for name in ('pnp','sdl'):
            if name not in validation or not validation[name]['collection_complete']:self.fail(name,'incomplete_diagnostic_coverage')
        end=self.clock()
        try:coverage=analyze_endpoint(ep,self.api.frequency,self.protocol.started,end,cleanup)
        except ValueError:coverage=dict(unknown_time_coverage=True,continuous_mute_proven=False);self.fail('endpoint','coverage_analysis_failed')
        preservation=all((ROOT/name).stat().st_size==item['bytes'] and digest(ROOT/name)==item['sha256'] for name,item in self.bundle['inputs'].items())
        if not preservation:self.fail('coordinator','original_inputs_changed')
        result=dict(schema='no-guest-result-v1',origin='host-test' if self.host_test else 'human-assisted-live',
            status='boundary_observed' if self.protocol.phase=='finished' and not self.protocol.first else 'FAILED',
            first_failure=self.protocol.global_first,original_first_failures=self.protocol.first,cleanup=cleanup,
            validation=validation,endpoint_coverage=coverage,original_input_hashes_unchanged=preservation,
            duration_seconds=end-self.protocol.started,guest_sessions=0,automatic_retries=0,automatic_usb_actions=0,
            recovery_accepted=False,physical_cause_inferred=False)
        if self.host_test:result['status']='HOST_TEST_COMPLETE' if result['status']=='boundary_observed' else 'HOST_TEST_FAILED'
        self.record('summary',status=result['status'],recovery_accepted=False)
        with (self.output/'result.json').open('x',encoding='utf-8') as f:json.dump(result,f,indent=2,allow_nan=False)
        self.closed=True
        if self.watchdog:self.watchdog.cancel()
        self.journal.close()
        artifacts={p.relative_to(self.output).as_posix():dict(sha256=digest(p),bytes=p.stat().st_size)
                   for p in self.output.rglob('*') if p.is_file()}
        with (self.output/'artifact-manifest.json').open('x',encoding='utf-8') as f:
            json.dump(dict(origin=result['origin'],artifacts=artifacts,recovery_accepted=False),f,indent=2)
        return 0 if result['status'] in ('boundary_observed','HOST_TEST_COMPLETE') else 1


def run_live(bundle,output):
    # Only main() calls this after all explicit authorization flags and attestation.
    from coordinator_windows_v1 import ProcessAPI,WindowsJob
    output=Path(output).absolute();need(output.resolve()==output and output.is_relative_to(ROOT/'build') and not output.exists(),'fresh_nonaliased_build_output_required')
    need(not any((ROOT/name).is_relative_to(output) for name in bundle['inputs']),'overlapping_input_output')
    print('NO GUEST. Leave USB connected and every button untouched. Type START_NO_GUEST to initialize the authorized monitors.')
    need(input().strip()=='START_NO_GUEST','human_start_required')
    api=ProcessAPI();pins=[];observer_job=guard_job=session=None;session_lock=None
    try:
        session_lock=api.session_lock()
        for name in bundle['inputs']:pins.append(api.pin_read(ROOT/name))
        need(all(digest(ROOT/n)==v['sha256'] for n,v in bundle['inputs'].items()),'input_changed_before_start')
        output.mkdir(parents=False,exist_ok=False)
        with (output/'original-input-hashes.json').open('x',encoding='utf-8') as f:json.dump(bundle['inputs'],f,indent=2)
        observer_job=WindowsJob();guard_job=WindowsJob()
        session=Session(bundle,output,api,observer_job,guard_job)
        original_record=session.record
        def display(event,**fields):
            original_record(event,**fields)
            if event in ('confirmation_required','manual_instruction'):print(fields['instruction'],flush=True)
            if event=='returning_boundary_candidate':print('Returning boundary observed. Leave buttons untouched and wait until the original reconnect deadline.',flush=True)
        session.protocol.record=display
        try:session.collect()
        except BaseException:session.fail('coordinator','collection_exception')
        return session.finish()
    finally:
        if session and not session.closed:
            try:session.emergency()
            finally:session.closed=True
        for job in (observer_job,guard_job):
            if job and job.handle:
                try:api.contain(job);job.close()
                except OSError:pass
        for pin in reversed(pins):pin.Close()
        if session_lock:session_lock.Close()
