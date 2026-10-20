# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
"""Generated host evidence is never physical controller verification."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import pad_hotplug_evidence as hp
from videoout_tests import png,unfiltered


def fixture():
    native=[dict(event='hotplug_opened',qpc=250000,qpc_frequency=1000000,episode=0,instance_id=11,
        connection='wired',vendor=1356,product=3302,real_type=6,virtual=False,sole=True),
        dict(event='hotplug_removed',qpc=9000000,episode=0,instance_id=11,sdl_timestamp_ns=9000000000),
        dict(event='hotplug_opened',qpc=20000000,qpc_frequency=1000000,episode=1,instance_id=12,
        connection='wired',vendor=1356,product=3302,real_type=6,virtual=False,sole=True,sdl_timestamp_ns=20000000000)]
    for stamp,episode,down in ((5000000,0,True),(9000000,0,False),(25000000,1,True),(29000000,1,False)):
        native.append(dict(event='sdl_button',qpc=stamp,episode=episode,instance_id=11+episode,button=0,down=down,
                           origin='SDL event; physical cause not asserted'))
    samples=[]
    for tick in range(5,322):
        us=tick*100000;connected=not 90<=tick<200
        pressed=connected and (50<=tick<90 or 250<=tick<290)
        raw_axes=[128]*4 if connected else [0]*4
        samples.append(dict(sequence=len(samples),handle=1,rc=0,audio_command=int(pressed),observed_us=us,
            timestamp=us if connected else 0,flip=len(samples)+1,audio_blocks=tick*2,
            raw_buttons=hp.CROSS if pressed else 0,effective_buttons=hp.CROSS if pressed else 0,
            raw_axes=raw_axes,effective_axes=[128]*4,connected=int(connected),count=(2 if tick>=200 else 1) if connected else 0,
            raw_triggers=[0,0],effective_triggers=[0,0],payload_valid=1,state=hp.CONNECTED if connected else hp.DISCONNECTED,
            elapsed_us=us+100))
        native.append(dict(event='hotplug_state',qpc=us,episode=int(tick>=200),instance_id=12 if tick>=200 else 11,
            connected=connected,input_valid=connected,buttons=int(pressed) if connected else None,
            axes=[0]*4 if connected else None))
    phases=[]
    for i,base in enumerate((1,5,10,16,21,25,29)):
        phases.append(dict(index=i,label=hp.PLAN[i][0],sequence=base*10+31-5,pixels_verified=640*360,
            instruction_qpc_seconds=base-.01,guest_after_observed_us=int((base-.01)*1e6),capture_qpc_seconds=base+3.15))
    for index,stamp in ((2,8.5),(4,19.2)):
        phases[index].update(instruction_qpc_seconds=stamp,guest_after_observed_us=int(stamp*1e6))
    return native,samples,phases


def audit(samples):
    events=[dict(event='configured',strict_imports=True),dict(event='imports_checked',phase='entry',unresolved_count=0),
            dict(event='guest_entry'),dict(event='guest_output',text='pad-hotplug-av: begin schema=1'),
            dict(event='guest_output',text='pad-hotplug-av: ready schema=1')]
    result=[dict(schema_version=1,elapsed_us=i,**e) for i,e in enumerate(events)]
    for s in samples:
        text=(f"pad-hotplug-av: sample={s['sequence']} handle={s['handle']} rc={s['rc']} command={s['audio_command']} "
              f"observed={s['observed_us']} timestamp={s['timestamp']} flip={s['flip']} audio_blocks={s['audio_blocks']} "
              f"raw_buttons={s['raw_buttons']} effective_buttons={s['effective_buttons']} "
              f"raw_axes={','.join(map(str,s['raw_axes']))} effective_axes={','.join(map(str,s['effective_axes']))} "
              f"connected={s['connected']} count={s['count']} raw_triggers={','.join(map(str,s['raw_triggers']))} "
              f"effective_triggers={','.join(map(str,s['effective_triggers']))} valid={s['payload_valid']} state={s['state']}")
        result.append(dict(schema_version=1,elapsed_us=s['elapsed_us'],event='guest_output',text=text))
    return result


def verify(args): return hp.verify_phases(*args,disconnect_authorized=True,reconnect_authorized=True)


class HotplugTests(unittest.TestCase):
    def test_schema_and_raw_disconnected_values_are_not_normalized(self):
        _,samples,_=fixture()
        raw=hp.HEADER+b''.join(map(hp.pack_record,samples))
        self.assertEqual(hp.verify_records(raw,samples)['bytes_verified'],len(raw))
        self.assertEqual(hp.progress(audit(samples))['samples'],samples)
        absent=next(s for s in samples if s['state']==hp.DISCONNECTED)
        self.assertEqual((absent['timestamp'],absent['raw_axes'],absent['effective_axes']),(0,[0]*4,[128]*4))
        for bad in (raw[1:],raw+b'x',raw[:84]+b'\x01'+raw[85:],raw[:16]+bytes([raw[16]^1])+raw[17:]):
            with self.assertRaises(ValueError): hp.verify_records(bad,samples)

    def test_error_payload_is_retained_invalid_and_never_accepted(self):
        _,samples,_=fixture();samples=samples[:2]
        bad=dict(samples[-1],sequence=2,observed_us=700000,elapsed_us=700100,rc=-123,payload_valid=0,state=hp.API_ERROR,
                 audio_command=0,flip=0,raw_buttons=hp.CROSS,raw_axes=[1,2,3,4],effective_buttons=0)
        samples.append(bad)
        events=audit(samples)
        events.append(dict(schema_version=1,elapsed_us=700101,event='guest_output',text='pad-hotplug-av: FAIL pad API/timestamp; exact result recorded'))
        with self.assertRaisesRegex(ValueError,'FAIL'): hp.progress(events)
        retained=hp.progress(events,allow_failure=True)
        self.assertEqual(retained['samples'][-1]['raw_buttons'],hp.CROSS)
        self.assertFalse(retained['running_observed'])
        self.assertTrue(hp.verify_records(hp.HEADER+b''.join(map(hp.pack_record,samples)),samples)['fatal_report'])
        with self.assertRaises(ValueError): hp.expected_pixels(bytes((1,2,4,7)),bad)

    def test_raw_api_errors_and_zero_connected_timestamp_cannot_masquerade_as_disconnect(self):
        for key,value in (('rc',1),('payload_valid',0),('timestamp',0),('handle',0),('connected',2),('raw_buttons',2**32),('audio_blocks',-1)):
            _,samples,_=fixture();samples[0][key]=value
            with self.assertRaises(ValueError): hp.validate_samples(samples)
        _,samples,_=fixture();samples[85]['rc']=-5
        with self.assertRaises(ValueError): hp.validate_samples(samples)

    def test_held_cross_and_audio_command_are_cleared_without_rewriting_raw_payload(self):
        _,samples,_=fixture()
        absent=next(s for s in samples if s['state']==hp.DISCONNECTED)
        absent['raw_buttons']=hp.CROSS;absent['raw_axes']=[17,33,70,250];absent['raw_triggers']=[255,128]
        hp.validate_samples(samples)
        for key,value in (('effective_buttons',hp.CROSS),('audio_command',1),('effective_axes',[0]*4),('effective_triggers',[255,0])):
            bad=copy.deepcopy(samples);bad[85][key]=value
            with self.assertRaises(ValueError): hp.validate_samples(bad)

    def test_same_handle_fresh_reconnect_and_guest_clock_required(self):
        _,samples,_=fixture()
        for key,value in (('handle',2),('timestamp',8900000),('timestamp',0),('observed_us',8900000)):
            bad=copy.deepcopy(samples);bad[195][key]=value
            with self.assertRaises(ValueError): hp.validate_samples(bad)

    def test_strict_markers_imports_and_explicit_failure_remain_rejected(self):
        _,samples,_=fixture();events=audit(samples[:2])
        for kind in ('bad-line','duplicate-begin','missing-ready','unresolved'):
            bad=copy.deepcopy(events)
            if kind=='bad-line': bad[-1]['text']+=' unknown=1'
            elif kind=='duplicate-begin': bad[4]['text']='pad-hotplug-av: begin schema=1'
            elif kind=='missing-ready': bad.pop(4)
            else: bad.insert(2,dict(schema_version=1,elapsed_us=1,event='unresolved',symbol='missing'))
            with self.assertRaises(ValueError): hp.progress(bad)

    def test_one_complete_cycle_requires_all_seven_distinct_stages(self):
        self.assertEqual(verify(fixture())['qualified_phases'],7)
        for i in range(7):
            args=fixture();args[2].pop(i)
            with self.assertRaises(ValueError): verify(args)
        args=fixture();args[2][4]['sequence']=args[2][0]['sequence']
        with self.assertRaises(ValueError): verify(args)

    def test_authorization_is_not_implied_by_observed_device_events(self):
        for flags in ({},{'disconnect_authorized':True},{'reconnect_authorized':True}):
            with self.assertRaisesRegex(ValueError,'authorization'): hp.verify_phases(*fixture(),**flags)

    def test_new_device_identity_and_actual_removal_order_are_required(self):
        for key,value in (('instance_id',11),('vendor',0),('real_type',1),('virtual',True),('connection','wireless'),('sole',False)):
            args=fixture();args[0][2][key]=value
            with self.assertRaises(ValueError): verify(args)
        for index in (0,1,2):
            args=fixture();args[0].pop(index)
            with self.assertRaises(ValueError): verify(args)
        args=fixture();next(r for r in args[0] if r['event']=='hotplug_state' and r['episode']==1)['instance_id']=11
        with self.assertRaises(ValueError): verify(args)

    def test_removal_generated_release_is_not_post_reconnect_human_release(self):
        args=fixture();args[0][:]=[r for r in args[0] if not (r['event']=='sdl_button' and r['episode']==1 and not r['down'])]
        with self.assertRaisesRegex(ValueError,'control edge'): verify(args)
        args=fixture();args[0][6]['instance_id']=11
        with self.assertRaises(ValueError): verify(args)

    def test_short_holds_stale_pad_time_and_disconnected_stalls_fail(self):
        args=fixture();args[2][1]['instruction_qpc_seconds']=6
        with self.assertRaises(ValueError): verify(args)
        args=fixture()
        for s in args[1][45:85]: s['timestamp']=5000000
        with self.assertRaises(ValueError): verify(args)
        args=fixture();args[1][args[2][3]['sequence']]['audio_blocks']=args[1][args[2][2]['sequence']]['audio_blocks']
        with self.assertRaises(ValueError): verify(args)
        args=fixture();args[1][10]['observed_us']+=400000
        with self.assertRaises(ValueError): verify(args)

    def test_png_binds_entire_original_record_and_disconnected_indicator(self):
        _,samples,_=fixture();sample=samples[100];palette=bytes((1,2,4,7))
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'original.png';path.write_bytes(png(unfiltered(hp.expected_pixels(palette,sample))))
            self.assertEqual(hp.verify_image(path,palette,sample)['pixels_verified'],230400)
            for key,value in (('sequence',1),('audio_blocks',1),('rc',1),('timestamp',123),('connected',1),('raw_axes',[128]*4)):
                with self.assertRaises(ValueError): hp.verify_image(path,palette,dict(sample,**{key:value}))
            with self.assertRaises(ValueError): hp.verify_image(path,bytes((2,1,4,7)),sample)

    def test_fixture_source_is_bound_and_physical_runner_is_permission_gated(self):
        contract=json.loads((ROOT/'config/pad-hotplug-av.json').read_text())
        self.assertEqual(hashlib.sha256((ROOT/'research/homebrew/pad_hotplug_av/main.cpp').read_bytes()).hexdigest(),contract['source_sha256'])
        command=[sys.executable,str(ROOT/'tests/pad_hotplug_guest_tests.py')]
        with tempfile.TemporaryDirectory() as tmp:
            absent=Path(tmp)/'not-opened';args=[]
            for name in ('engine','engine-report','fixture','supervisor','sdl-observer','muted-endpoint-observer','output'):
                args.extend(['--'+name,str(absent)])
            for permission in ([],['--disconnect-authorized'],['--reconnect-authorized']):
                result=subprocess.run(command+args+permission,capture_output=True,timeout=10,text=True)
                self.assertEqual(result.returncode,2);self.assertIn('separate',result.stderr)
                self.assertFalse(absent.exists())

    @unittest.skipUnless(os.environ.get('PS4_HOTPLUG_OBSERVER_CLI'),'Optional locally built SDL helper argument guards')
    def test_native_observer_rejects_arguments_before_any_sdl_initialization(self):
        helper=os.environ['PS4_HOTPLUG_OBSERVER_CLI']
        for args in (['--watch-hotplug','a','b','c','1000'],
                     ['--watch-hotplug','a','b','c','bad','--disconnect-authorized','--reconnect-authorized'],
                     ['--watch-hotplug','a','a','c','1000','--disconnect-authorized','--reconnect-authorized']):
            result=subprocess.run([helper]+args,capture_output=True,text=True,timeout=10)
            self.assertNotEqual(result.returncode,0);self.assertEqual(result.stdout,'')
            self.assertTrue(any(t in result.stderr for t in ('requires','Invalid timeout','Distinct fresh')))


if __name__=='__main__': unittest.main()
