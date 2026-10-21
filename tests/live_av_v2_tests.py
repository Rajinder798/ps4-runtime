# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
"""Generated host evidence only. No controller, guest or audio endpoint access."""
import copy
import json
import hashlib
import shutil
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'tools'), str(ROOT/'tests')]
import live_av_v2_evidence as ev
import live_av_v2_contract as contract
import run_live_v2_session as session
import run_homebrew_startup as startup
from videoout_tests import png, unfiltered


def samples():
    rows = []
    for i, (connected, buttons) in enumerate(((1,0),(1,ev.CROSS),(0,ev.CROSS),(0,0),(1,0),(1,ev.CROSS),(1,0))):
        rows.append(dict(sequence=i, handle=1, rc=0, audio_command=int(connected and bool(buttons)),
            observed_us=100000+i*100000, timestamp=100+i if connected else 0, flip=i+1,
            audio_blocks=i*2, raw_buttons=buttons, effective_buttons=buttons if connected else 0,
            raw_axes=[128]*4 if connected else [0]*4, effective_axes=[128]*4,
            connected=connected, count=1 if connected else 0, raw_triggers=[0,0],
            effective_triggers=[0,0], payload_valid=1, state=ev.CONNECTED if connected else ev.DISCONNECTED))
    return rows


def events(rows=None):
    rows = samples() if rows is None else rows
    result = [dict(schema_version=1, elapsed_us=0, event='configured', strict_imports=True),
        dict(schema_version=1, elapsed_us=1, event='imports_checked', phase='entry', unresolved_count=0),
        dict(schema_version=1, elapsed_us=2, event='guest_entry')]
    texts = ['live-av-v2: begin schema=2', 'live-av-v2: ready schema=2']
    for s in rows:
        texts.append('live-av-v2: sample={sequence} handle={handle} rc={rc} command={audio_command} '
            'observed={observed_us} timestamp={timestamp} flip={flip} audio_blocks={audio_blocks} '
            'raw_buttons={raw_buttons} effective_buttons={effective_buttons} raw_axes={ra} '
            'effective_axes={ea} connected={connected} count={count} raw_triggers={rt} '
            'effective_triggers={et} valid={payload_valid} state={state}'.format(**s,
                ra=','.join(map(str,s['raw_axes'])), ea=','.join(map(str,s['effective_axes'])),
                rt=','.join(map(str,s['raw_triggers'])), et=','.join(map(str,s['effective_triggers']))))
    return result+[dict(schema_version=1,elapsed_us=3+i,event='guest_output',text=t) for i,t in enumerate(texts)]


def transport():
    return dict(reason='exited',exit_code=0,forced_termination=False,active_before_cleanup=0,
        tree_cleanup=True,root_exit_verified=True,owner_watch_verified=True,lifetime='until_exit',root_pid=123)


class V2Tests(unittest.TestCase):
    def test_raw_effective_journal_and_distinct_schema(self):
        s=samples(); self.assertTrue(ev.progress(events())['running_observed'])
        raw=ev.HEADER+b''.join(map(ev.pack_record,s))
        self.assertEqual(ev.verify_records(raw,s)['bytes_verified'],16+72*7)
        self.assertEqual(s[2]['raw_buttons'],ev.CROSS)
        self.assertEqual(s[2]['effective_buttons'],0)
        for bad in (raw[:-1], b'PADHP1\0\0'+raw[8:], raw[:8]+struct.pack('<I',1)+raw[12:],raw+b'\0'):
            with self.assertRaises(ValueError):ev.verify_records(bad,s)

    def test_api_invalid_stale_backwards_and_reopened_handle_rejection(self):
        for case in ('api','positive-api','zero','stale','backwards','handle','effective','valid','flip','time','blocks','sequence'):
            s=samples()
            if case=='api':s[2]['rc']=-1
            elif case=='positive-api':s[2]['rc']=1
            elif case=='zero':s[4]['timestamp']=0
            elif case=='stale':s[4]['timestamp']=s[1]['timestamp']
            elif case=='backwards':s[1]['timestamp']=99
            elif case=='handle':s[4]['handle']=2
            elif case=='effective':s[2]['effective_buttons']=ev.CROSS
            elif case=='valid':s[2]['payload_valid']=0
            elif case=='flip':s[2]['flip']=0
            elif case=='time':s[2]['observed_us']=1
            elif case=='blocks':s[4]['audio_blocks']=0
            else:s[3]['sequence']=2
            with self.subTest(case=case),self.assertRaises(ValueError):ev.validate_samples(s)

    def test_actual_error_bytes_preserved_but_never_success(self):
        s=samples()[:3];s[-1].update(rc=-1,payload_valid=0,state=ev.API_ERROR,flip=0)
        self.assertTrue(ev.validate_samples(s)['fatal_report'])
        self.assertTrue(ev.progress(events(s),allow_failure=True)['failure'])
        with self.assertRaises(ValueError):ev.progress(events(s))
        ev.verify_records(ev.HEADER+b''.join(map(ev.pack_record,s)),s)
        with self.assertRaises(ValueError):ev.expected_pixels([0,1,2,3],s[-1])

    def test_full_pixel_wrong_missing_stale_and_corrupt_rejection(self):
        s=samples();palette=[0,1,2,3]
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'image.png'
            with self.assertRaises(ValueError):ev.verify_image(p,palette,s[0])
            p.write_bytes(png(unfiltered(ev.expected_pixels(palette,s[2]))))
            self.assertEqual(ev.verify_image(p,palette,s[2])['pixels_verified'],230400)
            for row,colors in ((s[0],palette),(s[2],[1,2,3,4])):
                with self.assertRaises(ValueError):ev.verify_image(p,colors,row)
            p.write_bytes(p.read_bytes()[:-5])
            with self.assertRaises(ValueError):ev.verify_image(p,palette,s[2])

    def test_exhaustion_and_no_fixed_research_record_limit(self):
        s=[]
        for i in range(4097):
            r=copy.deepcopy(samples()[0]);r.update(sequence=i,flip=i+1,observed_us=1+i*16000,timestamp=1+i,audio_blocks=i)
            s.append(r)
        ev.validate_samples(s)
        self.assertEqual(16+72*ev.MAX_RECORDS,4194304-(4194304-16)%72)
        self.assertLessEqual(16+72*ev.MAX_RECORDS,ev.MAX_JOURNAL_BYTES)
        with self.assertRaises(ValueError):ev.verify_records(b'x'*(ev.MAX_JOURNAL_BYTES+1),s)
        self.assertEqual(72*60*60,259200) # bytes/minute at hypothetical 60 records/sec, not measured FPS
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'audit';p.write_bytes(b'x'*(startup.MAX_AUDIT_BYTES+1))
            with self.assertRaises(ValueError):startup.read_events(p)

    def test_continuity_and_disconnected_progress(self):
        s=samples();s[3]['observed_us']=s[2]['observed_us']+5000000
        ev.verify_disconnected_progress(s[2],s[3])
        for field,value in (('observed_us',s[2]['observed_us']+4999999),('flip',s[2]['flip']),('audio_blocks',s[2]['audio_blocks']),('state',ev.CONNECTED)):
            r=dict(s[3]);r[field]=value
            with self.assertRaises(ValueError):ev.verify_disconnected_progress(s[2],r)
        ev.verify_continuity(samples())
        with self.assertRaises(ValueError):ev.verify_continuity(s)

    def test_strict_transport_never_converts_forced_cleanup_to_success(self):
        ev.verify_transport(transport())
        for field,value in (('reason','owner_exited'),('exit_code',1),('forced_termination',True),
            ('active_before_cleanup',1),('tree_cleanup',False),('root_exit_verified',False),
            ('owner_watch_verified',False),('lifetime','bounded'),('root_pid',0)):
            r=transport();r[field]=value
            with self.assertRaises(ValueError):ev.verify_transport(r)

    def test_real_runner_with_inert_host_boundaries_and_binary_journal(self):
        # Executes actual runner coordination; the fake supervisor never launches anything.
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);out=root/'out';out.mkdir()
            paths={k:root/k for k in ('engine','engine_report','fixture','supervisor')}
            for p in paths.values():p.write_text('host dummy')
            def supervise(supervisor,command,work,timeout,poll,*,on_started,environment):
                on_started(999)
                (work/'startup-audit.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events()))
                d=work/'user/data';d.mkdir(exist_ok=True)
                (d/'live-av-v2.bin').write_bytes(ev.HEADER+b''.join(map(ev.pack_record,samples())))
                self.assertFalse(poll())
                return self.result
            for bad in (False,True):
                if bad:
                    out=root/'bad';out.mkdir()
                self.result=transport()
                if bad:self.result['forced_termination']=True
                with patch.object(session.sys,'platform','win32'),patch.object(session.platform,'machine',return_value='AMD64'),\
                    patch.object(contract,'verify_inputs',return_value={}),patch.object(startup,'supervise',side_effect=supervise):
                    code,r=session.run_session(**paths,output=out)
                self.assertEqual(code,int(bad));self.assertEqual(r['normal_exit_verified'],not bad)
                self.assertFalse(r['independent_av_qualification_performed'])
                self.assertFalse(r['automated_gameplay_input_sent'])

    def test_exact_cadence_one_open_and_legacy_boundaries(self):
        source=(ROOT/'research/homebrew/live_av_v2/main.cpp').read_text()
        self.assertIn('sceKernelUsleep(LiveV2::PostFlipSleepUs)',source)
        self.assertEqual(source.count('scePadOpen('),1)
        self.assertNotIn('scePadClose(',source)
        import ps4_launch, runtime_settings
        self.assertNotIn('live-av-v2',ps4_launch.PROFILES)
        self.assertNotIn('live-av-v2',runtime_settings.AUDIO_TITLES)

    def test_pending_owner_is_logged_and_progress_uses_original_audit(self):
        import live_av_v2_guest_tests as driver
        emitted=[]
        with patch.object(driver,'read_status',side_effect=FileNotFoundError):
            self.assertIsNone(driver.optional_progress(Path('unused'),lambda event:emitted.append(event)))
        self.assertEqual(emitted,['owner_metadata_pending'])
        with patch.object(driver,'read_status',side_effect=ValueError),self.assertRaises(ValueError):
            driver.optional_progress(Path('unused'),lambda event:None)
        with patch.object(driver,'read_status',return_value=dict(schema_version=1,supervisor_pid=10)),\
            patch.object(startup,'read_events',return_value=events()):
            self.assertTrue(driver.optional_progress(Path('unused'),lambda event:None)['running_observed'])

    def test_human_protocol_permissions_order_and_budget_without_ui(self):
        from live_av_v2_guide import Protocol
        for scenario,reconnect,count in (('recovery',True,9),('disconnected-close',False,3)):
            with self.assertRaises(ValueError):Protocol(scenario)
            p=Protocol(scenario,physical_authorized=True,disconnect_authorized=True,reconnect_authorized=reconnect,before_close=lambda:None)
            p.ready()
            for i in range(count):
                self.assertEqual(p.index,i)
                with self.assertRaises(ValueError):p.verified()
                if p.mode=='usb-permission':p.confirm()
                p.confirm();p.capture();p.confirm();p.verified()
            self.assertEqual(p.mode,'close-permission')
            p.confirm();self.assertEqual(p.mode,'close');p.confirm();self.assertEqual(p.mode,'closed')
            with self.assertRaises(ValueError):p.confirm()
            with self.assertRaises(ValueError):p.check_budget(p.started+361)

    def test_supervisor_report_is_consumed_only_after_containment_finishes(self):
        import live_av_v2_guest_tests as driver
        with tempfile.TemporaryDirectory() as t:
            out=Path(t);(out/'session').mkdir();order=[]
            def wait(pid):
                order.append(pid)
                if pid==2:(out/'session/supervisor.json').write_text(json.dumps(transport()))
            with patch.object(driver,'wait_dead',side_effect=wait):
                r=driver.completed_transport(out,launcher_dead=True,root_pid=1,supervisor_pid=2)
            self.assertEqual(order,[1,2]);self.assertEqual(r,transport())

    def test_physical_cli_refuses_missing_consent_before_any_output_or_device(self):
        with tempfile.TemporaryDirectory() as t:
            out=Path(t)/'must-not-exist'
            command=[sys.executable,str(ROOT/'tests/live_av_v2_guest_tests.py')]
            for key in ('engine','engine-report','fixture','supervisor','muted-endpoint-observer'):
                command.extend(['--'+key,'unused'])
            command.extend(['--output',str(out),'--physical-scenario','recovery'])
            result=subprocess.run(command,capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,2);self.assertFalse(out.exists())
            self.assertIn('permissions required',result.stderr)

    def test_v2_contract_rejects_changed_engine_source_fixture_and_patch(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);(root/'config').mkdir()
            for name in ('startup-research.json','g2-integration-audit.json'):
                shutil.copyfile(ROOT/'config'/name,root/'config'/name)
            c=json.loads((root/'config/startup-research.json').read_text())
            for key in ('patch','audit_header','services_header','aac_header'):
                path=Path(c[key+'_path']);(root/path).parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(ROOT/path,root/path)
            source=root/'research/homebrew/live_av_v2/main.cpp';source.parent.mkdir(parents=True)
            source.write_bytes(b'original source')
            engine=root/'engine';fixture=root/'fixture';report=root/'report'
            engine.write_bytes(b'engine');fixture.write_bytes(b'fixture')
            config=dict(schema_version=1,source_sha256=startup.digest(source),oelf_sha256=startup.digest(fixture))
            (root/'config/live-av-v2.json').write_text(json.dumps(config))
            audit=json.loads((root/'config/g2-integration-audit.json').read_text())
            r=dict(status='strict_engine_built',upstream_revision=audit['upstream']['revision'],
                patched_tree=c['expected_patched_tree'],aac_backend='ffmpeg-aac-lc',fdk_linkage_verified_absent=True,
                aac_tests=dict(status='passed'),executable_sha256=startup.digest(engine))
            for key in ('patch','audit_header','services_header','aac_header'):r[key+'_sha256']=c[key+'_sha256']
            report.write_text(json.dumps(r))
            with patch.object(contract,'ROOT',root):
                contract.verify_inputs(engine,report,fixture)
                for path in (engine,fixture,source,root/c['patch_path']):
                    original=path.read_bytes();path.write_bytes(original+b'changed')
                    with self.assertRaises(ValueError):contract.verify_inputs(engine,report,fixture)
                    path.write_bytes(original)
                with self.assertRaises(ValueError):contract.verify_inputs(engine,report,fixture,'live-av')

    def test_generated_physical_recovery_contract_and_missing_edges(self):
        from live_av_v2_guide import RECOVERY
        rows=[];native=[];phases=[];human=[dict(event='human_ready_clicked',index=-1,qpc_seconds=.01)]
        opened=dict(event='hotplug_opened',episode=0,instance_id=10,qpc=100000,qpc_frequency=1000000,
            vendor=1356,product=3302,real_type=6,connection='wired',virtual=False,sole=True)
        native.append(opened)
        for i in range(485):
            at=(i+1)/10;connected=not 21.1<=at<33.1
            pressed=(6.1<=at<11.1 or 16.1<=at<21.1 or 38.1<=at<43.1)
            row=copy.deepcopy(samples()[0]);row.update(sequence=i,flip=i+1,observed_us=round(at*1e6),
                timestamp=round(at*1e6) if connected else 0,audio_blocks=i*2,
                raw_buttons=ev.CROSS if pressed else 0,effective_buttons=ev.CROSS if pressed and connected else 0,
                connected=int(connected),state=ev.CONNECTED if connected else ev.DISCONNECTED,audio_command=int(pressed and connected))
            rows.append(row)
            native.append(dict(event='hotplug_state',qpc=round(at*1e6),episode=int(at>=33.1),
                instance_id=11 if at>=33.1 else 10,connected=connected,input_valid=connected,
                buttons=int(pressed) if connected else None,axes=[0]*4 if connected else None))
        native.extend([dict(event='hotplug_removed',episode=0,instance_id=10,qpc=21100000),
            dict(opened,episode=1,instance_id=11,qpc=33100000)])
        for at,ep,down in ((6.1,0,True),(11.1,0,False),(16.1,0,True),(21.1,0,False),(38.1,1,True),(43.1,1,False)):
            native.append(dict(event='sdl_button',qpc=round(at*1e6),episode=ep,instance_id=10+ep,button=0,down=down))
        native.sort(key=lambda r:r['qpc']);native.append(dict(event='stopped',qpc=49000000))
        for i,(start,stop) in enumerate(zip((1,6,11,16,21,26,33,38,43),(5,10,15,20,25,32,37,42,47))):
            phases.append(dict(index=i,label=RECOVERY[i],sequence=stop*10-1,instruction_qpc_seconds=float(start),
                capture_qpc_seconds=float(stop),guest_after_observed_us=int(start*1e6),pixels_verified=230400))
            usb=i in (4,6)
            if usb:human.append(dict(index=i,event='usb-permission',qpc_seconds=start-.1))
            human.extend(dict(index=i,event=e,qpc_seconds=stamp) for e,stamp in
                zip((('usb_action_instruction' if usb else 'action'),'human_action_confirmed','capture_prompt','human_f12_confirmed'),
                    (float(start),start+.2,stop-.3,stop-.2)))
        close=dict(last_owned_qpc_seconds=47.1,instruction_qpc_seconds=47.2,root_exit_qpc_seconds=48.,
            finished_qpc_seconds=48.1,confirmed_qpc_seconds=48.3,ownership_failed=False,root_pid=123,bound_window=99,
            last_guest_observed_us=rows[-1]['observed_us'],last_guest_seen_qpc_seconds=47.9)
        human.extend(dict(index=9,event=e,qpc_seconds=stamp) for e,stamp in
            zip(('close-permission','normal_close_instruction','human_close_confirmed'),(47.05,47.2,48.3)))
        self.assertEqual(ev.verify_physical(native,rows,phases,RECOVERY,transport(),close)['qualified_phases'],9)
        ev.verify_confirmations(human,phases,RECOVERY,close)
        for kind in ('release','missing-phase','ownership','short','reopen','confirmation'):
            n=copy.deepcopy(native);p=copy.deepcopy(phases);c=copy.deepcopy(close);s=copy.deepcopy(rows)
            if kind=='release':n=[r for r in n if not(r['event']=='sdl_button' and r['qpc']==43100000)]
            elif kind=='missing-phase':p.pop()
            elif kind=='ownership':c['ownership_failed']=True
            elif kind=='short':p[5]['sequence']=p[4]['sequence']+1
            elif kind=='reopen':s[-1]['handle']=2
            else:
                with self.assertRaises(ValueError):ev.verify_confirmations(human[:-1],phases,RECOVERY,close)
                continue
            with self.subTest(kind=kind),self.assertRaises(ValueError):ev.verify_physical(n,s,p,RECOVERY,transport(),c)


if __name__=='__main__':unittest.main()
