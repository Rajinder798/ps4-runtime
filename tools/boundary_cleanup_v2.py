# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
"""Host process containment and offline endpoint coverage. No device/audio APIs.

Importing does not start processes or open a job. Future coordinators must call
cleanup_owned: stop observers first, retain guard until their job members exit,
then stop guard, release waited root handles and prove job emptiness before close.
The frozen one-off v1 coordinator is deliberately not modified.
"""
from dataclasses import dataclass
import ctypes as C
import math
import os
import time


@dataclass(frozen=True)
class Members:
    active: int | None
    pids: tuple[int, ...] | None
    exact: bool
    code: int = 0

    @property
    def empty(self):
        return self.exact and self.active == 0 and self.pids == ()


class WindowsJob:
    """Owned, noninheritable KILL_ON_JOB_CLOSE job; bounded supported queries."""
    def __init__(self):
        if os.name != 'nt':
            raise OSError('Windows job adapter unavailable')
        u32 = C.c_uint32

        class Basic(C.Structure):
            _fields_ = [('user', C.c_int64), ('kernel', C.c_int64), ('flags', u32),
                        ('min_ws', C.c_size_t), ('max_ws', C.c_size_t), ('active_limit', u32),
                        ('affinity', C.c_size_t), ('priority', u32), ('scheduling', u32)]

        class Limits(C.Structure):
            _fields_ = [('basic', Basic), ('io', C.c_uint64 * 6),
                        ('process_memory', C.c_size_t), ('job_memory', C.c_size_t),
                        ('peak_process', C.c_size_t), ('peak_job', C.c_size_t)]

        class Accounting(C.Structure):
            _fields_ = [('times', C.c_int64 * 4), ('faults', u32), ('total', u32),
                        ('active', u32), ('terminated', u32)]

        self.accounting_type = Accounting
        assert C.sizeof(Accounting) == 48 and Accounting.active.offset == 40
        self.k = C.WinDLL('kernel32', use_last_error=True)
        for name, args, result in (
            ('CreateJobObjectW', [C.c_void_p, C.c_wchar_p], C.c_void_p),
            ('SetInformationJobObject', [C.c_void_p, C.c_int, C.c_void_p, u32], C.c_int),
            ('QueryInformationJobObject', [C.c_void_p, C.c_int, C.c_void_p, u32, C.POINTER(u32)], C.c_int),
            ('AssignProcessToJobObject', [C.c_void_p, C.c_void_p], C.c_int),
            ('TerminateJobObject', [C.c_void_p, u32], C.c_int),
            ('WaitForSingleObject', [C.c_void_p, u32], u32),
            ('GetExitCodeProcess', [C.c_void_p, C.POINTER(u32)], C.c_int),
            ('CloseHandle', [C.c_void_p], C.c_int)):
            f = getattr(self.k, name); f.argtypes = args; f.restype = result
        self.handle = self.k.CreateJobObjectW(None, None)
        if not self.handle:
            raise C.WinError(C.get_last_error())
        limits = Limits(); limits.basic.flags = 0x2000
        if not self.k.SetInformationJobObject(self.handle, 9, C.byref(limits), C.sizeof(limits)):
            code = C.get_last_error(); self.close(); raise C.WinError(code)

    def assign(self, process):
        # Caller must gate process work until assignment, preventing pre-job children.
        if not self.k.AssignProcessToJobObject(self.handle, int(process._handle)):
            raise C.WinError(C.get_last_error())

    def accounting(self):
        value = self.accounting_type()
        if not self.k.QueryInformationJobObject(self.handle, 1, C.byref(value), C.sizeof(value), None):
            raise C.WinError(C.get_last_error())
        return value

    def members(self):
        # Accounting/list/accounting is not atomic. Inconsistency remains unknown;
        # bounded retries may observe convergence but never reinterpret active as total.
        capacity = 16
        try:
            for _ in range(4):
                before = self.accounting()
                buffer = C.create_string_buffer(8 + capacity * C.sizeof(C.c_size_t))
                returned = C.c_uint32()
                okay = self.k.QueryInformationJobObject(self.handle, 3, buffer, len(buffer), C.byref(returned))
                assigned = C.c_uint32.from_buffer(buffer, 0).value
                count = C.c_uint32.from_buffer(buffer, 4).value
                if not okay:
                    code = C.get_last_error()
                    if code != 234:
                        return Members(None, None, False, code)
                    capacity = min(4096, max(capacity * 2, assigned))
                    continue
                if assigned > count or count > capacity or assigned > 4096:
                    capacity = min(4096, max(capacity * 2, assigned))
                    continue
                pids = tuple(C.c_size_t.from_buffer(buffer, 8 + i*C.sizeof(C.c_size_t)).value for i in range(count))
                after = self.accounting()
                if before.active == after.active == assigned == count and len(set(pids)) == count:
                    return Members(after.active, pids, True)
            return Members(None, None, False, 234)
        except OSError as error:
            return Members(None, None, False, error.winerror or 1)

    def release(self, process):
        if process.poll() is None:
            raise RuntimeError('Cannot release a running root process handle')
        # Popen.wait() leaves the Windows process handle open. Do this only after
        # returncode is recorded; no subsequent wait/query on the released handle.
        if process._handle is not None:
            process._handle.Close()
            process._handle = None

    def terminate(self):
        if not self.handle:
            return False
        if not self.k.TerminateJobObject(self.handle, 125):
            raise C.WinError(C.get_last_error())
        return True

    def release_contained(self, process):
        """Independent emergency path after job termination/close, never poll()."""
        if process._handle is None:
            return process.returncode
        state = self.k.WaitForSingleObject(int(process._handle), 250)
        if state == 258:
            raise TimeoutError('Contained root exit not yet observed')
        if state != 0:
            raise C.WinError(C.get_last_error())
        code = C.c_uint32()
        if not self.k.GetExitCodeProcess(int(process._handle), C.byref(code)):
            raise C.WinError(C.get_last_error())
        process.returncode = code.value
        process._handle.Close()
        process._handle = None
        return process.returncode

    def close(self):
        if self.handle:
            handle = self.handle
            if not self.k.CloseHandle(handle):
                raise C.WinError(C.get_last_error())
            self.handle = None


def cleanup_owned(job, roots, request_stop, *, first_failure=None, guard='endpoint',
                  timeout=3.0, clock=time.monotonic, pause=time.sleep):
    """Always close an already-owned kill-on-close job, even on bookkeeping faults.

    Exception/fail-safe paths never certify normal cleanup. Any handle whose exit
    or close cannot be established remains explicitly owned by the caller.
    """
    warnings, observations, released = [], [], set()
    exits, stops, root_exits = {}, {}, {name: None for name in roots}
    before_close = Members(None, None, False, 1)
    observers_finished = completed = close_ok = terminated = fail_safe = False
    recorded_members = iterations = 0
    last_tick = None
    operation = 'contract'

    def warn(reason):
        if reason not in warnings:
            warnings.append(reason)

    def now():
        nonlocal operation, last_tick
        operation = 'clock'
        value = clock()
        if type(value) not in (int, float) or not math.isfinite(value) or (last_tick is not None and value < last_tick):
            raise ValueError('Invalid cleanup clock')
        last_tick = value
        return value

    def poll(name):
        nonlocal operation
        if name in released:
            return root_exits[name]
        operation = 'poll'
        value = roots[name].poll()
        if value is not None:
            root_exits[name] = value
        return value

    def stop(name):
        nonlocal operation
        stops[name] = now()
        operation = 'stop_request'
        try:
            request_stop(name)
        except Exception:
            warn('stop_request_failed')

    def snapshot():
        nonlocal recorded_members, operation
        begin = now()
        operation = 'membership'
        value = job.members()
        if not isinstance(value, Members):
            raise ValueError('Invalid membership result')
        count = len(value.pids or ())
        if len(observations) < 512 and recorded_members + count <= 16384:
            observations.append(dict(monotonic_begin=begin, monotonic_end=now(), active=value.active,
                                     member_pids=None if value.pids is None else list(value.pids),
                                     member_count=None if value.pids is None else len(value.pids),
                                     exact=value.exact, code=value.code))
            recorded_members += count
        else:
            warn('membership_evidence_limit')
        return value

    def release_exited():
        nonlocal operation
        for name, process in roots.items():
            if name not in released and poll(name) is not None:
                exits.setdefault(name, now())
                operation = 'root_handle_release'
                job.release(process)
                released.add(name)

    def waiting():
        nonlocal iterations, operation
        iterations += 1
        if iterations > 2048:
            operation = 'iteration_limit'
            raise RuntimeError('Cleanup iteration cap')
        return now() < deadline

    def sleep():
        nonlocal operation
        operation = 'pause'
        pause(0.01)

    def contain():
        nonlocal terminated
        try:
            terminated = job.terminate() is True
            if not terminated:
                warn('forced_containment_unavailable')
        except Exception:
            warn('forced_containment_failed')

    try:
        if not math.isfinite(timeout) or not 0 < timeout <= 10 or guard not in roots:
            raise ValueError('Invalid cleanup contract')
        deadline = now() + timeout
        for name in roots:
            if name != guard:
                stop(name)
        while waiting():
            release_exited()
            members = snapshot()
            if poll(guard) is not None:
                warn('guard_stopped_before_observers')
            observer_roots_exited = all(poll(n) is not None for n in roots if n != guard)
            if observer_roots_exited and members.exact and set(members.pids or ()) <= {roots[guard].pid}:
                observers_finished = True
                break
            sleep()
        if not observers_finished:
            warn('observer_members_not_proven_exited')
        stop(guard)
        while waiting():
            release_exited()
            members = snapshot()
            if len(released) == len(roots) and members.empty:
                break
            sleep()
        release_exited()
        before_close = snapshot()
        for name in roots:
            poll(name)
        if not before_close.empty:
            warn('job_not_proven_empty')
        completed = True
    except Exception:
        warn(operation + '_failed')
    finally:
        # This also runs for KeyboardInterrupt/SystemExit; those propagate after
        # containment and handle accounting rather than becoming a clean result.
        fail_safe = not completed
        try:
            if fail_safe:
                contain()
        finally:
            try:
                try:
                    job.close()
                    close_ok = True
                except Exception:
                    warn('job_close_failed')
                    fail_safe = True
                    if not terminated:
                        contain()
            finally:
                # Do not call the failed poll/release/clock/pause callback again. A direct
                # kernel wait can release only a signalled root; otherwise retain/report
                # the handle for the caller, without claiming full cleanup.
                for name, process in roots.items():
                    if name not in released:
                        fail_safe = True
                        if close_ok or terminated:
                            try:
                                root_exits[name] = job.release_contained(process)
                                released.add(name)
                            except Exception:
                                warn('root_handle_cleanup_failed')
                        else:
                            warn('root_handle_cleanup_uncontained')
    return dict(schema='boundary-cleanup-v2', first_failure=first_failure if first_failure is not None else ('cleanup_not_certified' if warnings or fail_safe else None),
                known_root_exit_codes=root_exits, known_roots_exited=all(v is not None for v in root_exits.values()),
                stop_requested_monotonic=stops, root_exit_observed_monotonic=exits,
                member_observations=observations, observers_proven_exited_before_guard_stop=observers_finished,
                job_empty_before_close=before_close.empty, kill_on_close_armed=True,
                explicit_termination=terminated, job_close_may_force=not before_close.empty,
                job_close_with_observed_members=before_close.exact and bool(before_close.pids), close_ok=close_ok,
                fail_safe_used=fail_safe, unreleased_root_handles=[name for name in roots if name not in released],
                cleanup_fully_certified=completed and close_ok and before_close.empty and len(released) == len(roots) and not warnings and not fail_safe,
                cleanup_warnings=warnings)


def endpoint_coverage(samples, scope_begin, scope_end, *, max_gap=0.1, guard_stop=None,
                      observers_end=None):
    """Analyze correlated monotonic seconds; only sampled mute is established.

    No interpolation across a gap, endpoint switch, missing/unmuted endpoint or
    volume change. Original elapsed_ms-only evidence has no exact QPC anchor and
    must not be passed as though it were globally correlated.
    """
    if not all(math.isfinite(x) for x in (scope_begin,scope_end,max_gap)) or scope_end < scope_begin or max_gap <= 0:
        raise ValueError('Invalid observation scope')
    verified, changes, volume_changes, baseline, points = [], [], [], {}, []
    previous = None
    for row in samples:
        if set(row) != {'time','default_token','endpoints'} or not math.isfinite(row['time']):
            raise ValueError('Invalid correlated endpoint sample')
        t = row['time']
        if previous is not None and t <= previous['time']:
            raise ValueError('Endpoint sample clock not strictly increasing')
        tokens = set()
        safe = bool(row['endpoints'])
        volumes = {}
        for e in row['endpoints']:
            if set(e) != {'token','available','muted','volume'} or type(e['token']) is not int or e['token'] < 0 or e['token'] in tokens:
                raise ValueError('Invalid endpoint identity')
            tokens.add(e['token'])
            if type(e['available']) is not bool or type(e['muted']) is not bool:
                raise ValueError('Invalid endpoint state')
            v = e['volume']
            if type(v) not in (int,float) or not math.isfinite(v) or not 0 <= v <= 1:
                raise ValueError('Invalid endpoint volume')
            if e['available']:
                baseline.setdefault(e['token'], v)
                if abs(baseline[e['token']]-v) > 0.000001:
                    volume_changes.append(dict(time=t, token=e['token']))
                    safe = False
            safe &= e['available'] and e['muted']
            volumes[e['token']] = v
        safe &= row['default_token'] in tokens
        if previous is not None:
            identity_same = row['default_token'] == previous['default_token'] and tokens == previous['tokens']
            if not identity_same:
                changes.append(dict(begin=previous['time'],end=t))
            if safe and previous['safe'] and identity_same and t-previous['time'] <= max_gap and volumes == previous['volumes']:
                a,b=max(scope_begin,previous['time']),min(scope_end,t)
                if a < b:
                    verified.append([a,b])
        points.append(dict(time=t,muted=safe))
        previous = dict(time=t,default_token=row['default_token'],tokens=tokens,safe=safe,volumes=volumes)
    # Complement of sample-supported intervals, including startup/shutdown gaps.
    gaps=[]; at=scope_begin
    for a,b in verified:
        if a > at: gaps.append([at,a])
        at=max(at,b)
    if at < scope_end: gaps.append([at,scope_end])
    known_shutdown = guard_stop is not None and observers_end is not None
    early = guard_stop < observers_end if known_shutdown else None
    return dict(schema='endpoint-coverage-v2',sample_supported_muted_intervals=verified,
                unobserved_or_unverified_intervals=gaps,identity_change_intervals=changes,
                per_endpoint_volume_unchanged=not volume_changes,volume_changes=volume_changes,
                guard_stopped_before_observers=early,shutdown_order_observed=known_shutdown,points=points,
                continuous_mute_proven=False,settings_changed=False)
