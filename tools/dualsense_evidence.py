# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
"""Strict physical-input evidence, separate from keyboard and hosted tests."""
import struct
import json
import time


def record_instruction(path, command):
    # Keep the operator's issue time distinct from observation/logging time.
    event = dict(event='human_instruction', monotonic=time.monotonic(), command=command)
    with path.open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(event)+'\n')
    return event


def append_progress(path, snapshot):
    # Test diagnostics are an append-only history, not a replaced runtime state
    # snapshot. Propagate every write error; no publication/test retry.
    with path.open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(dict(monotonic=time.monotonic(), **snapshot))+'\n')

# label, exact guest Pad mask, exact SDL button-state mask
PLAN = [('neutral', 0, 0), ('cross-1-held', 0x4000, 1), ('cross-1-release', 0, 0),
        ('cross-2-held', 0x4000, 1), ('cross-2-release', 0, 0),
        ('circle-held', 0x2000, 2), ('circle-release', 0, 0),
        ('dpad-up-held', 0x10, 1 << 11), ('dpad-up-release', 0, 0),
        ('dpad-down-held', 0x40, 1 << 12), ('dpad-down-release', 0, 0),
        ('dpad-left-held', 0x80, 1 << 13), ('dpad-left-release', 0, 0),
        ('dpad-right-held', 0x20, 1 << 14), ('dpad-right-release', 0, 0)]


def selected_plan(controls):
    if controls not in ('cross', 'buttons'): raise ValueError('Unknown physical controls scope')
    return PLAN[:5] if controls == 'cross' else PLAN


def classify_disconnect(records, result, exit_code, *, authorized, neutral_qualified, observation_seconds):
    transport = result.get('transport', {})
    if (not authorized or not neutral_qualified or not any(r['event']=='removed' for r in records) or
            not transport.get('tree_cleanup') or not transport.get('root_exit_verified')):
        raise ValueError('Missing authorized physical removal/neutral/cleanup evidence')
    rejected = 'live-av: FAIL pad read/connection' in result.get('error','')
    if rejected and exit_code != 0:
        return dict(outcome='guest reported pad read/connection failure',graceful_controller_support_verified=False,
                    forced_cleanup=transport['forced_termination'],reconnect_attempted=False)
    if exit_code == 0 and result.get('normal_exit_verified') and observation_seconds >= 5:
        return dict(outcome='no guest pad-failure marker during bounded observation; human closed game',
                    observation_seconds=observation_seconds,graceful_controller_support_verified=False,
                    forced_cleanup=transport['forced_termination'],reconnect_attempted=False)
    raise ValueError('Unexpected disconnect failure; preserve exact guest error')


def verify_physical(records, samples, raw, captures, *, controls='buttons'):
    plan = selected_plan(controls)
    opened = [r for r in records if r['event'] == 'opened']
    states = [r for r in records if r['event'] == 'state']
    buttons = [r for r in records if r['event'] == 'physical_button']
    if (len(opened) != 1 or opened[0]['connection'] != 'wired' or opened[0]['virtual'] is not False or
            (opened[0]['vendor'], opened[0]['product']) != (0x054c, 0x0ce6) or
            opened[0]['qpc_frequency'] <= 0 or any(r['event'] == 'removed' for r in records) or
            len(states) != len(plan) or not all(s['connected'] is True for s in states) or
            [s['buttons'] for s in states] != [s[2] for s in plan]):
        raise ValueError('Physical wired controller identity/connection/state sequence mismatch')
    expected_events = [(0, True), (0, False), (0, True), (0, False), (1, True), (1, False),
                       (11, True), (11, False), (12, True), (12, False),
                       (13, True), (13, False), (14, True), (14, False)]
    if controls == 'cross': expected_events = expected_events[:4]
    if ([(e['button'], e['down']) for e in buttons] != expected_events or
            any(e['instance_id'] != opened[0]['instance_id'] for e in buttons)):
        raise ValueError('Missing/wrong physical SDL button events')
    times = [e['qpc'] for e in buttons]
    if any(b <= a for a, b in zip(times, times[1:])):
        raise ValueError('Nonmonotonic physical button timestamps')
    holds = [(times[i+1] - times[i]) / opened[0]['qpc_frequency'] for i in (0, 2)]
    if min(holds) < 3:
        raise ValueError('Physical Cross hold shorter than three seconds')
    expected = [(s['sequence'], s['buttons'], s['timestamp'], s['flip']) for s in samples]
    if (len(raw) != 24 * len(plan) or list(struct.iter_unpack('<IIQQ', raw)) != expected or
            [s['sequence'] for s in samples] != list(range(len(plan))) or
            [s['buttons'] for s in samples] != [s[1] for s in plan] or
            min((samples[i+1]['timestamp'] - samples[i]['timestamp']) / 1e6 for i in (1, 3)) < 3 or
            [c['sequence'] for c in captures] != list(range(len(plan))) or
            [c['buttons'] for c in captures] != [s[1] for s in plan]):
        raise ValueError('Physical sequence disagrees with actual guest records/images/held input')
    return dict(cross_two_cycles=True, physical_cross_hold_seconds=holds,
                controls=['Cross'] if controls == 'cross' else ['Cross', 'Circle', 'D-pad up', 'D-pad down', 'D-pad left', 'D-pad right'],
                unverified_controls=['Circle','D-pad','analog sticks'] if controls == 'cross' else ['analog sticks'],
                guest_analog_axes_verified=False, keyboard_injection_performed=False,
                observer_is_separate_from_engine=True)
