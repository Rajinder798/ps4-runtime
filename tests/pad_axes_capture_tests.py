# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
"""Synthetic host qualification regression; no device, guest or GUI execution."""
import copy
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

    def run_actual_poll(self,late_invalid):
        class HostStop(Exception):pass
        native,samples,_=fixture()
        initial=[native[0]]+[x for x in native if x['event']=='axis_state' and x['qpc']<=4100000]
        control=dict(rows=initial,samples=[dict(samples[0],elapsed_us=100000)],clock=.5)
        guide=Mock();observer=Mock(returncode=0);observer.poll.return_value=None;result={}
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
                control['rows']=rows;control['clock']=4.4
                poll()  # Shared final rule must reject late bad input before guide advance.
                raise HostStop()
            patches=[patch.object(runner.startup,'verify_inputs',return_value={}),
                     patch.object(runner.startup,'prepare_session',side_effect=prepare),
                     patch.object(runner.startup,'supervise',side_effect=supervise),
                     patch.object(runner.subprocess,'Popen',return_value=observer),
                     patch.object(runner.startup,'read_events',return_value=[]),
                     patch.object(runner.axes,'progress',side_effect=lambda _:dict(running_observed=True,samples=control['samples'])),
                     patch.object(runner,'read_lines',side_effect=lambda _:control['rows']),
                     patch.object(runner.windows,'_owned_window',return_value=(123,456,789)),
                     patch.object(runner,'OwnedWindowTrace'),patch.object(runner,'finish_observation'),
                     patch.object(runner,'readback_ready',return_value=True),
                     patch.object(runner.axes,'image_sequence',return_value=31),
                     patch.object(runner.axes,'verify_image',return_value=dict(sequence=31,pixels_verified=230400)),
                     patch.object(runner.time,'perf_counter',side_effect=lambda:control['clock'])]
            for replacement in patches:stack.enter_context(replacement)
            if late_invalid:
                with self.assertRaisesRegex(ValueError,'Missing sustained'):runner.run(args,result,guide,Mock())
                self.assertEqual(result['phases'],[])
            else:
                with self.assertRaises(HostStop):runner.run(args,result,guide,Mock())
                self.assertEqual(len(result['phases']),1)
                self.assertEqual(result['phases'][0]['capture_qpc_seconds'],4.2)
            # Only synthetic local files and stubs were used; no native process/UI.
            history=(out/'host-trace.jsonl').read_text()
            self.assertIn('capture_waiting_for_sdl',history)
            self.assertEqual(history.count('"event": "image_verified"'),0 if late_invalid else 1)

    def test_actual_runner_waits_for_coverage_then_rejects_before_advance(self):self.run_actual_poll(True)
    def test_actual_runner_waits_for_coverage_then_accepts_same_fixed_cutoff(self):self.run_actual_poll(False)


if __name__=='__main__':unittest.main(verbosity=2)
