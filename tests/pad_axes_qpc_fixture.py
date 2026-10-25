# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
"""Inert boundaries around the real 17-phase runner, parser and image/final rules."""
import json
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from videoout_tests import png, unfiltered
import pad_axes_evidence as axes
import dualsense_axes_guest_tests as runner


def full_run(out, frequency, tick, bad_at_cutoff=False):
    (out/'physical-ready.txt').write_text('inert host fixture')
    source=out/'inert-fixture';source.write_bytes(b'not executable')
    args=SimpleNamespace(output=out,fixture=source,engine=out/'never-engine',
                         engine_report=out/'never-report',supervisor=out/'never-supervisor',
                         sdl_observer=out/'never-observer')
    start=tick/frequency-3.2
    rows=[dict(event='opened',qpc=round((start-.1)*frequency),qpc_frequency=frequency,
               instance_id=19,connection='wired',virtual=False,vendor=1356,product=3302)]
    samples=[dict(sequence=0,timestamp=100000,flip=1,axes=[128]*4,buttons=0,connected=1,elapsed_us=100000)]
    clock=dict(qpc=start-.01,mono=0.);last_clock=[None,0]
    observer=Mock(returncode=0);observer.poll.return_value=None
    window=Mock(window=41,pid=42);window.summary.return_value=dict(inert=True)
    guide=Mock();endpoint=Mock();result={}

    def perf():
        if last_clock[0]==clock['qpc']:last_clock[1]+=1
        else:last_clock[:]=[clock['qpc'],1]
        # The next instruction is issued after the frozen capture, even when
        # an exact witness permits credit in the first poll.
        return clock['qpc']+(0.00001 if last_clock[1]>=3 else 0)

    def sync():
        events=[dict(event='configured',strict_imports=True),
                dict(event='imports_checked',phase='entry',unresolved_count=0),
                dict(event='guest_entry'),dict(event='guest_output',text='pad-axes: begin schema=1'),
                dict(event='guest_output',text='pad-axes: ready schema=1')]
        events=[dict(schema_version=1,elapsed_us=i,**e) for i,e in enumerate(events)]
        for s in samples:
            text=(f"pad-axes: sample={s['sequence']} buttons={s['buttons']} timestamp={s['timestamp']} "
                  f"flip={s['flip']} lx={s['axes'][0]} ly={s['axes'][1]} rx={s['axes'][2]} "
                  f"ry={s['axes'][3]} connected={s['connected']}")
            events.append(dict(schema_version=1,elapsed_us=s['elapsed_us'],event='guest_output',text=text))
        (out/'session/startup-audit.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events))
        (out/'physical.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in rows))

    def prepare(work):
        for d in ('user/screenshots','user/data','user/log'):(work/d).mkdir(parents=True)
        sync()

    def drive(*args,**kwargs):
        poll=args[4];kwargs['on_started'](42);poll()
        for i,phase in enumerate(axes.PLAN):
            base=start+4*i;guest=[128]*4;native=[0]*4
            if phase[1] is not None:
                guest[phase[1]]=0 if phase[2]<0 else 255
                native[phase[1]]=phase[2]*30000
                rows.append(dict(event='physical_axis',qpc=round(base*frequency),instance_id=19,
                                 axis=phase[1],value=native[phase[1]]))
            for j in range(32):
                stamp=tick-1 if i==0 and j==31 else round((base+j*.1)*frequency)
                rows.append(dict(event='axis_state',qpc=stamp,axes=native[:],buttons=0,connected=True))
                seq=len(samples);elapsed=1000000+i*4000000+j*100000
                samples.append(dict(sequence=seq,timestamp=elapsed,flip=seq+1,axes=guest[:],
                                    buttons=0,connected=1,elapsed_us=elapsed))
            image=out/'session/user/screenshots'/f'{i:02}.png'
            image.write_bytes(png(unfiltered(axes.expected_pixels(result['palette'],samples[-1]))))
            sync();clock.update(qpc=tick/frequency if i==0 else base+3.2,mono=i*4+3.2)
            poll()  # Freeze candidate; first phase still lacks its publication witness.
            stamp=tick if i==0 else round((base+3.3)*frequency)
            rows.append(dict(event='axis_state',qpc=stamp,axes=[2184,0,0,0] if i==0 and bad_at_cutoff else native[:],
                             buttons=0,connected=True))
            sync();clock.update(qpc=base+3.4,mono=i*4+3.4);poll()
            history=(out/'host-trace.jsonl').read_text()
            assert history.count('"event": "image_verified"')==i+1
        assert guide.finish.call_count==1
        poll()
        (out/'session/user/data/pad-axes.bin').write_bytes(axes.HEADER+b''.join(
            axes.RECORD.pack(s['sequence'],s['buttons'],s['timestamp'],s['flip'],*s['axes'],s['connected']) for s in samples))
        (out/'session/user/log/shad_log.txt').write_text('1 controllers are currently connected\nGamepad registered for slot 0! Handle: 19\n')
        return dict(reason='exited',exit_code=0,forced_termination=False,active_before_cleanup=0,
                    tree_cleanup=True,root_exit_verified=True,owner_watch_verified=True)

    replacements=[patch.object(runner.startup,'verify_inputs',return_value={}),
                  patch.object(runner.startup,'prepare_session',side_effect=prepare),
                  patch.object(runner.startup,'supervise',side_effect=drive),
                  patch.object(runner.subprocess,'Popen',return_value=observer),
                  patch.object(runner.windows,'_owned_window',return_value=(Mock(),41,42)),
                  patch.object(runner,'OwnedWindowTrace',return_value=window),
                  patch.object(runner,'readback_ready',return_value=True),
                  patch.object(runner.time,'perf_counter',side_effect=perf),
                  patch.object(runner.time,'monotonic',side_effect=lambda:clock['mono'])]
    error=None
    with ExitStack() as stack:
        for replacement in replacements:stack.enter_context(replacement)
        try:runner.run(args,result,guide,endpoint)
        except ValueError as caught:error=caught
    assert observer.wait.called and window.close.called
    return result,rows,samples,guide,error
