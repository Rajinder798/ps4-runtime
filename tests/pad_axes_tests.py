# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
"""Host-only generated evidence: never physical-controller acceptance."""
import copy
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import pad_axes_evidence as axes
from videoout_tests import png,unfiltered


def fixture():
    native=[dict(event='opened',connection='wired',virtual=False,vendor=1356,product=3302,instance_id=1,qpc_frequency=1000000)]
    samples=[];phases=[]
    for index,phase in enumerate(axes.PLAN):
        base=1+index*4
        guest=[128]*4;sdl=[0]*4
        if phase[1] is not None:
            guest[phase[1]]=0 if phase[2]<0 else 255;sdl[phase[1]]=phase[2]*30000
            native.append(dict(event='physical_axis',qpc=base*1000000,instance_id=1,axis=phase[1],value=sdl[phase[1]]))
        for offset in range(32):
            stamp=base*1000000+offset*100000
            native.append(dict(event='axis_state',qpc=stamp,connected=True,buttons=0,axes=list(sdl)))
            samples.append(dict(sequence=len(samples),buttons=0,timestamp=stamp,flip=len(samples)+1,
                                axes=list(guest),connected=1,elapsed_us=stamp))
        phases.append(dict(index=index,label=phase[0],instruction_qpc_seconds=base-.01,
                           guest_after_elapsed_seconds=base-.01,capture_qpc_seconds=base+3.1,
                           sequence=len(samples)-1,pixels_verified=640*360))
    return native,samples,phases


def events():
    result=[dict(event='configured',strict_imports=True),dict(event='imports_checked',phase='entry',unresolved_count=0),dict(event='guest_entry')]
    texts=['pad-axes: begin schema=1','pad-axes: ready schema=1',
           'pad-axes: sample=0 buttons=0 timestamp=10 flip=1 lx=128 ly=128 rx=128 ry=128 connected=1']
    result += [dict(event='guest_output',text=t) for t in texts]
    return [dict(schema_version=1,elapsed_us=i,**e) for i,e in enumerate(result)]


class AxesTests(unittest.TestCase):
    def test_window_identity_diagnostic_keeps_the_ownership_failure(self):
        import ctypes
        from owned_window_trace import OwnedWindowTrace
        class InvalidWindow:
            @staticmethod
            def GetWindowThreadProcessId(window,pid):return 0
        state=object.__new__(OwnedWindowTrace)
        state.window=123;state.pid=456;state.user=InvalidWindow();state.diagnostics=None;events=[]
        state.emit=lambda event,**fields:events.append(dict(event=event,**fields))
        with patch.object(ctypes,'get_last_error',return_value=1400,create=True), patch.object(ctypes,'set_last_error',create=True):
            with self.assertRaisesRegex(RuntimeError,'identity changed'):state.poll()
        self.assertEqual(len(events),1)
        record=events[0]
        self.assertGreater(record.pop('qpc_seconds'),0);self.assertGreater(record.pop('unix_ns'),0)
        self.assertEqual(record,dict(event='owned_window_identity_failure',expected_root_pid=456,observed_pid=0,
                                    window_handle=123,observed_thread=0,win32_error=1400))

    def test_raw_guest_file_requires_exact_schema_values_and_reserved_bytes(self):
        _,samples,_=fixture()
        raw=axes.HEADER+b''.join(axes.RECORD.pack(s['sequence'],s['buttons'],s['timestamp'],s['flip'],*s['axes'],s['connected']) for s in samples)
        self.assertEqual(axes.verify_records(raw,samples)['records'],len(samples))
        for bad in (raw[1:],raw+b'x',b'badmagic'+raw[8:],raw[:40]+bytes([raw[40]^1])+raw[41:],raw[:45]+b'\x01'+raw[46:]):
            with self.assertRaises(ValueError):axes.verify_records(bad,samples)

    def test_strict_guest_order_failure_range_and_connection(self):
        self.assertTrue(axes.progress(events())['running_observed'])
        for change in ('connected=0','lx=256','sample=1','flip=2','timestamp=0'):
            data=events();old=change.split('=')[0]
            import re
            data[-1]['text']=re.sub(old+r'=\d+',change,data[-1]['text'])
            with self.assertRaises(ValueError):axes.progress(data)
        data=events();data[-1]['text']='pad-axes: FAIL pad disconnected'
        with self.assertRaises(ValueError):axes.progress(data)
        data=events();data[3]['text'],data[4]['text']=data[4]['text'],data[3]['text']
        with self.assertRaises(ValueError):axes.progress(data)

    def test_all_eight_cardinal_directions_and_nine_centers_required(self):
        args=fixture();self.assertEqual(axes.verify_phases(*args)['qualified_phases'],17)
        for i in range(17):
            bad=copy.deepcopy(args);bad[2].pop(i)
            with self.assertRaises(ValueError):axes.verify_phases(*bad)
        for event in ('removed',):
            bad=copy.deepcopy(args);bad[0].append(dict(event=event))
            with self.assertRaises(ValueError):axes.verify_phases(*bad)

    def test_detected_virtual_wireless_or_axis_motion_alone_cannot_pass(self):
        for key,value in (('virtual',True),('connection','wireless'),('product',0)):
            args=fixture();args[0][0][key]=value
            with self.assertRaises(ValueError):axes.verify_phases(*args)
        args=fixture();args[0][:]=[r for r in args[0] if r['event']!='physical_axis']
        with self.assertRaises(ValueError):axes.verify_phases(*args)
        args=fixture()
        next(r for r in args[0] if r['event']=='physical_axis')['instance_id']=99
        with self.assertRaises(ValueError):axes.verify_phases(*args)

    def test_center_wrong_stick_direction_button_and_short_hold_rejected(self):
        self.assertTrue(axes.matches([128]*4,0,1,axes.PLAN[0]))
        self.assertFalse(axes.matches([150,128,128,128],0,1,axes.PLAN[0]))
        self.assertFalse(axes.matches([128,128,0,128],0,1,axes.PLAN[1]))
        self.assertFalse(axes.matches([255,128,128,128],0,1,axes.PLAN[1]))
        self.assertFalse(axes.matches([0,128,128,128],0x4000,1,axes.PLAN[1]))
        args=fixture();args[2][1]['instruction_qpc_seconds']+=1
        with self.assertRaises(ValueError):axes.verify_phases(*args)
        args=fixture();args[2][1]['guest_after_elapsed_seconds']+=1
        with self.assertRaises(ValueError):axes.verify_phases(*args)
        # A large observation gap cannot count as uninterrupted stability.
        rows=[dict(qpc=i*1000000,axes=[0]*4,buttons=0,connected=True) for i in (1,2,5)]
        self.assertEqual(axes.stable_suffix(rows,axes.PLAN[0],sdl=True,frequency=1000000)[1],0)
        args=fixture();args[2][2]['sequence']=args[2][0]['sequence']
        with self.assertRaises(ValueError):axes.verify_phases(*args)

    def test_exact_image_binds_sequence_axes_buttons_and_challenge(self):
        _,samples,_=fixture();sample=samples[32];palette=bytes((1,2,4,7))
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'original.png';path.write_bytes(png(unfiltered(axes.expected_pixels(palette,sample))))
            self.assertEqual(axes.verify_image(path,palette,sample)['pixels_verified'],230400)
            for key,value in (('sequence',0),('axes',[255,128,128,128]),('buttons',0x2000),('connected',0)):
                bad=dict(sample,**{key:value})
                with self.assertRaises(ValueError):axes.verify_image(path,palette,bad)
            with self.assertRaises(ValueError):axes.verify_image(path,bytes((2,1,4,7)),sample)

    def test_fixture_contract_and_human_axis_instructions(self):
        contract=json.loads((ROOT/'config/pad-axes.json').read_text())
        self.assertEqual(hashlib.sha256((ROOT/'research/homebrew/pad_axes/main.cpp').read_bytes()).hexdigest(),contract['source_sha256'])
        from dualsense_axes_guest_tests import instruction
        for i,(_,axis,sign) in enumerate(axes.PLAN):
            title,text=instruction(i)
            self.assertIn('F12 NOW',instruction(i,True)[0])
            self.assertIn('CENTERED' if axis is None else ('LEFT STICK' if axis<2 else 'RIGHT STICK'),title)
            self.assertIn('muted',text)


if __name__=='__main__':unittest.main()
