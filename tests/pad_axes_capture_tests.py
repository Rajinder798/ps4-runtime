# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
"""Synthetic host qualification regression; no device, guest or GUI execution."""
import copy
import json
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'tests')]
import pad_axes_evidence as axes
import dualsense_axes_guest_tests as runner
from pad_axes_tests import fixture


def measured_timing():
    # Generated UP records; timing and neighboring values reproduce the sealed
    # stage-6 boundary. No device IDs, physical evidence or PASS claim included.
    frequency=10000000
    start=851201959570
    online_end=851251382504
    times=sorted(set([start+i*1000000 for i in range(49)]+[851232502007,online_end]))
    rows=[dict(event='axis_state',qpc=t,connected=True,buttons=0,axes=[642,-32768,385,0]) for t in times]
    rows += [dict(event='axis_state',qpc=t,connected=True,buttons=0,axes=[x,-32768,385,0]) for t,x in
             [(851252425821,1413),(851253479890,1413),(851254531485,1670),
              (851255584565,1670),(851256639514,2184),(851257694270,1927)]]
    return rows,frequency,online_end,85125.7320741


class CaptureTests(unittest.TestCase):
    def test_original_timed_counterexample_stays_rejected(self):
        rows,freq,end,cutoff=measured_timing();phase=axes.PLAN[5]
        def suffix(cut):return axes.stable_suffix([x for x in rows if x['qpc']/freq<=cut],phase,
                                                sdl=True,after=85114.3843059,frequency=freq)
        self.assertAlmostEqual(suffix(85123.2502007)[1],3.0542437)
        self.assertAlmostEqual(suffix(end/freq)[1],4.9422934)
        self.assertEqual(suffix(cutoff),([],0))
        self.assertFalse(axes.sdl_cutoff_covered(rows[:-1],freq,cutoff))
        self.assertTrue(axes.sdl_cutoff_covered(rows,freq,cutoff))
        self.assertFalse(axes.matches([2184,-32768,385,0],0,True,phase,sdl=True))

    def test_all_stable_phases_keep_the_existing_final_acceptance(self):
        native,samples,phases=fixture()
        for q in phases:
            self.assertTrue(axes.sdl_cutoff_covered(native,1000000,q['capture_qpc_seconds']))
            evidence=axes.verify_capture(native[0],native,samples,q)
            self.assertGreaterEqual(evidence['stable_sdl_seconds'],3)
        self.assertEqual(axes.verify_phases(native,samples,phases)['qualified_phases'],17)

    def altered_phase(self,offset,lx,cutoff=None):
        native,samples,phases=fixture();q=phases[5]
        row=dict(event='axis_state',qpc=int((21+offset)*1000000),connected=True,buttons=0,axes=[lx,-30000,0,0])
        native[:]=[x for x in native if x.get('event')!='axis_state' or x['qpc']!=row['qpc']]
        native.append(row)
        native.sort(key=lambda x:x.get('qpc',-1))
        if cutoff is not None:q['capture_qpc_seconds']=21+cutoff
        return native,samples,q

    def test_late_off_axis_at_cutoff_is_included_and_rejected(self):
        native,samples,q=self.altered_phase(3.1,2184)
        with self.assertRaisesRegex(ValueError,'Missing sustained'):
            axes.verify_capture(native[0],native,samples,q)

    def test_movement_strictly_after_cutoff_does_not_change_frozen_capture(self):
        native,samples,q=self.altered_phase(3.100001,2184)
        self.assertTrue(axes.sdl_cutoff_covered(native,1000000,q['capture_qpc_seconds']))
        self.assertGreaterEqual(axes.verify_capture(native[0],native,samples,q)['stable_sdl_seconds'],3)

    def test_delayed_capture_rejects_late_invalid_input(self):
        native,samples,q=self.altered_phase(3.2,2184,3.4)
        native.append(dict(event='axis_state',qpc=24500000,connected=True,buttons=0,axes=[0,-30000,0,0]))
        native.sort(key=lambda x:x.get('qpc',-1))
        self.assertTrue(axes.sdl_cutoff_covered(native,1000000,q['capture_qpc_seconds']))
        with self.assertRaisesRegex(ValueError,'Missing sustained'):
            axes.verify_capture(native[0],native,samples,q)

    def test_late_snapshot_waits_without_moving_cutoff(self):
        rows,freq,end,cutoff=measured_timing()
        self.assertFalse(axes.sdl_cutoff_covered([x for x in rows if x['qpc']<=end],freq,cutoff))
        self.assertTrue(axes.sdl_cutoff_covered(rows,freq,cutoff))
        self.assertEqual(cutoff,85125.7320741)

    def test_strict_sideways_tolerance_not_relaxed(self):
        for lx,accepted in ((2048,True),(2049,False),(2184,False)):
            native,samples,q=self.altered_phase(3.1,lx)
            if accepted:axes.verify_capture(native[0],native,samples,q)
            else:
                with self.assertRaisesRegex(ValueError,'Missing sustained'):
                    axes.verify_capture(native[0],native,samples,q)

    def test_wrong_guest_short_hold_and_missing_motion_still_reject(self):
        for mutation in ('guest','short','motion'):
            native,samples,phases=fixture();q=phases[5]
            if mutation=='guest':samples[q['sequence']]['axes']=[128]*4
            if mutation=='short':q['instruction_qpc_seconds']+=1
            if mutation=='motion':native[:]=[x for x in native if x['event']!='physical_axis']
            with self.assertRaises(ValueError):axes.verify_capture(native[0],native,samples,q)

    def test_nonmonotonic_axis_stream_cannot_seal_an_earlier_prefix(self):
        native,_,_=fixture();rows=[x for x in native if x['event']=='axis_state']
        for bad in (rows[::-1],rows+[rows[-1]],[]):
            if bad:
                with self.assertRaisesRegex(ValueError,'Non-monotonic'):axes.sdl_cutoff_covered(bad,1000000,4)
            else:self.assertFalse(axes.sdl_cutoff_covered(bad,1000000,4))

    def run_actual_poll(self,late_invalid,scenario=None):
        class HostStop(Exception):pass
        native,samples,_=fixture()
        initial=[native[0]]+[x for x in native if x['event']=='axis_state' and x['qpc']<=4100000]
        control=dict(rows=initial,samples=[dict(samples[0],elapsed_us=100000)],clock=.5,mono=0.)
        guide=Mock();observer=Mock(returncode=0);observer.poll.return_value=None;result={}
        window_state=Mock(window=123,pid=456);first=RuntimeError('FIRST identity');first.winerror=1400
        with tempfile.TemporaryDirectory() as temp,ExitStack() as stack:
            out=Path(temp);(out/'physical-ready.txt').write_text('host stub')
            source=out/'inert-fixture';source.write_bytes(b'not executable')
            args=SimpleNamespace(output=out,fixture=source,engine=out/'never-engine',engine_report=out/'never-report',
                                 supervisor=out/'never-supervisor',sdl_observer=out/'never-observer')
            def prepare(work):(work/'user/screenshots').mkdir(parents=True)
            def supervise(*args,**kwargs):
                poll=args[4];kwargs['on_started'](123)
                poll()  # Bind/instruct, with insufficient guest duration; no capture.
                control['samples']=samples[:32];control['clock']=4.2
                (out/'session/user/screenshots/original.png').write_bytes(b'inert')
                self.assertFalse(poll())  # PNG verified; existing SDL snapshot ends before frozen cutoff.
                self.assertEqual(result.get('phases',[]),[])
                self.assertEqual(guide.finish.call_count,0)
                rows=copy.deepcopy(initial)
                rows += [dict(event='axis_state',qpc=4150000,connected=True,buttons=0,
                              axes=[2184,0,0,0] if late_invalid else [0]*4),
                         dict(event='axis_state',qpc=4300000,connected=True,buttons=0,axes=[0]*4)]
                if scenario=='stale':
                    rows=copy.deepcopy(initial)+[dict(event='axis_state',qpc=4900000,connected=True,buttons=0,axes=[0]*4)]
                if scenario=='malformed':
                    rows=copy.deepcopy(initial)+[dict(event='axis_state',qpc=4300000,connected=True,buttons=0,axes=[])]
                if scenario=='after_cutoff': rows[-1]['axes']=[2184,0,0,0]
                if scenario=='missing': rows=copy.deepcopy(initial)
                control['rows']=rows;control['clock']=4.4
                if scenario=='observer_exit': observer.poll.return_value=7
                if scenario=='ownership': window_state.poll.side_effect=first
                poll()  # Shared final rule must reject late bad input before guide advance.
                if scenario=='missing':
                    self.assertEqual(result.get('phases',[]),[])
                    control['mono']=541.
                    poll()
                raise HostStop()
            patches=[patch.object(runner.startup,'verify_inputs',return_value={}),
                     patch.object(runner.startup,'prepare_session',side_effect=prepare),
                     patch.object(runner.startup,'supervise',side_effect=supervise),
                     patch.object(runner.subprocess,'Popen',return_value=observer),
                     patch.object(runner.startup,'read_events',return_value=[]),
                     patch.object(runner.axes,'progress',side_effect=lambda _:dict(running_observed=True,samples=control['samples'])),
                     patch.object(runner,'read_lines',side_effect=lambda _:control['rows']),
                     patch.object(runner.windows,'_owned_window',return_value=(123,456,789)),
                     patch.object(runner,'OwnedWindowTrace',return_value=window_state),patch.object(runner,'finish_observation'),
                     patch.object(runner,'readback_ready',return_value=True),
                     patch.object(runner.axes,'image_sequence',return_value=31),
                     patch.object(runner.axes,'verify_image',return_value=dict(sequence=31,pixels_verified=230400)),
                     patch.object(runner.time,'perf_counter',side_effect=lambda:control['clock']),
                     patch.object(runner.time,'monotonic',side_effect=lambda:control['mono'])]
            for replacement in patches:stack.enter_context(replacement)
            rejected=scenario in ('stale','malformed','missing','observer_exit','ownership') or late_invalid
            if rejected:
                message={'stale':'gap spans frozen cutoff','malformed':'Malformed','missing':'540-second','observer_exit':'observer stopped','ownership':'FIRST identity'}.get(scenario,'Missing sustained')
                with self.assertRaisesRegex(ValueError,message) as caught:runner.run(args,result,guide,Mock())
                if scenario=='ownership':
                    self.assertIs(caught.exception.__cause__,first)
                    self.assertEqual(caught.exception.winerror,1400)
                    self.assertEqual(result['failure']['winerror'],1400)
                    self.assertEqual(result['failure']['phase'],'poll')
                self.assertEqual(result['phases'],[])
            else:
                with self.assertRaises(HostStop):runner.run(args,result,guide,Mock())
                self.assertEqual(len(result['phases']),1)
                self.assertEqual(result['phases'][0]['capture_qpc_seconds'],4.2)
                self.assertEqual(result['phases'][0]['capture_qpc_ticks'],4200000)
            # Only synthetic local files and stubs were used; no native process/UI.
            history=(out/'host-trace.jsonl').read_text()
            self.assertIn('capture_waiting_for_sdl',history)
            self.assertEqual(history.count('"event": "image_verified"'),0 if rejected else 1)

    def test_actual_poll_ownership_retains_object_and_code(self):self.run_actual_poll(False,'ownership')

    def test_actual_poll_stale_gap_rejects(self):self.run_actual_poll(False,'stale')
    def test_actual_poll_malformed_witness_rejects(self):self.run_actual_poll(False,'malformed')
    def test_actual_poll_missing_witness_deadline(self):self.run_actual_poll(False,'missing')
    def test_actual_poll_observer_exit_while_pending(self):self.run_actual_poll(False,'observer_exit')
    def test_actual_poll_valid_after_cutoff_direction_irrelevant(self):self.run_actual_poll(False,'after_cutoff')

    def test_actual_runner_waits_for_coverage_then_rejects_before_advance(self):self.run_actual_poll(True)
    def test_actual_runner_waits_for_coverage_then_accepts_same_fixed_cutoff(self):self.run_actual_poll(False)


class CoverageBlockerTests(unittest.TestCase):
    def state(self,tick,**changes):
        return dict(event='axis_state',qpc=tick,axes=[0]*4,connected=True,buttons=0,**changes)

    def test_original_gap_examples_rejected_in_live_and_final(self):
        for last,cutoff,after in ((4.1,4.2,4.9),(24.1,24.8,25.0)):
            rows=[self.state(round(last*1000000)),self.state(round(after*1000000))]
            with self.assertRaisesRegex(ValueError,'gap spans'):axes.sdl_cutoff_covered(rows,1000000,cutoff)
        native,samples,phases=fixture();phases[5]['capture_qpc_seconds']=24.8
        with self.assertRaisesRegex(ValueError,'gap spans'):axes.verify_phases(native,samples,phases)

    def test_exact_and_integer_035_boundary(self):
        for delta,valid in ((350000,True),(350001,False)):
            rows=[self.state(4100000),self.state(4100000+delta)]
            if valid:self.assertTrue(axes.sdl_cutoff_covered(rows,1000000,4.2))
            else:
                with self.assertRaisesRegex(ValueError,'gap spans'):axes.sdl_cutoff_covered(rows,1000000,4.2)
        self.assertTrue(axes.sdl_cutoff_covered([self.state(4200000)],1000000,4.2))
        self.assertFalse(axes.sdl_cutoff_covered([self.state(4199999)],1000000,4.2))
        self.assertTrue(axes.sdl_cutoff_covered([self.state(4199999),self.state(4200001)],1000000,4.2))

    def test_historical_native_tick_recovery(self):
        cutoff=85125.7320741;tick=851257320741
        self.assertEqual(axes.qpc_cutoff_ticks(10000000,cutoff),tick)
        for value,covered in ((tick-1,False),(tick,True)):
            self.assertEqual(axes.sdl_cutoff_covered([self.state(value)],10000000,cutoff),covered)
        with self.assertRaisesRegex(ValueError,'Inconsistent'):axes.qpc_cutoff_ticks(10000000,cutoff,tick+1)

    def test_raw_malformed_witnesses_cannot_be_skipped(self):
        bads=[dict(axes=v) for v in ([],[0]*3,[0]*5,[False,0,0,0],[0.,0,0,0],[-32769,0,0,0],[32768,0,0,0])]
        bads += [dict(buttons=v) for v in (False,0.,-1,0x100000000)]
        bads += [dict(connected=v) for v in (1,None,False)]
        for change in bads:
            row=self.state(4300000);row.update(change)
            rows=[self.state(4100000),json.loads(json.dumps(row)),self.state(4400000)]
            with self.subTest(change=change),self.assertRaises(ValueError):axes.sdl_cutoff_covered(rows,1000000,4.2)
        with self.assertRaisesRegex(ValueError,'Unknown SDL'):
            axes.sdl_cutoff_covered([dict(event='axis_state_typo',qpc=4300000)],1000000,4.2)
        for missing in ('axes','buttons','connected','qpc'):
            row=self.state(4300000);del row[missing]
            with self.assertRaises(ValueError):axes.sdl_cutoff_covered([self.state(4100000),row],1000000,4.2)

    def test_impossible_clock_and_native_timestamp_values(self):
        for frequency in (0,-1,True,1000000.,float('inf'),0x8000000000000000):
            with self.assertRaises(ValueError):axes.sdl_cutoff_covered([],frequency,4.2)
        for cutoff in (0,-1,True,float('nan'),float('inf'),1e30):
            with self.assertRaises(ValueError):axes.sdl_cutoff_covered([],1000000,cutoff)
        for tick in (0,-1,False,4300000.,0x8000000000000000):
            row=self.state(tick)
            with self.assertRaises(ValueError):axes.sdl_cutoff_covered([self.state(4100000),row],1000000,4.2)

    def test_opened_identity_contract_is_required(self):
        for field,value in (('instance_id',0),('virtual',True),('connection','wireless'),('vendor',True),('qpc_frequency',True)):
            native,samples,phases=fixture();native[0][field]=value
            with self.assertRaises(ValueError):axes.verify_capture(native[0],native,samples,phases[0])

    def test_raw_duplicate_json_members_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'rows.jsonl';p.write_text('{"event":"axis_state","qpc":1,"qpc":2}\n')
            with self.assertRaisesRegex(ValueError,'Duplicate SDL'):runner.read_lines(p)
            p.write_text('{"event":"axis_state"')
            self.assertEqual(runner.read_lines(p),[])  # Pending writer's incomplete tail cannot certify a cutoff.


class OwnershipBlockerTests(unittest.TestCase):
    def report(self,first,discovery=None,emission=None):
        result=dict(supervision_diagnostics=dict(primary_failure=None,secondary_failures=[],secondary_dropped=0))
        state=Mock(window=123,pid=456);emit=Mock(side_effect=emission)
        with patch.object(runner.windows,'_owned_window',side_effect=discovery,return_value=(1,123,456)):
            try:
                raise first
            except RuntimeError as primary:
                runner.ownership_postmortem(primary,state,1,Path('inert'),emit,result)
                self.assertIs(primary,first)
        return result

    def test_original_object_code_phase_and_secondary_provenance(self):
        first=RuntimeError('FIRST identity');first.winerror=1400
        r=self.report(first,emission=OSError(5,'SECOND postmortem write'))
        self.assertEqual(r['failure']['message'],'FIRST identity');self.assertEqual(r['failure']['phase'],'poll')
        self.assertEqual(r['failure']['winerror'],1400)
        self.assertEqual(r['cleanup_failures'][0]['phase'],'window_identity_postmortem_emit')
        self.assertEqual(r['supervision_diagnostics']['secondary_failures'][0]['errno'],5)

    def test_multiple_secondary_errors_and_successful_emission(self):
        first=RuntimeError('FIRST identity')
        r=self.report(first,OSError(2,'SECOND discovery'),OSError(5,'THIRD emission'))
        self.assertEqual(r['failure']['message'],'FIRST identity')
        self.assertEqual([x['phase'] for x in r['cleanup_failures']],['window_identity_postmortem_discovery','window_identity_postmortem_emit'])
        r=self.report(first);self.assertNotIn('cleanup_failures',r)

    def test_metadata_failure_still_cannot_replace_original(self):
        first=RuntimeError('FIRST identity');first.winerror=1400
        with patch.object(runner.startup,'failure_details',side_effect=OSError(5,'metadata')):
            r=self.report(first,emission=OSError(6,'emit'))
        self.assertEqual(r['failure']['message'],'FIRST identity');self.assertEqual(r['failure']['winerror'],1400)
        self.assertEqual(len(r['cleanup_failures']),2)
        self.assertEqual(r['cleanup_failures'][-1]['errno'],6)

    def test_actual_supervisor_preserves_poll_cause_codes_and_final_result(self):
        first=RuntimeError('FIRST identity');first.winerror=1400
        result=dict(supervision_diagnostics={});details=result['supervision_diagnostics']
        state=Mock(window=123,pid=456);emit=Mock(side_effect=OSError(5,'SECOND emission'))
        def poll():
            runner.ownership_postmortem(first,state,1,Path('inert'),emit,result)
            rejection=ValueError(str(first));rejection.winerror=first.winerror
            raise rejection from first
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp);(out/'supervisor.json').write_text(json.dumps(dict(schema_version=1,tree_cleanup=True,root_exit_verified=True)))
            child=Mock(returncode=0,pid=123);child.poll.side_effect=[None,0,0]
            with patch.object(runner.startup.subprocess,'Popen',return_value=child),patch.object(runner.startup.time,'sleep'),patch.object(runner.windows,'_owned_window',return_value=(1,123,456)):
                with self.assertRaises(ValueError) as caught:
                    runner.startup.supervise(Path('never-supervisor'),['never-engine'],out,1,poll,diagnostics=details)
            self.assertIs(caught.exception.__cause__.__cause__,first)
            self.assertEqual(details['primary_failure']['message'],'FIRST identity')
            self.assertEqual(details['primary_failure']['winerror'],1400)
            self.assertEqual(details['secondary_failures'][0]['phase'],'window_identity_postmortem_emit')
            runner._set_failure(result,caught.exception,'axes_session')
            runner.finalize_result(out,result,Mock(),first)
            published=json.loads((out/'result.json').read_text())
            self.assertEqual(published['failure']['type'],'RuntimeError')
            self.assertEqual(published['failure']['winerror'],1400)
            self.assertEqual(published['cleanup_failures'][0]['errno'],5)

    def test_publication_error_without_ownership_is_primary(self):
        # The ownership helper has no no-prior-error path; unrelated write errors
        # remain the first poll error in the actual supervisor, not swallowed.
        first=OSError(5,'FIRST publication');details={}
        def poll():raise first
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp);(out/'supervisor.json').write_text(json.dumps(dict(schema_version=1,tree_cleanup=True,root_exit_verified=True)))
            child=Mock(returncode=0,pid=123);child.poll.side_effect=[None,0,0]
            with patch.object(runner.startup.subprocess,'Popen',return_value=child),patch.object(runner.startup.time,'sleep'):
                with self.assertRaises(ValueError) as caught:
                    runner.startup.supervise(Path('never-supervisor'),['never-engine'],out,1,poll,diagnostics=details)
            self.assertIs(caught.exception.__cause__,first)
            self.assertEqual(details['primary_failure']['message'],str(first))
            self.assertEqual(details['primary_failure']['errno'],5)


class RationalQpcTests(unittest.TestCase):
    cases=((10000000,2684354560000011,-1),(1000000000,4194304000000005,-1),
           (10000000,2684354560000017,1),(1000000000,4194304000000007,1))

    def state(self,tick,axes_value=None):
        return dict(event='axis_state',qpc=tick,axes=[0]*4 if axes_value is None else axes_value,
                    buttons=0,connected=True)

    def test_four_double_rounding_cases_and_saved_ticks(self):
        for frequency,tick,old_delta in self.cases:
            with self.subTest(frequency=frequency,tick=tick):
                cutoff=tick/frequency
                self.assertEqual(round(cutoff*frequency),tick+old_delta)
                self.assertEqual(axes.qpc_cutoff_ticks(frequency,cutoff),tick)
                self.assertEqual(axes.qpc_cutoff_ticks(frequency,cutoff,tick),tick)
                for wrong in (tick-1,tick+1,True,float(tick)):
                    with self.assertRaisesRegex(ValueError,'Inconsistent'):
                        axes.qpc_cutoff_ticks(frequency,cutoff,wrong)

    def test_exact_rational_ties_even_and_integral_cutoffs(self):
        for cutoff,frequency,expected in ((1.25,10,12),(1.75,10,18),(5,1000000000,5000000000),
                                           (9007199254740993,1,9007199254740993),
                                           (0x7fffffffffffffff,1,0x7fffffffffffffff)):
            self.assertEqual(axes.qpc_cutoff_ticks(frequency,cutoff),expected)

    def test_high_clock_exact_and_bracket_gap_boundaries(self):
        for frequency,tick,_ in self.cases:
            cutoff=tick/frequency
            self.assertTrue(axes.sdl_cutoff_covered([self.state(tick)],frequency,cutoff))
            self.assertFalse(axes.sdl_cutoff_covered([self.state(tick-1)],frequency,cutoff))
            for delta in (-1,0,1):
                before=tick-frequency//10
                rows=[self.state(before),self.state(before+frequency*7//20+delta)]
                if delta<=0:self.assertTrue(axes.sdl_cutoff_covered(rows,frequency,cutoff))
                else:
                    with self.assertRaisesRegex(ValueError,'gap spans'):
                        axes.sdl_cutoff_covered(rows,frequency,cutoff)

    def test_exact_cutoff_bad_input_and_strictly_later_movement(self):
        for frequency,tick,_ in self.cases:
            native,samples,phases=fixture();qualified=phases[0]
            qualified.update(instruction_qpc_seconds=tick/frequency-3.2,capture_qpc_seconds=tick/frequency)
            opened=dict(native[0],qpc_frequency=frequency)
            held=[self.state(tick-(31-j)*frequency//10-1) for j in range(32)]
            for offset,accepted in ((0,False),(1,True)):
                rows=[opened]+held
                if offset:rows.append(self.state(tick))
                rows.append(self.state(tick+offset,[2184,0,0,0]))
                with self.subTest(frequency=frequency,tick=tick,offset=offset):
                    if accepted:axes.verify_capture(opened,rows,samples,qualified)
                    else:
                        with self.assertRaisesRegex(ValueError,'Missing sustained'):
                            axes.verify_capture(opened,rows,samples,qualified)

    def test_precision_type_and_range_guards(self):
        for frequency in (True,0,-1,1.,2**63,None):
            with self.assertRaises(ValueError):axes.qpc_cutoff_ticks(frequency,4.2)
        for cutoff in (True,0,-1,float('nan'),float('inf'),None,'4.2',2**53*1.,1e30):
            with self.assertRaises(ValueError):axes.qpc_cutoff_ticks(10000000,cutoff)
        for cutoff,frequency in ((1,2**63-1),(2**63-1,1)):
            self.assertLessEqual(axes.qpc_cutoff_ticks(frequency,cutoff),2**63-1)
        with self.assertRaisesRegex(ValueError,'Invalid QPC capture tick'):
            axes.qpc_cutoff_ticks(2,2**63-1)
        with self.assertRaises(ValueError):axes.qpc_cutoff_ticks(1,.1)

    def test_full_production_runner_and_final_reject_both_false_acceptances(self):
        from pad_axes_qpc_fixture import full_run
        for frequency,tick,_ in self.cases[:2]:
            with self.subTest(frequency=frequency),tempfile.TemporaryDirectory() as temp:
                out=Path(temp)
                good=out/'valid';good.mkdir()
                result,rows,samples,guide,error=full_run(good,frequency,tick)
                self.assertIsNone(error)
                self.assertEqual(result['physical_verification']['qualified_phases'],17)
                self.assertEqual(len(result['phases']),17)
                self.assertEqual(guide.finish.call_count,1)
                first=result['phases'][0]
                self.assertEqual(first['capture_qpc_seconds'],tick/frequency)
                self.assertEqual(first['capture_qpc_ticks'],tick)
                # Replay the complete accepted journal/17 candidates through
                # the actual final validator with the original bad boundary row.
                bad_rows=copy.deepcopy(rows)
                next(r for r in bad_rows if r['event']=='axis_state' and r['qpc']==tick)['axes']=[2184,0,0,0]
                with self.assertRaisesRegex(ValueError,'Missing sustained'):
                    axes.verify_phases(bad_rows,samples,result['phases'])
                bad=out/'bad-at-cutoff';bad.mkdir()
                rejected,_,_,guide,error=full_run(bad,frequency,tick,True)
                self.assertIsInstance(error,ValueError)
                self.assertIn('Missing sustained',str(error))
                self.assertEqual(rejected['phases'],[])
                self.assertEqual(guide.finish.call_count,0)


if __name__=='__main__':unittest.main(verbosity=2)
