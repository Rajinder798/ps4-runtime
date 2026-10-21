# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
"""Read-only endpoint observation for opt-in guest tests; never a launch prerequisite."""
import json
from pathlib import Path
import subprocess
import time


def validate_report(path):
    records = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()]
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


class MutedEndpoint:
    def __init__(self, helper, output):
        self.report = output / "endpoint.jsonl"
        self.stop = output / "endpoint-stop.request"
        self.ready = output / "endpoint-ready.txt"
        self.errors = (output / "endpoint-stderr.txt").open("wb")
        self.child = subprocess.Popen([str(helper.resolve()), "--watch", str(self.report),
            str(self.stop), str(self.ready), "600000"], stdout=subprocess.DEVNULL, stderr=self.errors)

    def check(self):
        if self.child.poll() is not None:
            raise RuntimeError("Endpoint observer stopped; see endpoint-stderr.txt. No automatic audio changes or retries.")

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
            self.__exit__(None, None, None)
            raise

    def __exit__(self, kind, value, trace):
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
