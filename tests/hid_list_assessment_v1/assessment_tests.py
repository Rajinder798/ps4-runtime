# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
"""HOST TEST property bytes, fixed-output privacy and frozen policy cross-checks."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools'))
import pnp_coverage_v2 as frozen
DRIVER = Path(sys.argv.pop(1)).resolve()

def units(text):
    return ''.join(f'{int.from_bytes(text[i:i+2], "little"):04x}' for i in range(0, len(text), 2))

class PropertyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(os.environ.get('HID_V1_EVIDENCE', cls.tmp.name))/'property'
        cls.out.mkdir(parents=True, exist_ok=False)
        result = subprocess.run([str(DRIVER)], capture_output=True, timeout=20)
        (cls.out/'native.stdout').write_bytes(result.stdout)
        (cls.out/'native.stderr').write_bytes(result.stderr)
        if result.returncode: raise AssertionError('native property fixture failed; output preserved')
        cls.policies = cls.out/'policy'
        subprocess.run([str(DRIVER), '--policy-dir', str(cls.policies)], check=True, capture_output=True, timeout=20)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def assess(self, text=b'\0\0', *, code=0, type_=0x2012, declared=None):
        result = subprocess.run([str(DRIVER), '--raw', str(code), str(type_),
                                 str(len(text) if declared is None else declared), units(text)],
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        row = json.loads(result.stdout)
        self.assertEqual(set(row), {'schema','origin','assessment','identity','entries','first_issue',
                                   'first_context','own_target_hid','readiness_granted','recovery_accepted'})
        self.assertEqual(row['schema'], 'hid-list-assessment-v1')
        self.assertEqual(row['origin'], 'HOST TEST')
        self.assertFalse(row['readiness_granted'] or row['recovery_accepted'])
        return row

    def test_six_public_strings_are_synthetic_and_full_list_vetoes_apply(self):
        values = ['HID\\VID_054C&PID_0CE6&REV_0100&MI_03', 'HID\\VID_054C&PID_0CE6&MI_03',
                  'HID\\VID_054C&UP:0001_U:0005', 'HID_DEVICE_UP:0001_U:0005', 'HID_DEVICE', 'HID_DEVICE']
        payload = ('\0'.join(values)+'\0\0').encode('utf-16le')
        a = self.assess(payload)
        self.assertEqual((a['entries'],a['first_context'],a['own_target_hid']), (6,2,True))
        for extra,expected in [('UNSUPPORTED_PRIVATE_SERIAL','unsupported'),
                               ('HID\\VID_054C&PID_0001&MI_03','conflicting'),
                               ('HID\\VID_054C&PID_0CE6&MI_03&MI_03','malformed')]:
            b = self.assess(('\0'.join(values+[extra])+'\0\0').encode('utf-16le'))
            self.assertEqual(b['assessment'], expected)
            self.assertFalse(b['own_target_hid'])
            self.assertEqual(b['identity'], 'none')

    def test_api_type_length_encoding_and_termination_precedence(self):
        self.assertEqual(self.assess(code=13, type_=0, declared=999999)['assessment'], 'property_api_failure')
        self.assertEqual(self.assess(type_=0, declared=999999)['assessment'], 'invalid_property_type')
        self.assertEqual(self.assess(declared=16386)['assessment'], 'property_limit')
        self.assertEqual(self.assess(declared=1)['assessment'], 'invalid_property_length')
        self.assertEqual(self.assess(b'\x00\xd8\0\0\0\0')['assessment'], 'invalid_utf16')
        self.assertEqual(self.assess('ABC\0'.encode('utf-16le'))['assessment'], 'invalid_multisz_termination')

    def test_empty_property_and_partial_context_never_identify_product(self):
        for data in (b'\0\0', b'\0\0\0\0'):
            self.assertEqual(self.assess(data)['assessment'], 'empty')
        p = self.assess('HID\\VID_054C&UP:0001_U:0005\0\0'.encode('utf-16le'))
        self.assertEqual(p['assessment'], 'partial_context_without_product')
        self.assertFalse(p['own_target_hid'])

    def test_arbitrary_identifiers_never_escape_categories(self):
        secrets = ['PRIVATE-DEVICE-SERIAL-11:22:33:44', 'HID\\VID_1234&PID_ABCD', '\\?\\PRIVATE_PATH']
        for secret in secrets:
            out = self.assess((secret+'\0\0').encode('utf-16le'))
            encoded = json.dumps(out)
            for forbidden in ('PRIVATE','SERIAL','1234','ABCD','PATH'):
                self.assertNotIn(forbidden, encoded)

    def test_bounded_raw_input_cli_fails_without_echo(self):
        for arg in ('PRIVATE_INPUT', 'zzzz'):
            r = subprocess.run([str(DRIVER),'--raw','0','8210','2',arg], capture_output=True,text=True,timeout=5)
            self.assertNotEqual(r.returncode,0)
            self.assertEqual(r.stdout,'')
            self.assertEqual(r.stderr.strip(),'HOST TEST failed')
        r=subprocess.run([str(DRIVER),'--raw-stdin','0','8210','2'],input='0'*32772,
                         capture_output=True,text=True,timeout=5)
        self.assertNotEqual(r.returncode,0)
        self.assertEqual(r.stdout,'')
        self.assertEqual(r.stderr.strip(),'HOST TEST failed')

    def test_property_to_frozen_policy_requires_independent_status_and_coverage(self):
        paths = list(self.policies.glob('*.jsonl'))
        self.assertEqual(len(paths),11)
        for path in paths:
            rows=frozen.load(path); verdict=frozen.validate(rows,allow_host_test=True,require_complete=False)
            snapshot=next(r for r in rows if r['event']=='snapshot')
            self.assertEqual(snapshot['initial_ready'],path.stem=='hypothetical-complete-proof',path.stem)
            self.assertFalse(verdict['recovery_accepted'])
            if path.stem=='syntax-only-status-unknown':
                node=next(r for r in rows if r['event']=='devnode' and r['role']=='hid_child')
                self.assertEqual((node['started'],node['status_code']),(-1,0xffffffff))

    def test_frozen_live_surfaces_have_exact_baseline_sources(self):
        import hashlib
        config=json.loads((ROOT/'config/pnp-snapshot-v1.json').read_text(encoding='utf-8'))
        self.assertEqual(len(config['frozen_source_lf_sha256']),39)
        for name,expected in config['frozen_source_lf_sha256'].items():
            actual=hashlib.sha256((ROOT/name).read_bytes().replace(b'\r\n',b'\n')).hexdigest()
            self.assertEqual(actual,expected,name)

    def test_host_driver_has_no_live_mode(self):
        for flag in ('--run-initial-snapshot','--authorize-one-initial-snapshot','--watch','--live'):
            r=subprocess.run([str(DRIVER),flag],capture_output=True,timeout=5)
            self.assertEqual(r.returncode,2)
            self.assertEqual(r.stdout,b'')

if __name__=='__main__': unittest.main()
