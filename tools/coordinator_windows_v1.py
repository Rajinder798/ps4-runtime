# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
"""Windows process ownership only. No device APIs; import has no side effects."""
import ctypes as C
import os
from pathlib import Path
import subprocess
from boundary_cleanup_v2 import WindowsJob


class Handle:
    def __init__(self,k,value):self.k=k;self.value=value
    def __int__(self):return self.value
    def Close(self):
        if self.value:
            if not self.k.CloseHandle(self.value):raise C.WinError(C.get_last_error())
            self.value=None


class OwnedProcess:
    def __init__(self,k,handle,pid):self.k=k;self._handle=Handle(k,handle);self.pid=pid;self.returncode=None
    def poll(self):
        if self.returncode is None:
            state=self.k.WaitForSingleObject(int(self._handle),0)
            if state==0:
                value=C.c_uint32()
                if not self.k.GetExitCodeProcess(int(self._handle),C.byref(value)):raise C.WinError(C.get_last_error())
                self.returncode=value.value
            elif state!=258:raise C.WinError(C.get_last_error())
        return self.returncode


class ProcessAPI:
    def __init__(self):
        if os.name!='nt':raise OSError('Windows-only owned process adapter')
        self.k=C.WinDLL('kernel32',use_last_error=True)
        h=C.c_void_p;u=C.c_uint32
        class Startup(C.Structure):
            _fields_=[('cb',u),('reserved',C.c_wchar_p),('desktop',C.c_wchar_p),('title',C.c_wchar_p),
                      ('x',u),('y',u),('width',u),('height',u),('chars_x',u),('chars_y',u),
                      ('fill',u),('flags',u),('show',C.c_uint16),('reserved2_size',C.c_uint16),
                      ('reserved2',h),('stdin',h),('stdout',h),('stderr',h)]
        class Extended(C.Structure):_fields_=[('startup',Startup),('attributes',h)]
        class Information(C.Structure):_fields_=[('process',h),('thread',h),('pid',u),('tid',u)]
        self.Extended=Extended;self.Information=Information
        signatures={
            'InitializeProcThreadAttributeList':([h,u,u,C.POINTER(C.c_size_t)],C.c_int),
            'UpdateProcThreadAttribute':([h,u,C.c_size_t,h,C.c_size_t,h,h],C.c_int),
            'DeleteProcThreadAttributeList':([h],None),
            'CreateProcessW':([C.c_wchar_p,C.c_wchar_p,h,h,C.c_int,u,h,C.c_wchar_p,h,h],C.c_int),
            'ResumeThread':([h],u),'WaitForSingleObject':([h,u],u),
            'GetExitCodeProcess':([h,C.POINTER(u)],C.c_int),'CloseHandle':([h],C.c_int),
            'GetCurrentProcess':([],h),'DuplicateHandle':([h,h,h,C.POINTER(h),u,C.c_int,u],C.c_int),
            'TerminateProcess':([h,u],C.c_int),'TerminateJobObject':([h,u],C.c_int),
            'IsProcessInJob':([h,h,C.POINTER(C.c_int)],C.c_int),
            'QueryPerformanceCounter':([C.POINTER(C.c_int64)],C.c_int),
            'QueryPerformanceFrequency':([C.POINTER(C.c_int64)],C.c_int),
            'CreateFileW':([C.c_wchar_p,u,u,h,u,u,h],h)}
        signatures['CreateMutexW']=([h,C.c_int,C.c_wchar_p],h)
        for name,(args,result) in signatures.items():
            f=getattr(self.k,name);f.argtypes=args;f.restype=result
        frequency=C.c_int64()
        if not self.k.QueryPerformanceFrequency(C.byref(frequency)):raise C.WinError(C.get_last_error())
        self.frequency=frequency.value

    def qpc(self):
        value=C.c_int64()
        if not self.k.QueryPerformanceCounter(C.byref(value)):raise C.WinError(C.get_last_error())
        return value.value

    def pin_read(self,path):
        # Deny write/delete while attestations are checked and tools execute.
        value=self.k.CreateFileW(str(path),0x80000000,1,None,3,0x80,None)
        if value in (None,C.c_void_p(-1).value):raise C.WinError(C.get_last_error())
        return Handle(self.k,value)

    def spawn(self,command,job,stdout,stderr,*,before_resume=None):
        """Atomic JOB_LIST assignment plus suspended thread; only three std handles inherit.

        before_resume is an inert-test hook. Production callers never supply it.
        No shell, search-path executable resolution, broad handle inheritance or
        fallback to ordinary Popen is permitted.
        """
        import msvcrt
        executable=Path(command[0]).resolve(strict=True)
        text=subprocess.list2cmdline([str(executable),*map(str,command[1:])])
        if len(text)>=32767:raise ValueError('Command exceeds Windows limit')
        size=C.c_size_t();self.k.InitializeProcThreadAttributeList(None,2,0,C.byref(size))
        if not 0<size.value<=65536:raise OSError('Invalid attribute-list size')
        buffer=C.create_string_buffer(size.value);attributes=C.cast(buffer,C.c_void_p)
        initialized=False;handles=[];process=None;thread=None
        try:
            if not self.k.InitializeProcThreadAttributeList(attributes,2,0,C.byref(size)):raise C.WinError(C.get_last_error())
            initialized=True
            job_list=(C.c_void_p*1)(job.handle)
            if not self.k.UpdateProcThreadAttribute(attributes,0,0x2000D,job_list,C.sizeof(job_list),None,None):raise C.WinError(C.get_last_error())
            with open(os.devnull,'rb') as null:
                for file in (null,stdout,stderr):
                    duplicate=C.c_void_p();current=self.k.GetCurrentProcess()
                    if not self.k.DuplicateHandle(current,msvcrt.get_osfhandle(file.fileno()),current,C.byref(duplicate),0,True,2):raise C.WinError(C.get_last_error())
                    handles.append(Handle(self.k,duplicate.value))
            inherited=(C.c_void_p*3)(*[int(h) for h in handles])
            if not self.k.UpdateProcThreadAttribute(attributes,0,0x20002,inherited,C.sizeof(inherited),None,None):raise C.WinError(C.get_last_error())
            startup=self.Extended();startup.startup.cb=C.sizeof(startup);startup.attributes=attributes
            startup.startup.flags=0x100
            startup.startup.stdin,startup.startup.stdout,startup.startup.stderr=[int(h) for h in handles]
            info=self.Information();cmd=C.create_unicode_buffer(text)
            # EXTENDED_STARTUPINFO_PRESENT | CREATE_SUSPENDED | CREATE_NO_WINDOW.
            if not self.k.CreateProcessW(str(executable),cmd,None,None,True,0x08080004,None,
                                         str(executable.parent),C.byref(startup),C.byref(info)):
                raise C.WinError(C.get_last_error())
            process=OwnedProcess(self.k,info.process,info.pid);thread=Handle(self.k,info.thread)
            inside=C.c_int()
            if not self.k.IsProcessInJob(info.process,job.handle,C.byref(inside)) or not inside.value:
                raise OSError('Atomic job assignment not verified')
            if before_resume:before_resume(process)
            if self.k.ResumeThread(int(thread))!=1:raise OSError('Unexpected primary-thread suspend count')
            return process
        except BaseException:
            if process:
                self.k.TerminateProcess(int(process._handle),125)
                self.k.WaitForSingleObject(int(process._handle),2000)
                process.poll();process._handle.Close()
            raise
        finally:
            if thread:thread.Close()
            for handle in handles:handle.Close()
            if initialized:self.k.DeleteProcThreadAttributeList(attributes)

    def contain(self,job):
        if job.handle and not self.k.TerminateJobObject(job.handle,125):raise C.WinError(C.get_last_error())

    def session_lock(self):
        value=self.k.CreateMutexW(None,False,'Local\\PS4RuntimeNoGuestCoordinatorV1')
        if not value:raise C.WinError(C.get_last_error())
        handle=Handle(self.k,value)
        if C.get_last_error()==183:
            handle.Close();raise OSError('Another no-guest coordinator owns the session lock')
        return handle


def cleanup_jobs(api,observer_job,guard_job,observers,guard,stop,record,*,clock,pause,timeout=8):
    """Stop observer job to full emptiness, then guard job; bounded containment otherwise."""
    deadline=clock()+timeout
    results={};guard_early=False;guard_exit_at=None
    def empty_job(label,job,roots,end):
        nonlocal guard_early,guard_exit_at
        released=set();last=None
        while True:
            for name,p in roots.items():
                if name not in released and p.poll() is not None:
                    record('root_exit',observer=name,exit_code=p.returncode,observed_at=clock())
                    job.release(p);released.add(name)
            begin=clock();members=job.members()
            # Record complete supported lists, never just root exit codes.
            state=(members.active,members.pids,members.exact,members.code)
            if state!=last:
                record('job_members',job=label,active=members.active,pids=members.pids,exact=members.exact,
                       code=members.code,query_begin=begin,query_end=clock())
                last=state
            if label=='observers' and guard and guard.poll() is not None:
                guard_early=True
                if guard_exit_at is None:guard_exit_at=clock()
            if len(released)==len(roots) and members.empty:return True,members
            if clock()>=end:return False,members
            pause(0.01)
    for name in observers:stop(name)
    normal,members=empty_job('observers',observer_job,observers,deadline-2)
    results['observers_empty_before_close']=normal
    results['observer_membership_unknown']=not members.exact
    results['observer_forced_containment']=not normal
    if not normal:
        record('forced_containment',job='observers',membership_known=members.exact)
        api.contain(observer_job)
        normal_after,_=empty_job('observers',observer_job,observers,deadline-1)
        results['observers_empty_after_containment']=normal_after
    # Guard is kept until normal exit OR bounded containment has finished.
    results['observer_shutdown_established']=normal or results.get('observers_empty_after_containment',False)
    results['observer_shutdown_observed_at']=clock() if results['observer_shutdown_established'] else None
    record('job_close',job='observers',empty_proven=results['observer_shutdown_established'],may_force=not results['observer_shutdown_established'])
    observer_job.close()
    if guard:stop('endpoint')
    guard_normal,guard_members=empty_job('endpoint',guard_job,{'endpoint':guard} if guard else {},deadline)
    results.update(guard_empty_before_close=guard_normal,guard_membership_unknown=not guard_members.exact,
                   guard_forced_containment=not guard_normal,guard_stopped_early=guard_early)
    if not guard_normal:
        record('forced_containment',job='endpoint',membership_known=guard_members.exact)
        api.contain(guard_job)
        guard_after,_=empty_job('endpoint',guard_job,{'endpoint':guard} if guard else {},deadline+0.5)
        results['guard_empty_after_containment']=guard_after
    record('job_close',job='endpoint',empty_proven=guard_normal or results.get('guard_empty_after_containment',False),
           may_force=not (guard_normal or results.get('guard_empty_after_containment',False)))
    guard_job.close()
    results['guard_shutdown_observed_at']=guard_exit_at if guard_exit_at is not None else (clock() if not guard or guard.poll() is not None else None)
    results['fully_certified']=normal and guard_normal and not guard_early
    return results
