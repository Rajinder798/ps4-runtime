# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
"""Replay original physical-001 output. No guest, controller, window or audio access."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'tools'), str(ROOT/'tests')]
import pad_hotplug_evidence as hp
import pad_disconnected_close_evidence as dc
import run_homebrew_startup as startup
from hotplug_endpoint import validate_report

EVIDENCE = ROOT/'research/evidence/2026-10-21-disconnected-close'
RUN = EVIDENCE/'physical-001'


def read(path): return json.loads(path.read_text(encoding='utf-8-sig'))
def lines(path): return [json.loads(s) for s in path.read_text(encoding='utf-8-sig').splitlines()]
def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def collected():
    q = read(RUN/'qualification.json')
    samples = hp.progress(startup.read_events(RUN/'guest-audit.jsonl', final=True))['samples']
    return q, samples, lines(RUN/'native.jsonl')


class RecordedCloseTests(unittest.TestCase):
    def test_original_hashes_and_failed_unmuted_preflight_remain_distinct(self):
        manifest = read(EVIDENCE/'manifest.json')
        self.assertEqual(manifest['physically_tested_commit'], 'd7ef5df24b310962b60fd8de17a68cb05a4a79ff')
        for item in manifest['artifacts']:
            path = (EVIDENCE/item['published']).resolve()
            self.assertTrue(path.is_relative_to(EVIDENCE.resolve()))
            self.assertEqual(path.stat().st_size, item['size'])
            self.assertEqual(digest(path), item['sha256'])
            self.assertNotIn(path.suffix.lower(), ('.exe', '.oelf', '.elf', '.dll', '.lib', '.obj'))
        failed = read(EVIDENCE/'preflight-001/status.json')
        self.assertEqual(failed['status'], 'failed'); self.assertFalse(failed['guest_launched'])
        self.assertFalse(lines(EVIDENCE/'preflight-001/endpoint.jsonl')[0]['endpoints'][0]['muted'])
        passed = read(EVIDENCE/'preflight-002/status.json')
        self.assertEqual(passed['status'], 'passed'); self.assertFalse(passed['guest_launched'])
        self.assertTrue(passed['endpoint']['every_available_tracked_endpoint_muted'])

    def test_actual_607_records_original_journal_and_three_exact_images(self):
        q, samples, _ = collected()
        binary = hp.verify_records((RUN/'journal.bin').read_bytes(), samples)
        self.assertEqual((binary['records'], binary['bytes_verified']), (607, 43720))
        dc.verify_images(RUN, bytes(q['palette']), samples, q['phases'])
        self.assertEqual(len(q['phases']), 3)
        self.assertEqual([p['sequence'] for p in q['phases']], [89, 310, 393])
        absent = [s for s in samples if s['state'] == hp.DISCONNECTED]
        self.assertEqual(len(absent), 354)
        self.assertEqual({s['handle'] for s in samples}, {1})
        self.assertEqual({s['rc'] for s in samples}, {0})
        for s in absent:
            self.assertEqual((s['connected'], s['timestamp'], s['raw_axes']), (0, 0, [0]*4))
            self.assertEqual((s['effective_axes'], s['effective_buttons'], s['audio_command']), ([128]*4, 0, 0))
        a, b = (samples[q['phases'][i]['sequence']] for i in (1, 2))
        self.assertEqual(b['observed_us']-a['observed_us'], 9683422)
        self.assertEqual((a['flip'], b['flip'], a['audio_blocks'], b['audio_blocks']), (311, 394, 850, 1077))

    def test_actual_removal_human_close_ownership_mute_and_empty_process_tree(self):
        q, samples, native = collected()
        result = dc.verify(native, samples, q['phases'], q['close'], read(RUN/'supervisor.json'), disconnect_authorized=True)
        self.assertEqual((result['removals'], result['reconnections']), (1, 0))
        dc.verify_confirmations(lines(RUN/'human-confirmations.jsonl'), q['phases'], q['close'])
        endpoint = validate_report(RUN/'endpoint.jsonl')
        self.assertEqual((endpoint['samples'], endpoint['default_changes']), (2426, 0))
        trace = lines(RUN/'window-trace.jsonl')
        self.assertFalse(any(r['event'] in ('test_failure', 'owned_window_identity_failure', 'owned_window_state_query_failure') for r in trace))
        destroyed = [r for r in trace if r['event'] == 'owned_process_window_event' and r['kind'] == 'destroy' and r['bound_window']]
        self.assertTrue(destroyed)
        self.assertTrue(all(r['received_qpc_seconds'] > q['close']['instruction_qpc_seconds'] for r in destroyed))
        self.assertLess(q['close']['root_exit_qpc_seconds']-q['close']['instruction_qpc_seconds'], 30)
        snapshot = next(r for r in trace if r['event'] == 'owned_window_identity_snapshot' and r['reason'] == 'supervision_finished')
        self.assertEqual((snapshot['process_wait_result'], snapshot['process_exit_code']), (0, 0))
        post = read(RUN/'postflight.json')
        self.assertEqual((post['conflicting_process_count'], post['present_dualsense_interface_count']), (0, 0))
        review = read(RUN/'engine-review.json')
        self.assertEqual(dc.verify_engine('\n'.join(review['controller_lines']))['slots'], [0])
        self.assertEqual(len(review['error_labelled_messages']), 6)
        self.assertEqual(review['new_warning_messages'], [])

    def test_tested_runner_guide_observer_and_acceptance_sources_unchanged(self):
        attestation = read(RUN/'attestation.json')
        self.assertEqual(len(attestation['source_sha256']), 17)
        for name, expected in attestation['source_sha256'].items():
            snapshot = RUN/'tested-source'/name
            self.assertEqual(digest(snapshot), expected)
            current_lf = (ROOT/name).read_bytes().replace(b'\r\n', b'\n')
            self.assertEqual(hashlib.sha256(current_lf).hexdigest(), attestation['source_lf_sha256'][name])
        self.assertEqual(attestation['inputs']['engine']['sha256'], 'c41da6f5a27a8215b816c2215c3c830c6726d461f44791423f49daec9f0571ba')
        self.assertEqual(attestation['inputs']['fixture']['sha256'], 'bde543dc632bb3c39b152a459e44249c2ae8c299a0a176b660ed0f3228414535')

    def test_corrupted_actual_evidence_cannot_pass_replay(self):
        q, samples, native = collected()
        for kind in ('forced', 'reconnected', 'api', 'short-progress', 'missing-confirmation'):
            with self.subTest(kind=kind):
                s = copy.deepcopy(samples); n = copy.deepcopy(native); p = copy.deepcopy(q['phases'])
                t = copy.deepcopy(q['transport'])
                if kind == 'forced': t['forced_termination'] = True
                elif kind == 'reconnected': n.insert(-1, copy.deepcopy(n[1]))
                elif kind == 'api': s[-1].update(rc=-1, payload_valid=0, state=hp.API_ERROR, flip=0)
                elif kind == 'short-progress': p[2]['sequence'] = p[1]['sequence']+40
                else:
                    rows = lines(RUN/'human-confirmations.jsonl')[:-1]
                    with self.assertRaises(ValueError): dc.verify_confirmations(rows, p, q['close'])
                    continue
                with self.assertRaises(ValueError):
                    dc.verify(n, s, p, q['close'], t, disconnect_authorized=True)
        with self.assertRaises(ValueError): hp.verify_records((RUN/'journal.bin').read_bytes()[:-1], samples)
        with self.assertRaises(ValueError):
            hp.verify_image(RUN/q['phases'][0]['path'], bytes(q['palette']), samples[q['phases'][1]['sequence']])


if __name__ == '__main__': unittest.main()
