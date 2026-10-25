# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
"""Read-only endpoint observation for opt-in guest tests; never a launch prerequisite."""
import json
from pathlib import Path
import subprocess
import sys
import time


def validate_report(path, *, all_render=False):
    records = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()]
    if all_render:
        return validate_all_render(records)
    if len(records) < 3 or records[-1].get("status") != "passed":
        raise RuntimeError("Endpoint observation incomplete")
    samples = records[:-1]
    if records[-1].get("samples") != len(samples):
        raise RuntimeError("Endpoint observation count mismatch")
    initial = samples[0]["volume"]
    previous = -1
    for sample in samples:
        elapsed = sample["elapsed_ms"]
        if (sample["muted"] is not True or sample["same_endpoint"] is not True or
                type(sample["volume"]) not in (int, float) or not 0 <= initial <= 1 or
                sample["volume"] != initial or type(elapsed) is not int or elapsed < previous):
            raise RuntimeError("Windows endpoint did not remain muted and unchanged")
        previous = elapsed
    gaps = [b["elapsed_ms"] - a["elapsed_ms"] for a, b in zip(samples, samples[1:])]
    return dict(status="passed", samples=len(samples), duration_ms=previous,
                volume_scalar=initial, muted=True, same_endpoint=True, max_sample_gap_ms=max(gaps),
                observation="read-only polling; changes between samples are not excluded")


def validate_all_render(records):
    """Independent schema-2 reader; never grants acceptance to a failed footer."""
    if not records or records[-1].get('event') != 'summary' or records[-1].get('status') != 'passed':
        raise RuntimeError('All-render endpoint observation incomplete or failed')
    known, volumes, samples = {}, {}, []
    default = None
    for row in records[:-1]:
        if row.get('schema_version') != 2:
            raise RuntimeError('Wrong all-render endpoint schema')
        if row.get('event') == 'identity':
            token, identity = row['token'], row['identity']
            if (type(token) is not int or token != len(known) or token >= 32 or
                    type(identity) is not str or not identity or identity in known.values()):
                raise RuntimeError('Invalid endpoint identity inventory')
            known[token] = identity
        elif row.get('event') == 'sample':
            stamp, current = row['elapsed_ms'], row['default_tokens']
            endpoints = row['endpoints']
            if (type(stamp) is not int or stamp < 0 or (samples and stamp < samples[-1]) or
                    type(current) is not list or len(current) != 3 or
                    any(type(token) is not int or token not in known for token in current) or
                    not endpoints or len(endpoints) > 32):
                raise RuntimeError('Invalid endpoint sample/default')
            if default is None: default = list(current)
            if current != default: raise RuntimeError('Default endpoint changed')
            seen = set()
            for endpoint in endpoints:
                token, scalar = endpoint['token'], endpoint['volume']
                if (type(token) is not int or token not in known or token in seen or
                        endpoint['active'] is not True or endpoint['muted'] is not True or
                        type(scalar) not in (int, float) or not 0 <= scalar <= 1):
                    raise RuntimeError('Endpoint unavailable, unmuted or unverifiable')
                seen.add(token)
                if token in volumes and volumes[token] != scalar:
                    raise RuntimeError('Endpoint volume changed')
                volumes[token] = scalar
            if not set(current).issubset(seen) or set(known) != seen or not set(volumes).issubset(seen):
                raise RuntimeError('Previously observed endpoint removed')
            samples.append(stamp)
        else:
            raise RuntimeError('Failed/unknown endpoint event')
    footer = records[-1]
    if (footer.get('schema_version') != 2 or type(footer.get('samples')) is not int or
            footer['samples'] != len(samples) or not samples or set(known) != set(volumes)):
        raise RuntimeError('Incomplete all-render observation')
    return dict(status='passed', scope='all-active-render', samples=len(samples),
                endpoint_identities=len(known), muted=True, same_default=True,
                duration_ms=samples[-1], max_sample_gap_ms=max([b-a for a,b in zip(samples,samples[1:])] or [0]),
                observation='read-only polling; transitions between samples may be missed')


class MutedEndpoint:
    def __init__(self, helper, output, *, all_render=False):
        self.report = output / "endpoint.jsonl"
        self.stop = output / "endpoint-stop.request"
        self.ready = output / "endpoint-ready.txt"
        self.all_render = all_render
        self.cleanup_failures = []
        self.errors = (output / "endpoint-stderr.txt").open("wb")
        self.child = subprocess.Popen([str(helper.resolve()), "--watch-all-render" if all_render else "--watch", str(self.report),
            str(self.stop), str(self.ready), "600000"], stdout=subprocess.DEVNULL, stderr=self.errors)

    def check(self):
        if self.child.poll() is not None:
            error = RuntimeError("Endpoint observer stopped; see endpoint-stderr.txt. No automatic audio changes or retries.")
            if self.all_render: error.observer_exit_code = self.child.returncode
            if self.all_render and self.report.exists():
                rows = self.report.read_text(encoding='utf-8').splitlines()
                for line in reversed(rows):
                    row = json.loads(line)
                    if row.get('event') == 'failure':
                        error.observer_failure = row
                        if row.get('code_domain') == 'HRESULT': error.hresult = row['code']
                        break
            raise error

    def __enter__(self):
        try:
            deadline = time.monotonic() + 10
            while not self.ready.exists():
                self.check()
                if time.monotonic() >= deadline:
                    raise RuntimeError("Endpoint observer not ready; no guest will be launched")
                time.sleep(0.025)
            self.check()
            return self
        except BaseException:
            self.__exit__(*(sys.exc_info() if self.all_render else (None, None, None)))
            raise

    def __exit__(self, kind, value, trace):
        if self.all_render:
            from run_homebrew_startup import failure_details
            first = None
            for phase, action in (
                ('endpoint_stop', lambda: self.stop.touch(exist_ok=True)),
                ('endpoint_wait', lambda: self.child.wait(timeout=5)),
            ):
                try: action()
                except BaseException as error:
                    if first is None: first = error
                    self.cleanup_failures.append(failure_details(error, phase))
            if self.child.poll() is None:
                for phase, action in (('endpoint_kill', self.child.kill), ('endpoint_wait_after_kill', lambda: self.child.wait(timeout=5))):
                    try: action()
                    except BaseException as error:
                        if first is None: first = error
                        self.cleanup_failures.append(failure_details(error, phase))
            if self.child.returncode and first is None:
                try: self.check()
                except BaseException as error: first = error
                self.cleanup_failures.append(failure_details(first, 'endpoint_exit'))
            try: self.errors.close()
            except BaseException as error:
                if first is None: first = error
                self.cleanup_failures.append(failure_details(error, 'endpoint_stderr_close'))
            if first is not None and kind is None: raise first
            return
        try:
            self.stop.touch(exist_ok=True)
            try:
                code = self.child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.child.kill()
                self.child.wait(timeout=5)
                raise RuntimeError("Endpoint observer required termination")
            if code and kind is None:
                raise RuntimeError("Endpoint observation failed; see endpoint-stderr.txt")
        finally:
            self.errors.close()
