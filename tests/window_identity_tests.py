# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
"""Window diagnostics host tests. These never establish guest/hardware behavior."""
import ctypes as c
from ctypes import wintypes as w
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from owned_window_trace import OwnedWindowTrace
from window_identity_diagnostics import WindowIdentityDiagnostics, lifecycle_record


class IdentityTests(unittest.TestCase):
    def test_zero_or_absent_binding_cannot_install_global_hooks(self):
        for binding in ((None,123,0),(None,123,None),(None,123,-1),(None,None,456)):
            with self.assertRaisesRegex(ValueError,'nonzero verified'):
                WindowIdentityDiagnostics(binding,lambda *a,**k: None)

    def test_lifecycle_filters_nonwindow_objects_without_requiring_a_live_hwnd(self):
        # A destroyed HWND cannot reliably be queried from the asynchronous callback.
        for event in (0x8000, 0x8001, 0x8002, 0x8003, 0x800b):
            record = lifecycle_record(456, 123, event, 123, 0, 0, 789, 100)
            self.assertEqual(record['scoped_pid'], 456)
            self.assertEqual(record['event_thread_id'], 789)
            self.assertTrue(record['bound_window'])
            self.assertEqual(record['event_tick_ms'], 100)
        for arguments in ((0x8005,123,0,0), (0x8000,123,-4,0),
                          (0x8000,123,0,1), (0x8000,None,0,0)):
            self.assertIsNone(lifecycle_record(456,123,*arguments,789,100))
        self.assertFalse(lifecycle_record(456,123,0x8000,999,0,0,789,100)['bound_window'])

    def test_successful_wrong_pid_does_not_report_stale_last_error_or_rebind(self):
        class WrongOwner:
            @staticmethod
            def GetWindowThreadProcessId(window, pid):
                c.cast(pid,c.POINTER(w.DWORD)).contents.value = 999
                return 789
        state = object.__new__(OwnedWindowTrace)
        state.window, state.pid, state.user, state.diagnostics = 123,456,WrongOwner(),None
        events = []
        state.emit = lambda event,**fields: events.append(dict(event=event,**fields))
        with patch.object(c,'set_last_error',create=True), patch.object(c,'get_last_error',return_value=1400,create=True) as error:
            with self.assertRaisesRegex(RuntimeError,'identity changed'):
                state.poll()
        error.assert_not_called()
        self.assertEqual(events[0]['observed_pid'],999)
        self.assertIsNone(events[0]['win32_error'])
        self.assertEqual(state.window,123)

    def test_secondary_success_never_rescues_primary_query_failure(self):
        class Missing:
            @staticmethod
            def GetWindowThreadProcessId(window,pid): return 0
        class Secondary:
            def drain(self): pass
            def snapshot(self,reason): self.reason=reason  # Simulates a later successful query.
        state=object.__new__(OwnedWindowTrace)
        state.window,state.pid,state.user,state.diagnostics=123,456,Missing(),Secondary()
        state.emit=lambda *a,**k: None
        with patch.object(c,'set_last_error',create=True), patch.object(c,'get_last_error',return_value=1400,create=True):
            with self.assertRaisesRegex(RuntimeError,'identity changed'): state.poll()
        self.assertEqual(state.diagnostics.reason,'identity_failure_secondary_query')
        self.assertEqual(state.window,123)

    def test_broken_secondary_diagnostic_preserves_the_primary_guard(self):
        class Missing:
            @staticmethod
            def GetWindowThreadProcessId(window,pid): return 0
        class Secondary:
            def drain(self): pass
            def snapshot(self,reason): raise OSError('diagnostic unavailable')
        state=object.__new__(OwnedWindowTrace)
        state.window,state.pid,state.user,state.diagnostics=123,456,Missing(),Secondary()
        events=[]
        state.emit=lambda event,**fields: events.append(event)
        with patch.object(c,'set_last_error',create=True), patch.object(c,'get_last_error',return_value=1400,create=True):
            with self.assertRaisesRegex(RuntimeError,'identity changed'): state.poll()
        self.assertEqual(events,['owned_window_identity_failure','owned_window_secondary_diagnostic_failure'])

    def test_gui_state_query_failure_is_distinct_from_identity_loss(self):
        class User:
            @staticmethod
            def GetWindowThreadProcessId(window,pid):
                c.cast(pid,c.POINTER(w.DWORD)).contents.value=456
                return 789
            @staticmethod
            def GetGUIThreadInfo(thread,info): return 0
        class Info(c.Structure):
            _fields_=[('size',w.DWORD)]
        state=object.__new__(OwnedWindowTrace)
        state.window,state.pid,state.user,state.diagnostics,state.GuiInfo=123,456,User(),None,Info
        events=[]
        state.emit=lambda event,**fields: events.append(dict(event=event,**fields))
        with patch.object(c,'set_last_error',create=True), patch.object(c,'get_last_error',return_value=5,create=True), \
             patch.object(c,'WinError',return_value=OSError('state query denied'),create=True):
            with self.assertRaisesRegex(OSError,'state query denied'): state.poll()
        self.assertEqual(events[0]['event'],'owned_window_state_query_failure')
        self.assertEqual(events[0]['thread_id'],789)
        self.assertEqual(events[0]['win32_error'],5)

    @unittest.skipUnless(os.name=='nt','Real HWND lifecycle requires Windows')
    def test_native_destroy_replace_and_process_exit_are_distinguished(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)
            evidence=os.environ.get('PS4_WINDOW_DIAGNOSTIC_TEST_EVIDENCE')
            target=Path(evidence) if evidence else None
            if target: target.mkdir(parents=True,exist_ok=False)
            creationflags=subprocess.CREATE_NO_WINDOW
            child=subprocess.Popen([sys.executable,str(Path(__file__).with_name('window_identity_child.py')),str(out)],
                                   stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=creationflags)
            events=[]; state=None
            def emit(event,**fields): events.append(dict(event=event,**fields))
            def wait(condition):
                deadline=time.monotonic()+5
                while not condition():
                    if child.poll() is not None: self.fail('Host window child exited early: '+child.stderr.read().decode())
                    if time.monotonic()>deadline: self.fail('Host lifecycle condition timed out')
                    time.sleep(.01)
            try:
                wait(lambda:(out/'initial.json').exists() and (out/'initial.json').stat().st_size)
                info=json.loads((out/'initial.json').read_text())
                state=OwnedWindowTrace((c.WinDLL('user32',use_last_error=True),info['window'],child.pid),emit,lifecycle=True)
                # A hidden/unfocused HWND still has valid identity.
                self.assertFalse(state.poll()['foreground'])
                self.assertFalse(state.poll()['thread_focus'])
                bound=next(r for r in events if r['event']=='owned_window_identity_snapshot')
                self.assertEqual(bound['process_wait_result'],258)  # WAIT_TIMEOUT = still running.
                self.assertEqual(bound['observed_pid'],child.pid)
                self.assertGreater(bound['observed_thread'],0)
                (out/'destroy.request').touch()
                wait(lambda:(out/'destroyed.txt').exists())
                wait(lambda:(state.diagnostics.drain() or any(r.get('kind')=='destroy' for r in events)))
                with self.assertRaisesRegex(RuntimeError,'identity changed'): state.poll()
                failure=next(r for r in events if r.get('reason')=='identity_failure_secondary_query')
                self.assertFalse(failure['is_window_after_query'])
                self.assertEqual(failure['process_wait_result'],258)
                self.assertEqual(failure['query_error'],1400)
                (out/'replace.request').touch()
                wait(lambda:(out/'replacement.json').exists() and (out/'replacement.json').stat().st_size)
                replacement=json.loads((out/'replacement.json').read_text())
                wait(lambda:(state.diagnostics.drain() or any(r.get('kind')=='create' and r['window_handle']==replacement['window'] for r in events)))
                self.assertEqual(state.window,info['window'])  # No automatic rebind.
                self.assertNotEqual(replacement['window'],state.window)
                (out/'exit.request').touch()
                self.assertEqual(child.wait(timeout=5),0)
                state.diagnostics.snapshot('test_process_exited')
                exited=events[-1]
                self.assertEqual(exited['process_wait_result'],0)
                self.assertEqual(exited['process_exit_code'],0)
                self.assertEqual(exited['process_creation_filetime'],bound['process_creation_filetime'])
            finally:
                (out/'exit.request').touch()
                try: child.wait(timeout=5)
                except subprocess.TimeoutExpired: child.kill();child.wait();self.fail('Host fixture needed forced cleanup')
                finally:
                    try:
                        if state: state.close()
                    finally:
                        if target:
                            (target/'events.json').write_bytes((json.dumps(events,indent=2)+'\n').encode())
                            if (out/'child.jsonl').exists(): (target/'child.jsonl').write_bytes((out/'child.jsonl').read_bytes())
                            (target/'child-stdout.txt').write_bytes(child.stdout.read())
                            (target/'child-stderr.txt').write_bytes(child.stderr.read())
                        child.stdout.close();child.stderr.close()


if __name__=='__main__': unittest.main()
