# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
"""Option A sampled evidence only. No endpoint acquisition or device setters."""
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import time
from muted_endpoint import MutedEndpoint as LegacyMutedEndpoint

ROLES = ('console', 'multimedia', 'communications')
LIMIT = 32
IDENTITY_BYTES = 1024
MANIFEST_BYTES = 64 * 1024
REPORT_BYTES = 32 * 1024 * 1024
SAMPLE_LIMIT = 32768
SAMPLE_BOUND_MS = 200
SAMPLE_BOUND_NS = SAMPLE_BOUND_MS * 1_000_000


def unique_members(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate fixed-inventory JSON member')
        result[key] = value
    return result


def invalid_constant(value):
    raise ValueError('Non-finite fixed-inventory JSON number: ' + value)


def identity(value):
    return (type(value) is str and bool(value) and
            len(value.encode('utf-8')) <= IDENTITY_BYTES and
            not any(ord(ch) < 32 for ch in value))


def normalize_inventory(value):
    keys = {'schema_version', 'scope', 'inventory_policy',
            'endpoint_identities', 'default_role_identities'}
    if (type(value) is not dict or set(value) != keys or
            type(value['schema_version']) is not int or value['schema_version'] != 1 or
            value['scope'] != 'all-active-render' or value['inventory_policy'] != 'fixed'):
        raise ValueError('Explicit fixed all-render inventory is required')
    ids, roles = value['endpoint_identities'], value['default_role_identities']
    if (type(ids) is not list or not 1 <= len(ids) <= LIMIT or
            not all(identity(item) for item in ids) or len(set(ids)) != len(ids) or
            type(roles) is not dict or set(roles) != set(ROLES) or
            not all(identity(roles[role]) and roles[role] in ids for role in ROLES)):
        raise ValueError('Incomplete endpoint inventory/default-role identities')
    # Detached primitive copies: a caller cannot change approval while observing.
    return dict(schema_version=1, scope='all-active-render', inventory_policy='fixed',
                endpoint_identities=sorted(ids),
                default_role_identities={role: roles[role] for role in ROLES})


def load_fixed_inventory(path):
    with Path(path).open('rb') as stream:
        data = stream.read(MANIFEST_BYTES + 1)
    if len(data) > MANIFEST_BYTES:
        raise ValueError('Expected endpoint inventory exceeds bounded size')
    return normalize_inventory(json.loads(data.decode('utf-8'),
        object_pairs_hook=unique_members, parse_constant=invalid_constant))


class FixedRenderEvidence:
    """Incremental strict schema-2 fixed-policy reader; failure is sticky.

    Native acquisition span, sample gaps and current latest-sample age are each
    bounded. These are observation limits, never an OS routing exclusion claim.
    """
    def __init__(self, expected, *, started_ns=0):
        normalized = normalize_inventory(expected)
        self.expected_ids = frozenset(normalized['endpoint_identities'])
        self.expected_roles = tuple(normalized['default_role_identities'][r] for r in ROLES)
        self.inventory_sha256 = hashlib.sha256(json.dumps(normalized, sort_keys=True,
            separators=(',', ':')).encode('utf-8')).hexdigest()
        if type(started_ns) is not int or started_ns < 0:
            raise ValueError('Invalid observer start timestamp')
        self.started_ns = started_ns
        self.known, self.volumes = {}, {}
        self.samples = self.offset = self.previous_elapsed = 0
        self.last_started = self.last_finished = 0
        self.max_gap_ns = 0
        self.footer = False
        self.file_identity = None
        self.failure = None

    def _consume(self, row):
        if (type(row) is not dict or type(row.get('schema_version')) is not int or
                row['schema_version'] != 2 or self.footer):
            raise RuntimeError('Wrong/incomplete fixed all-render schema or trailing record')
        event = row.get('event')
        if event == 'failure':
            error = RuntimeError('Fixed all-render observer reported failure')
            error.observer_failure = row
            if row.get('code_domain') == 'HRESULT' and type(row.get('code')) is int:
                error.hresult = row['code']
            raise error
        if event == 'identity':
            if set(row) != {'schema_version', 'event', 'token', 'identity'}:
                raise RuntimeError('Malformed fixed endpoint identity')
            token, name = row['token'], row['identity']
            if (self.samples or type(token) is not int or token != len(self.known) or
                    token >= LIMIT or not identity(name) or name not in self.expected_ids or
                    name in self.known.values()):
                raise RuntimeError('Unexpected/duplicate endpoint identity or inventory addition')
            self.known[token] = name
            return
        if event == 'summary':
            if (set(row) != {'schema_version', 'event', 'inventory_policy', 'status', 'samples'} or
                    row['inventory_policy'] != 'fixed' or row['status'] != 'passed' or
                    type(row['samples']) is not int or row['samples'] != self.samples or self.samples < 2):
                raise RuntimeError('Incomplete/failed fixed all-render footer')
            self.footer = True
            return
        fields = {'schema_version', 'event', 'inventory_policy', 'elapsed_ms',
                  'sample_started_unix_ns', 'unix_ns', 'sample_span_ms', 'default_tokens', 'endpoints'}
        if event != 'sample' or set(row) != fields or row['inventory_policy'] != 'fixed':
            raise RuntimeError('Fixed schema-2 all-render sample contract required')
        stamp, began, ended, span = (row[k] for k in
            ('elapsed_ms', 'sample_started_unix_ns', 'unix_ns', 'sample_span_ms'))
        if (any(type(x) is not int for x in (stamp, began, ended, span)) or stamp < 0 or
                began <= 0 or began < self.started_ns or ended < began or
                ended - began > SAMPLE_BOUND_NS or not 0 <= span <= SAMPLE_BOUND_MS or
                (self.samples and (stamp <= self.previous_elapsed or began < self.last_finished or
                                   began - self.last_started > SAMPLE_BOUND_NS))):
            raise RuntimeError('Stale/replayed/overlong fixed endpoint observation')
        defaults, endpoints = row['default_tokens'], row['endpoints']
        if (type(defaults) is not list or len(defaults) != 3 or
                any(type(t) is not int or t not in self.known for t in defaults) or
                tuple(self.known[t] for t in defaults) != self.expected_roles or
                type(endpoints) is not list or not 1 <= len(endpoints) <= LIMIT or
                set(self.known.values()) != self.expected_ids):
            raise RuntimeError('Fixed endpoint inventory/default-role mismatch')
        seen = set()
        for endpoint in endpoints:
            if type(endpoint) is not dict or set(endpoint) != {'token', 'active', 'muted', 'volume'}:
                raise RuntimeError('Incomplete fixed endpoint state')
            token, scalar = endpoint['token'], endpoint['volume']
            if (type(token) is not int or token not in self.known or token in seen or
                    endpoint['active'] is not True or endpoint['muted'] is not True or
                    type(scalar) not in (int, float) or not math.isfinite(scalar) or not 0 <= scalar <= 1):
                raise RuntimeError('Fixed endpoint unavailable, unmuted or unknown')
            seen.add(token)
            if token in self.volumes and self.volumes[token] != scalar:
                raise RuntimeError('Fixed endpoint volume changed')
            self.volumes[token] = scalar
        if seen != set(self.known):
            raise RuntimeError('Fixed active endpoint removed or missing')
        if self.samples:
            self.max_gap_ns = max(self.max_gap_ns, began - self.last_started)
        self.samples += 1
        if self.samples > SAMPLE_LIMIT:
            raise RuntimeError('Fixed endpoint sample limit exceeded')
        self.previous_elapsed, self.last_started, self.last_finished = stamp, began, ended

    def update(self, path, *, final=False, now_ns=None):
        if self.failure is not None:
            raise self.failure
        try:
            with Path(path).open('rb') as stream:
                stat = os.fstat(stream.fileno())
                current = (stat.st_dev, stat.st_ino)
                if (self.file_identity is not None and current != self.file_identity) or stat.st_size < self.offset:
                    raise RuntimeError('Fixed endpoint evidence replaced or truncated')
                if stat.st_size > REPORT_BYTES:
                    raise RuntimeError('Fixed endpoint evidence exceeds bounded size')
                self.file_identity = current
                stream.seek(self.offset)
                data = stream.read(REPORT_BYTES - self.offset + 1)
            if self.offset + len(data) > REPORT_BYTES:
                raise RuntimeError('Fixed endpoint evidence exceeds bounded size')
            if data and not data.endswith(b'\n'):
                raise RuntimeError('Incomplete fixed endpoint JSON record')
            for line in data.decode('utf-8').splitlines():
                self._consume(json.loads(line, object_pairs_hook=unique_members,
                                        parse_constant=invalid_constant))
            self.offset += len(data)
            now = time.time_ns() if now_ns is None else now_ns
            if (type(now) is not int or not self.samples or now < self.last_finished or
                    now - self.last_started > SAMPLE_BOUND_NS or
                    (final and not self.footer) or (not final and self.footer)):
                raise RuntimeError('Stale/incomplete fixed endpoint observation or unexpected observer end')
            return dict(status='passed' if final else 'observing', scope='all-active-render',
                        inventory_policy='fixed', schema_version=2, samples=self.samples,
                        endpoint_identities=len(self.expected_ids), inventory=sorted(self.expected_ids),
                        default_role_identities=dict(zip(ROLES, self.expected_roles)),
                        expected_inventory_sha256=self.inventory_sha256, muted=True, same_default=True,
                        duration_ms=self.previous_elapsed, max_sample_gap_ms=self.max_gap_ns / 1_000_000,
                        sample_bound_ms=SAMPLE_BOUND_MS,
                        observation='Sequential sampled read-only observations; no instantaneous/acoustic silence or Windows routing exclusion guarantee')
        except Exception as error:
            self.failure = error
            raise


def validate_fixed_report(path, expected, *, started_ns=0, now_ns=None):
    return FixedRenderEvidence(expected, started_ns=started_ns).update(path, final=True, now_ns=now_ns)


class FixedMutedEndpoint(LegacyMutedEndpoint):
    """Explicit Option A adapter. Historical wrappers/readers stay unchanged."""
    def __init__(self, helper, output, *, all_render=True, fixed_inventory):
        if all_render is not True:
            raise ValueError('Fixed inventory requires explicit all-render observation')
        self.report, self.stop, self.ready = (output/name for name in
            ('endpoint.jsonl', 'endpoint-stop.request', 'endpoint-ready.txt'))
        self.all_render = True
        self.fixed_evidence = FixedRenderEvidence(fixed_inventory, started_ns=time.time_ns())
        self.fixed_summary = None
        self._fixed_first = None
        self._fixed_ready = False
        self.cleanup_failures = []
        self.cleanup_confirmed = False
        self.errors = (output/'endpoint-stderr.txt').open('xb')
        try:
            self.child = subprocess.Popen([str(helper.resolve()), '--watch-all-render-fixed',
                str(self.report), str(self.stop), str(self.ready), '600000'],
                stdout=subprocess.DEVNULL, stderr=self.errors)
        except BaseException as primary:
            try:
                self.errors.close()
            except BaseException as secondary:
                from run_live_v2_session import publication_failure_record
                primary.endpoint_cleanup_failures = [publication_failure_record(secondary, 'endpoint_launch_stderr_close')]
            raise

    def _check_child(self):
        if self.child.poll() is None:
            return
        error = RuntimeError('Fixed all-render observer stopped; no automatic audio changes or retries')
        error.observer_exit_code = self.child.returncode
        self._fixed_first = error
        try:
            if self.report.exists():
                with self.report.open('rb') as stream:
                    data = stream.read(REPORT_BYTES+1)
                if len(data)>REPORT_BYTES:
                    raise ValueError('Fixed endpoint failure metadata exceeds byte limit')
                for line in reversed(data.decode('utf-8').splitlines()):
                    row = json.loads(line, object_pairs_hook=unique_members, parse_constant=invalid_constant)
                    if type(row) is dict and row.get('event')=='failure':
                        error.observer_failure = row
                        if row.get('code_domain')=='HRESULT' and type(row.get('code')) is int:
                            error.hresult = row['code']
                        break
        except Exception as metadata_error:
            error.endpoint_metadata_error = type(metadata_error).__name__
            from run_live_v2_session import publication_failure_record
            self.cleanup_failures.append(publication_failure_record(metadata_error,'endpoint_failure_metadata'))
        raise error

    def check(self):
        if self._fixed_first is not None:
            raise self._fixed_first
        try:
            self._check_child()
            if self.ready.exists():
                self.fixed_evidence.update(self.report)
                self._fixed_ready = True
            elif self._fixed_ready:
                raise RuntimeError('Fixed endpoint readiness disappeared')
        except Exception as error:
            if self._fixed_first is None:
                self._fixed_first = error
            raise self._fixed_first

    def require_fixed_inventory(self):
        self.check()
        if self.all_render is not True or not self._fixed_ready:
            self._fixed_first = RuntimeError('Fixed endpoint inventory is not verified ready')
            raise self._fixed_first
        return self.fixed_evidence.inventory_sha256

    def __exit__(self, kind, value, trace):
        first = self._fixed_first
        try:
            super().__exit__(kind,value,trace)
        except BaseException as error:
            if first is None:
                first = error
        if self.cleanup_confirmed:
            try:
                expected = dict(schema_version=1,scope='all-active-render',inventory_policy='fixed',
                    endpoint_identities=sorted(self.fixed_evidence.expected_ids),
                    default_role_identities=dict(zip(ROLES,self.fixed_evidence.expected_roles)))
                self.fixed_summary = validate_fixed_report(self.report,expected,
                    started_ns=self.fixed_evidence.started_ns)
            except BaseException as error:
                from run_live_v2_session import publication_failure_record
                self.cleanup_failures.append(publication_failure_record(error,'endpoint_fixed_final_evidence'))
                if first is None:
                    first = error
        if first is not None and kind is None:
            raise first


def require_fixed_guard(endpoint):
    require = getattr(endpoint,'require_fixed_inventory',None)
    if not callable(require):
        raise RuntimeError('Option A requires fixed schema-2 all-render protection')
    digest = require()
    if type(digest) is not str or len(digest)!=64 or any(ch not in '0123456789abcdef' for ch in digest):
        raise RuntimeError('Fixed endpoint inventory proof is missing or malformed')
    return digest


def bounded_acceptance_failure(error, phase):
    """Keep available observer codes without copying arbitrary error payloads."""
    from run_live_v2_session import publication_failure_record
    record = publication_failure_record(error, phase)
    try:
        code = getattr(error, 'observer_exit_code', None)
        if code is not None:
            if type(code) is int and -(2**63) <= code < 2**63:
                record['observer_exit_code'] = code
            else:
                record['metadata_unavailable'] = True
        if getattr(error, 'endpoint_metadata_error', None) is not None:
            record['metadata_unavailable'] = True
    except Exception:
        record['metadata_unavailable'] = True
    return record


def finalization_emitter(emit, result):
    """D1's bounded fallback retains the additional A1 FIRST descriptor too."""
    def combined(event, **fields):
        if event == 'final_result_write_failure':
            fields['acceptance_failure_details'] = result.get('acceptance_failure_details')
        return emit(event, **fields)
    return combined
