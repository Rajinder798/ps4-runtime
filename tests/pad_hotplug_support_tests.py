# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
"""Host-only real instruction/confirmation and endpoint rejection checks; no input generation."""
import copy
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

import hotplug_endpoint as endpoint
from muted_endpoint import validate_report as strict_report
import pad_hotplug_guest_tests as runner
from pad_hotplug_guide import ConfirmationState, ConfirmedGuide, reconnect_expired

ROOT=Path(__file__).resolve().parents[1]
HELPER=sys.argv.pop() if len(sys.argv)>1 else 'unsupported'

class Value:
    def set(self,value): self.value=value
class Button:
    def configure(self,**values): self.values=values

def device(i,v=.7,available=True):
    return dict(token=i,available=available,device_state=1 if available else 4,
        muted=True if available else None,volume=v if available else None,
        same_device_volume=True if available else None)
def sample(ms,selected,devices,changed=False):
    return dict(schema_version=1,event='sample',elapsed_ms=ms,default_token=selected,
        default_changed=changed,endpoints=devices)
def reports():
    return [sample(0,0,[device(0)]),sample(25,1,[device(0),device(1,.4)],True),
        sample(50,1,[device(0,available=False),device(1,.4)]),
        sample(75,0,[device(0),device(1,.4)],True),
        dict(schema_version=1,event='summary',status='passed',samples=4,default_changes=2,endpoint_identities=2)]

class SupportTests(unittest.TestCase):
    def test_actual_utf8_stage_labels_render_and_require_each_human_confirmation(self):
        # The real guide methods run with inert labels/buttons, never a Tk window.
        with tempfile.TemporaryDirectory() as tmp:
            g=ConfirmedGuide.__new__(ConfirmedGuide)
            g.confirmations=ConfirmationState();g.output=Path(tmp)
            g.title=Value();g.text=Value();g.confirm_button=Button();g.pump=lambda:None
            g.reconnect_instruction_monotonic=g.unplug_instruction_monotonic=None
            for index in range(7):
                title,text=runner.instruction(index)
                self.assertIn('\u2014',title)
                g.show(title,text)
                self.assertEqual(g.confirmations.index,index)
                self.assertEqual(g.confirm_button.values['state'],'normal')
                self.assertFalse(g.action_confirmed);self.assertFalse(g.capture_confirmed)
                with self.assertRaises(ValueError): g.confirmations.begin(index,True)
                if index in (2,4):
                    self.assertEqual(g.confirmations.mode,'permission')
                    self.assertIn('Do NOT do it yet',g.text.value)
                    if index==4: self.assertIsNone(g.reconnect_instruction_monotonic)
                    g.confirm()
                    self.assertEqual(g.confirmations.mode,'action');self.assertFalse(g.action_confirmed)
                    self.assertIsNotNone(g.reconnect_instruction_monotonic if index==4 else g.unplug_instruction_monotonic)
                g.confirm()
                if index==2:
                    self.assertFalse(g.action_confirmed)
                    self.assertEqual(g.confirmations.mode,'release-disconnected');g.confirm()
                self.assertTrue(g.action_confirmed);self.assertFalse(g.capture_confirmed)
                g.show(*runner.instruction(index,True))
                self.assertEqual(g.confirmations.mode,'capture')
                g.confirm();self.assertTrue(g.capture_confirmed)
                self.assertEqual(g.confirm_button.values['state'],'disabled')
            g.finish();self.assertEqual(g.confirmations.mode,'close')
            g.confirm();self.assertTrue(g.confirmations.closed_confirmed)
            rows=[json.loads(s) for s in (g.output/'human-confirmations.jsonl').read_text(encoding='utf-8').splitlines()]
            for event,count in [('stage_prompt',7),('capture_prompt',7),('human_confirmation',18),('usb_action_instruction',2)]:
                self.assertEqual(sum(r['event']==event for r in rows),count)
            bad=runner.instruction(0)[0].encode('utf-8').decode('cp1252')
            self.assertIsNone(re.match(r'(\d)/7 — (.*)',bad))

    def test_reconnect_clock_begins_after_readiness_not_while_reading_permission(self):
        self.assertFalse(reconnect_expired(None,1000))
        self.assertFalse(reconnect_expired(100,129.999))
        self.assertFalse(reconnect_expired(100,130))
        self.assertTrue(reconnect_expired(100,130.001))
        source=(ROOT/'tests/pad_hotplug_guest_tests.py').read_text(encoding='utf-8')
        self.assertIn('reconnect_expired(guide.reconnect_instruction_monotonic,time.monotonic())',source)
        self.assertIn('time.monotonic()-begun>360',source)
        self.assertIn('Screenshot before phase qualification',source)

    def test_hotplug_protocol_requires_separate_authorization_before_ui_or_device_access(self):
        with tempfile.TemporaryDirectory() as tmp:
            absent=Path(tmp)/'not-created';args=[]
            for name in ('engine','engine-report','fixture','supervisor','sdl-observer','muted-endpoint-observer','output'):
                args.extend(['--'+name,str(absent)])
            result=subprocess.run([sys.executable,str(ROOT/'tests/pad_hotplug_guest_tests.py'),*args,
                '--disconnect-authorized','--reconnect-authorized'],capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,2);self.assertIn('hotplug endpoint protocol',result.stderr)
            self.assertFalse(absent.exists())

    def test_muted_endpoint_transitions_are_recorded_and_per_device_volumes_retained(self):
        result=endpoint.validate_rows(reports())
        self.assertEqual(result['default_changes'],2)
        self.assertEqual(result['per_endpoint_volume'],{0:.7,1:.4})

    def test_unmuted_changed_missing_reappearing_and_incomplete_endpoint_data_rejected(self):
        cases=[]
        for key,value in [('muted',False),('volume',.8),('same_device_volume',False),('available',False),('token',True)]:
            bad=reports();bad[1]['endpoints'][0][key]=value;cases.append(bad)
        for key,value in [('volume',.6),('muted',False),('same_device_volume',False)]:
            bad=reports();bad[2]['endpoints'][1][key]=value;cases.append(bad)
        for index,key,value in [(3,'volume',.8),(2,'muted',True)]:
            bad=reports();bad[index]['endpoints'][0][key]=value;cases.append(bad)
        bad=reports();bad[2]['endpoints'].pop(0);cases.append(bad)
        bad=reports();bad[1]['default_changed']=False;cases.append(bad)
        bad=reports();bad[1]['default_token']=0;cases.append(bad)
        bad=reports();bad[2]['endpoints'][1]=device(1,available=False);cases.append(bad)
        for key,value in [('samples',3),('default_changes',1),('endpoint_identities',3)]:
            bad=reports();bad[-1][key]=value;cases.append(bad)
        bad=reports();bad[2]['elapsed_ms']=1;cases.append(bad)
        cases.extend([reports()[:-1],reports()[1:]])
        self.assertEqual(len(cases),20)
        for i,bad in enumerate(cases):
            with self.subTest(case=i),self.assertRaises((RuntimeError,KeyError)): endpoint.validate_rows(bad)

    def test_original_strict_endpoint_contract_still_rejects_identity_changes(self):
        rows=[dict(elapsed_ms=0,muted=True,volume=1,same_endpoint=True),
            dict(elapsed_ms=25,muted=True,volume=1,same_endpoint=False),dict(status='passed',samples=2)]
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'strict.jsonl';p.write_text('\n'.join(map(json.dumps,rows))+'\n',encoding='utf-8')
            with self.assertRaises(RuntimeError): strict_report(p)

    @unittest.skipIf(HELPER=='unsupported','Windows native argument guards only')
    def test_native_helper_rejects_bad_arguments_before_com_or_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            t=Path(tmp)
            for value in ('0','nan','600001','-1'):
                r=subprocess.run([HELPER,'--watch',str(t/'a'),str(t/'b'),str(t/'c'),value],capture_output=True,timeout=5)
                self.assertNotEqual(r.returncode,0);self.assertFalse(list(t.iterdir()))

if __name__=='__main__':unittest.main()
