# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
"""Replay immutable actual guest evidence. This does not execute a guest or controller."""
import ast
import hashlib
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import pad_hotplug_evidence as hp
import run_homebrew_startup as startup
from hotplug_endpoint import validate_report

EVIDENCE=ROOT/'research/evidence/2026-10-20-pad-hotplug'
RUN=EVIDENCE/'physical-004'
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def lines(p):return [json.loads(s) for s in p.read_text(encoding='utf-8').splitlines()]
def nodes(p,names):
    tree=ast.parse(p.read_text(encoding='utf-8'))
    return {n.name:ast.dump(n,include_attributes=False) for n in tree.body if getattr(n,'name',None) in names}

class RecordedTests(unittest.TestCase):
    def test_published_original_bytes_and_failed_attempt_classifications_preserved(self):
        manifest=read(EVIDENCE/'manifest.json')
        for item in manifest['artifacts']:
            path=(EVIDENCE/item['published']).resolve()
            path.relative_to(EVIDENCE.resolve())
            self.assertEqual(path.stat().st_size,item['size'])
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),item['sha256'])
            self.assertNotIn(path.suffix.lower(),('.exe','.oelf','.elf','.dll','.lib','.obj'))
        reports=[read(EVIDENCE/f'attempts/physical-{i:03}-analysis.json') for i in range(1,5)]
        self.assertEqual(reports[0]['accepted_phases'],0)
        self.assertEqual(reports[1]['accepted_phases'],4)
        self.assertFalse(reports[1]['complete_physical_acceptance'])
        self.assertIn('TIMER',reports[2]['result'])
        self.assertIn('PASSED_SINGLE_USB_CYCLE',reports[3]['status'])

    def test_actual_1276_guest_records_and_all_seven_vulkan_readbacks(self):
        qualification=read(RUN/'qualification.json')
        samples=hp.progress(startup.read_events(RUN/'guest-audit.jsonl',final=True))['samples']
        verified=hp.verify_records((RUN/'journal.bin').read_bytes(),samples)
        self.assertEqual(verified['records'],1276)
        self.assertEqual(verified['bytes_verified'],91888)
        self.assertEqual({s['rc'] for s in samples},{0})
        self.assertEqual({s['handle'] for s in samples},{1})
        for phase in qualification['phases']:
            name=phase['path'].replace('\\','/').rsplit('/',1)[-1]
            image=hp.verify_image(RUN/'images'/name,qualification['palette'],samples[phase['sequence']])
            self.assertEqual(image['pixels_verified'],230400)
        native=lines(RUN/'native.jsonl')
        result=hp.verify_phases(native,samples,qualification['phases'],disconnect_authorized=True,reconnect_authorized=True)
        self.assertEqual(result['qualified_phases'],7)
        absent=[s for s in samples if s['state']==hp.DISCONNECTED]
        self.assertEqual(len(absent),439)
        self.assertEqual({s['timestamp'] for s in absent},{0})
        self.assertTrue(all(s['connected']==0 and s['audio_command']==0 and s['effective_buttons']==0 for s in absent))
        before=samples[absent[0]['sequence']-1];after=samples[absent[-1]['sequence']+1]
        self.assertEqual((before['timestamp'],after['timestamp']),(48696011,100085210))
        a,b=(samples[qualification['phases'][i]['sequence']] for i in (2,3))
        self.assertEqual(b['observed_us']-a['observed_us'],13766622)
        self.assertEqual((a['audio_blocks'],b['audio_blocks']),(1432,1754))

    def test_actual_endpoint_transitions_explicit_confirmation_and_normal_cleanup(self):
        endpoint=validate_report(RUN/'endpoint.jsonl')
        self.assertEqual((endpoint['samples'],endpoint['default_changes'],endpoint['endpoint_identities']),(4925,2,2))
        self.assertTrue(endpoint['every_available_tracked_endpoint_muted'])
        confirmations=lines(RUN/'human-confirmations.jsonl')
        native=lines(RUN/'native.jsonl')
        opened=[r for r in native if r['event']=='hotplug_opened'];frequency=opened[0]['qpc_frequency']
        removed=next(r for r in native if r['event']=='hotplug_removed')
        for index,stamp in [(2,removed['qpc']/frequency),(4,opened[1]['qpc']/frequency)]:
            permission=next(r for r in confirmations if r['event']=='usb_action_instruction' and r['index']==index)
            self.assertLess(permission['qpc_seconds'],stamp)
            if index==4:self.assertLess(stamp-permission['qpc_seconds'],30)
        for index in range(7):
            actual=[r['confirmed_step'] for r in confirmations if r['event']=='human_confirmation' and r['index']==index]
            expected=['permission','action','release-disconnected','capture'] if index==2 else \
                ['permission','action','capture'] if index==4 else ['action','capture','close'] if index==6 else ['action','capture']
            self.assertEqual(actual,expected)
        cleanup=read(RUN/'supervisor.json')
        self.assertEqual((cleanup['reason'],cleanup['exit_code'],cleanup['active_before_cleanup']),('exited',0,0))
        self.assertFalse(cleanup['forced_termination']);self.assertTrue(cleanup['tree_cleanup']);self.assertTrue(cleanup['root_exit_verified'])

    def test_integrated_execution_policy_matches_the_physically_tested_source(self):
        tested=RUN/'tested-source'
        # Imports, portable root, explicit additional consent and source snapshots
        # are integration changes; the executed run loop/policy remains identical.
        self.assertEqual(nodes(ROOT/'tests/pad_hotplug_guest_tests.py',{'run','instruction'}),
                         nodes(tested/'confirmed_runner.py',{'run','instruction'}))
        self.assertEqual(nodes(ROOT/'tests/pad_hotplug_guide.py',{'ConfirmationState','ConfirmedGuide','reconnect_expired'}),
                         nodes(tested/'confirmed_guide.py',{'ConfirmationState','ConfirmedGuide','reconnect_expired'}))
        self.assertEqual(nodes(ROOT/'tests/hotplug_endpoint.py',{'validate_rows','validate_report'}),
                         nodes(tested/'hotplug_endpoint.py',{'validate_rows','validate_report'}))
        self.assertEqual((ROOT/'tests/hotplug_endpoint_observer.cpp').read_bytes(),(tested/'hotplug_endpoint_observer.cpp').read_bytes())

if __name__=='__main__':unittest.main()
