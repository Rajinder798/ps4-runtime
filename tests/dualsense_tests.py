# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
"""Host-only negative evidence tests; generated data is not physical verification."""
import json
from pathlib import Path
import struct
import sys
import unittest
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from dualsense_evidence import PLAN, verify_physical, record_instruction, append_progress, classify_disconnect, readback_ready
from dualsense_guide import phase_instruction


def fixture():
    records = [dict(event='opened', connection='wired', virtual=False, vendor=0x054c,
                    product=0x0ce6, qpc_frequency=1000000, instance_id=1)]
    samples, captures = [], []
    for i, (_, guest, sdl) in enumerate(PLAN):
        records.append(dict(event='state', qpc=(i+1)*5000000, connected=True, buttons=sdl))
        if i:
            code = (sdl or PLAN[i-1][2]).bit_length()-1
            records.append(dict(event='physical_button', qpc=(i+1)*5000000, instance_id=1,
                                button=code, down=bool(sdl)))
        samples.append(dict(sequence=i, buttons=guest, timestamp=(i+1)*5000000, flip=i+1, audio_blocks=i+1))
        captures.append(dict(sequence=i, buttons=guest))
    raw = b''.join(struct.pack('<IIQQ', s['sequence'], s['buttons'], s['timestamp'], s['flip']) for s in samples)
    return records, samples, raw, captures


class PhysicalEvidenceTests(unittest.TestCase):
    def test_original_png_is_not_consumed_while_engine_is_still_writing(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'original.png';path.touch();pending={}
            self.assertFalse(readback_ready(path,pending,now=10))
            path.write_bytes(b'\x89PNG\r\n\x1a\n')
            self.assertFalse(readback_ready(path,pending,now=11))
            path.write_bytes(path.read_bytes()+b'\0\0\0\0IEND\xaeB`\x82')
            self.assertTrue(readback_ready(path,pending,now=12))
            # Readiness never grants pixel/CRC qualification; the existing full
            # decoder/oracle still rejects malformed or wrong-state images.
            path.write_bytes(b'incomplete')
            with self.assertRaises(ValueError):readback_ready(path,pending,now=15)

    def test_guide_names_each_actual_button_and_release(self):
        controls={1:'Cross',3:'Cross',5:'Circle',7:'D-pad UP',9:'D-pad DOWN',11:'D-pad LEFT',13:'D-pad RIGHT'}
        self.assertIn('NEUTRAL',phase_instruction(PLAN,0)[0])
        for index,name in controls.items():
            self.assertIn(name,phase_instruction(PLAN,index)[0])
            self.assertIn('HOLD',phase_instruction(PLAN,index)[0])
            self.assertIn(name,phase_instruction(PLAN,index,True)[1])
            self.assertIn('RELEASE '+name,phase_instruction(PLAN,index+1)[0])
        self.assertIn('15/15',phase_instruction(PLAN,14)[0])

    def test_circle_and_all_dpad_evidence_is_mandatory(self):
        for index in (5,7,9,11,13):
            args=fixture();args[1][index]['buttons']=0
            with self.assertRaises(ValueError):verify_physical(*args)
            args=fixture();edges=[r for r in args[0] if r['event']=='physical_button'];edges.pop(index-1)
            args[0][:]=[r for r in args[0] if r['event']!='physical_button']+edges
            with self.assertRaises(ValueError):verify_physical(*args)

    def test_disconnect_classification_never_claims_graceful_support(self):
        result=dict(error='Invalid/failing live guest output: live-av: FAIL pad read/connection',
            transport=dict(tree_cleanup=True,root_exit_verified=True,forced_termination=True))
        args=dict(authorized=True,neutral_qualified=True,observation_seconds=0)
        actual=classify_disconnect([dict(event='removed')],result,1,**args)
        self.assertFalse(actual['graceful_controller_support_verified'])
        self.assertTrue(actual['forced_cleanup'])
        for field in ('authorized','neutral_qualified'):
            invalid=dict(args,**{field:False})
            with self.assertRaises(ValueError):classify_disconnect([dict(event='removed')],result,1,**invalid)
        with self.assertRaises(ValueError):classify_disconnect([],result,1,**args)
        result=dict(normal_exit_verified=True,transport=dict(tree_cleanup=True,root_exit_verified=True,forced_termination=False))
        with self.assertRaises(ValueError):classify_disconnect([dict(event='removed')],result,0,**args)
        args['observation_seconds']=5
        self.assertFalse(classify_disconnect([dict(event='removed')],result,0,**args)['graceful_controller_support_verified'])

    def test_progress_history_can_append_with_a_reader_open(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'progress.jsonl'
            append_progress(path,dict(state='starting',completed=0))
            with path.open(encoding='utf-8') as reader:
                first=json.loads(reader.readline())
                append_progress(path,dict(state='neutral_capture',completed=0))
                second=json.loads(reader.readline())
            self.assertEqual(first['state'],'starting')
            self.assertEqual(second['state'],'neutral_capture')
            self.assertEqual(len(path.read_text(encoding='utf-8').splitlines()),2)

    def test_cross_scope_still_requires_two_cycles_and_all_five_images(self):
        records,samples,raw,captures=fixture()
        subset=[r for r in records if r['event']=='opened' or r['qpc']<=25000000]
        result=verify_physical(subset,samples[:5],raw[:120],captures[:5],controls='cross')
        self.assertEqual(result['controls'],['Cross'])
        with self.assertRaises(ValueError):verify_physical(subset,samples[:3],raw[:72],captures[:3],controls='cross')
        with self.assertRaises(ValueError):verify_physical(subset,samples[:5],raw[:120],captures[:4],controls='cross')

    def test_real_operator_command_timestamp_can_be_logged_without_collision(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'trace.jsonl'
            command=dict(index=0,instruction='Leave neutral and physically press F12',monotonic=12.5)
            event=record_instruction(path,command)
            self.assertEqual(json.loads(path.read_text(encoding='utf-8')),event)
            self.assertEqual(event['command'],command)
            self.assertGreater(event['monotonic'],0)

    def test_complete_protocol_and_missing_physical_events(self):
        args=fixture()
        self.assertTrue(verify_physical(*args)['cross_two_cycles'])
        args[0][:]=[r for r in args[0] if r['event']!='physical_button']
        with self.assertRaises(ValueError): verify_physical(*args)

    def test_virtual_wireless_disconnect_and_wrong_instance_rejected(self):
        for key,value in (('virtual',True),('connection','wireless'),('vendor',0)):
            args=fixture();args[0][0][key]=value
            with self.assertRaises(ValueError): verify_physical(*args)
        args=fixture();args[0].append(dict(event='removed'))
        with self.assertRaises(ValueError): verify_physical(*args)
        args=fixture();next(r for r in args[0] if r['event']=='physical_button')['instance_id']=2
        with self.assertRaises(ValueError): verify_physical(*args)

    def test_short_hold_in_either_domain_rejected(self):
        args=fixture();edges=[r for r in args[0] if r['event']=='physical_button'];edges[1]['qpc']=edges[0]['qpc']+1000000
        with self.assertRaises(ValueError): verify_physical(*args)
        args=list(fixture());args[1][2]['timestamp']=args[1][1]['timestamp']+1000000
        args[2]=b''.join(struct.pack('<IIQQ', s['sequence'],s['buttons'],s['timestamp'],s['flip']) for s in args[1])
        with self.assertRaises(ValueError): verify_physical(*args)

    def test_wrong_guest_record_or_missing_graphics_rejected(self):
        args=list(fixture());args[2]=args[2][:-1]
        with self.assertRaises(ValueError): verify_physical(*args)
        args=fixture();args[3].pop()
        with self.assertRaises(ValueError): verify_physical(*args)
        args=fixture();args[3][1]['buttons']=0
        with self.assertRaises(ValueError): verify_physical(*args)


if __name__=='__main__': unittest.main()
