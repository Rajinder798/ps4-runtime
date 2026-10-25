# Issue #39: four adversarial host safety corrections

Gate: G4 host safety prerequisite. This version follows the independent review
of Draft PR #47 at `e1fdf46bf47d0747e7fde99e37386420a14836e9`, based on main
`9b3810e38718637ac6bc89661f13391832c10776`. It does not complete G4 or qualify
physical endpoint/controller behavior. The original
[source record](../research/results/2026-10-25-issue39-host-safety.json),
[documentation](issue39-host-safety.md), review and raw counterexamples remain
preserved separately. No engine, guest or physical diagnostic was executed.

## Corrections and acceptance

1. All-render endpoint cleanup captures a failed process-status query, assumes
   termination is still needed, attempts kill and bounded wait, and attempts
   stderr closure in a finalizer. An existing session error remains primary;
   otherwise the first cleanup error is raised. Later status/kill/wait/close or
   metadata errors cannot replace it. A numeric exit observation must agree with
   the process return code before `cleanup_confirmed` becomes true. Missing or
   inconsistent confirmation is an error, and the axes result records that
   confirmation separately from the observed exit code. Legacy cleanup is
   unchanged.
2. The shared supervisor explicitly attempts stderr flush and close under its
   existing first-failure accumulator. Flush failure cannot skip close. Poll
   rejections keep their ValueError contract, original cause and timestamp/code
   record; close-only failure remains a failure. Secondary errors retain the
   existing 32-entry bound and overflow count. Root-exit and tree-cleanup checks
   remain required. Native containment and Job Object code are unchanged.
3. The existing all-render poll/publish loop is shared in
   `tests/all_render_loop.h`; production COM acquisition stays unchanged in
   `tests/all_render_observer.h`. Synthetic native operation shims exercise that
   same loop with deterministic time, readiness, stop and sleep operations.
   Actual elapsed time is checked after queries and before readiness/success.
   Pending identity/sample bytes and a complete terminal footer must fit before
   publication. The writer checks the output position again before the footer,
   and all new-mode output paths respect the 32 MiB limit. Query/identity/unmute
   failures remain sticky and take precedence if the same query also exceeds
   the time budget. No asynchronous COM design or additional thread is added.
4. Only schema-2 all-render JSON parsing rejects duplicate members, including
   nested objects and repeated equal values. Contradictory mute, token/identity,
   default-role, status, schema and footer fields cannot silently overwrite
   earlier values. Raw JSON tests exercise this boundary. The schema-1 reader
   deliberately retains its previous parsing behavior.

The 540-second session, 30-second startup, 570-second SDL observer and existing
endpoint-observer argument limits are unchanged. The all-render mode still uses
synchronous sequential COM queries and polling with a requested 25 ms sleep.
It cannot guarantee instantaneous detection or exclusion of transitions between
observations, nor preempt a blocked query. An overlong returning query fails;
these host tests do not qualify real query latency or physical safety.

## Before and after evidence

Fresh ignored output is `build/issue39-host-safety-002`; the directory was checked
absent before creation. Prior `issue39-host-safety-001` and
`issue39-adversarial-review-001` outputs were never reused.

Before editing, copied original counterexamples reproduced primary-error
replacement and skipped endpoint cleanup, supervisor close masking, duplicate
mute acceptance, and a passed native result at 153 ms with a 100 ms budget.
Separate green copies now retain the original session/poll error, attempt later
endpoint cleanup, reject the duplicate and reject the overlong native query
without readiness or a passed footer. The original close reproduction overrides
stream context exit; explicit stream closure avoids that exit hook. Additional
unit cases inject actual flush/close method errors and verify their ordering.

Local Windows x86-64 results:

- 31/31 baseline CTest suites; existing shared supervisor/observer callers pass.
- 39 Python safety methods: the original 23 plus 16 additions. The fresh native
  helper is used only with invalid arguments rejected before COM acquisition.
- Original 61 portable guard checks plus 40 production-loop checks: 101 total.
  Cases cover late/at-deadline first queries, stop during a late query, delayed
  stop queries, later overlong reads, pending sample/footer byte caps, exact-cap
  completion, query failure versus timeout and failed readiness/output sinks.
- PnP/readiness/cleanup: 3/3 suites. Diagnostic contract: 1/1 suite.
- Historical recorded-data replay: 6 methods, including five in-memory rejection
  substitutions against the actual source-attestation assertion.
- Five focused original PR #46 host methods pass using the corrected shared
  module. Its real supervise call binds to the current API. These checks do not
  qualify the combined guest/runtime behavior of the unmerged PRs.
- Isolated native observer builds successfully; original pinned binaries remain
  unchanged. No material compiler/linker warning was found in local builds.

Reproduce with the normal baseline CMake/CTest commands in a new build directory.
The baseline includes `issue39-safety-contract` and `all-render-guard-policy`;
the standalone PnP and diagnostic projects retain their normal CTest commands.
These are host-only targets. Do not run opt-in guest or physical harnesses.
Final hosted Windows/Linux run identities, inspected logs/warnings and exact
pushed head are recorded in PR #47 and the local correction report; passing an
earlier revision is not evidence for a subsequent revision.

## Historical source and integrity limits

The new [versioned source record](../research/results/2026-10-25-issue39-host-safety-v2.json)
links the unchanged prior record and its reviewed helper hashes to the current
two-helper delta. The historical replay still verifies all 17 original tested
source snapshots against their attestation and exact current equivalence for
the other 15 files. Only the original two-file exception is allowed. Modified
current helpers are explicitly host-tested, not physically requalified.

The preflight-005/process-raw.json exception remains invalid historical evidence.
Original SHA-256 is
`c5ca48a0fbb509a6ffa3cc72bad61ea6e8a7481503b08fcfd6957fd3edb2302e`;
preserved current SHA-256 is
`00d7528d03f6ca452e1b171dca2fddcb03d3dfbeff15c87f56e8d80c3b9d75eb`.
Original bytes are unavailable. The original checksum manifest and overwritten
file are unchanged; no reconstruction or full-preservation claim is made for
that preflight. A new preservation inventory covers 7,020 protected files,
including other G4/G5 workspaces and all earlier safety/review evidence.

## Required next checkpoint

Keep PR #47 Draft and unmerged. Request a new independent review of the final
corrective head after exact-head hosted checks have been inspected. Keep PR #46
unchanged, Issues #33/#37/#39 open and G5 frozen. Historical recovery remains
FAIL 6/9, connected PnP remains FAILED and live Windows integration remains
NO-GO. Licensing, source/relink and redistribution holds remain open; no binary,
SDK, firmware, keys or commercial assets are distributed by this source change.

No physical session authorization was consumed. A later independent review,
fresh complete machine/artifact preflight and separate explicit operator
readiness confirmation remain necessary. These corrections authorize no launch,
automatic retry, merge or G5 work.
