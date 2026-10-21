# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
"""Bounded v2-only diagnostics. Never a guest-state or input acceptance oracle."""
import json
import time
import traceback


class Diagnostics:
    MAX_BYTES = 1024 * 1024
    MAX_RECORDS = 8192

    def __init__(self, path):
        self.path = path
        self.bytes = self.records = 0
        # Fresh output only; never replace or truncate an existing record.
        with path.open('xb'):
            pass

    def emit(self, event, **fields):
        row = dict(fields, schema_version=1, event=event, qpc=time.perf_counter(), unix_ns=time.time_ns())
        raw = (json.dumps(row, allow_nan=False) + '\n').encode('utf-8')
        if self.records >= self.MAX_RECORDS or self.bytes + len(raw) > self.MAX_BYTES:
            raise ValueError('V2 diagnostic storage exhausted; no rotation or retry')
        with self.path.open('ab') as stream:
            if stream.write(raw) != len(raw):
                raise OSError('Incomplete v2 diagnostic write')
        self.bytes += len(raw)
        self.records += 1


class FirstFailure:
    """Latch before containment; a secondary logging/cleanup error cannot replace it."""
    def __init__(self):
        self.error = self.record = self.diagnostic_error = None

    def capture(self, error, phase, emit=None):
        if self.error is not None:
            return
        self.error = error
        trace = ''.join(traceback.format_exception(type(error), error, error.__traceback__))
        self.record = dict(phase=phase, type=type(error).__name__, message=str(error),
            errno=getattr(error, 'errno', None), winerror=getattr(error, 'winerror', None),
            qpc=time.perf_counter(), unix_ns=time.time_ns(),
            traceback=trace[-8192:], traceback_truncated=len(trace) > 8192)
        if emit is not None:
            try:
                emit('first_failure', failure=self.record)
            except (OSError, ValueError) as diagnostic_error:
                # The run is already failed. Report this separately in the final
                # result rather than losing the original exception to logging.
                self.diagnostic_error = str(diagnostic_error)

    def update_result(self, result):
        if self.error is not None:
            result.update(status='failed', error=str(self.error), first_failure=self.record)
        if self.diagnostic_error is not None:
            result['first_failure_diagnostic_error'] = self.diagnostic_error

    def write_result(self, path, result, emit=None):
        self.update_result(result)
        try:
            path.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
        except (OSError, ValueError) as error:
            if self.error is None:
                self.capture(error, 'final_result_write', emit)
            elif emit is not None:
                try:
                    emit('final_result_write_failure', error=str(error))
                except (OSError, ValueError) as diagnostic_error:
                    self.diagnostic_error = self.diagnostic_error or str(diagnostic_error)
            raise self.error
