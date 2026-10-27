# Issue #39 host-only preflight safety correction

Gate: G4 diagnostic safety prerequisite. Base main is
`9b3810e38718637ac6bc89661f13391832c10776`. This change does not reproduce or
resolve the unexplained window losses, establish controller recovery, execute a
PS4 guest or complete G4. The research engine remains a separate pinned shadPS4
process; no engine or homebrew source/pin changes are included.

## Corrected failure ordering

The former supervisor polling loop replaced `monitor_error` on every rejection.
The axes runner could then replace that error with an SDL observer cleanup
exception. The corrected transport retains the first exception and its observed
message, class, phase, QPC/Unix timestamp and available errno/Win32/HRESULT data.
The existing polling `ValueError` contract is retained, with the original error
as its cause. Optional diagnostics expose the primary, up to 32 ordered secondary
failures, an explicit overflow count and the actual supervisor report.

Stop-request, wait/termination, report and root-exit/tree-cleanup checks still run
after a rejection. A cleanup error without an earlier failure is itself a primary
failure. SDL/window/endpoint cleanup and postmortem/publication errors are recorded
separately. Axes results are published from a new partial only after successful
write/flush/close; an incomplete partial is not a successful final result.

The supervisor executable, Job Object ownership/kill-on-close behavior, engine,
fixture, input stages and original HWND/PID guard are unchanged. No automatic
rebinding, input injection, physical retry or timeout extension is introduced.

## Scoped all-render observer mode

Only the Issue #39 axes harness opts into `--watch-all-render` through
`MutedEndpoint(..., all_render=True)`. The existing `--watch` mode, schema-1
reader and unrelated callers retain their console-default contract.

The new mode uses read-only COM queries to enumerate the actual active render
endpoint set on every poll. It checks all three Windows default roles (console,
multimedia and communications), each endpoint's identity, availability, mute and
per-device volume. It does not hardcode six endpoints. The readiness signal is
written only after a complete valid initial observation. Later unmute on any
observed endpoint, an unsafe newly active endpoint, any default-role change,
removal/unavailability, lost/duplicate identity or failed query stops the guard.
A new safely muted endpoint may join the tracked set; all previously observed
endpoints must remain present and unchanged. Failures are sticky with no retry.

The production COM provider and synthetic provider feed the same portable guard.
Schema 2 records per-run tokens and identity mappings, sample endpoints and
default-role tokens. Failure records retain the offending identity, phase,
available HRESULT/Win32 code and timestamp. A failed result exits nonzero and is
an axes abort; the independent Python reader rejects failed/incomplete or
inconsistent evidence. Real local logs contain relevant OS endpoint IDs for
attribution: do not publish them without privacy review. Committed fixtures use
artificial endpoint names/IDs only.

No mute/volume setter, stream/client initialization, device removal, driver or
Windows configuration API is used. Bounds are 32 tracked identities, 32 MiB
sample output and the existing 100..600000 ms observer budget; exceeding a bound
fails. The axes 540-second session, 30-second startup, 570-second physical
observer, audit, screenshot and process-containment limits are unchanged.

This remains polling (25 ms requested sleep), not proof that a brief transition
between samples cannot occur. Native setup/query failures fail closed; output
failure leaves incomplete evidence, never acceptance. Synthetic host tests do
not qualify physical endpoint safety.

## Verification and historical evidence

The deterministic regressions exercise actual supervisor, axes cleanup/finalizer,
reader and guard logic with fake process/endpoint boundaries. They cover distinct
successive polling errors, SDL timeout after a primary, cleanup-only failures,
secondary evidence errors, root/tree-check rejection, default/nondefault/new
unmute, three default roles, removal, query/identity failures and legacy mode.
Native helper argument tests reject invalid requests before COM initialization.
No engine, guest, controller test, audio-setting change or audio stream is used.

The original disconnected-close source snapshots and attestation remain intact.
Two shared helpers now intentionally differ from those physically tested bytes.
The recorded-evidence suite checks their explicit new hashes in
`research/results/2026-10-25-issue39-host-safety.json`, checks the original hashes
against unchanged snapshots, and retains exact equivalence for the other 15
files. This records a host-only source delta, not physical requalification.

The earlier `preflight-005/process-raw.json` is an integrity exception: original
SHA-256 `c5ca48a0fbb509a6ffa3cc72bad61ea6e8a7481503b08fcfd6957fd3edb2302e`,
preserved current SHA-256
`00d7528d03f6ca452e1b171dca2fddcb03d3dfbeff15c87f56e8d80c3b9d75eb`.
Its original bytes are unavailable; its original checksum manifest is unchanged.
It is excluded from valid historical evidence. No reconstruction or repair is
performed. The isolated repair's full local preservation manifest covers 1,625
original tracked/relevant evidence/artifact files and is verified after tests.

## Review and future physical checkpoint

All builds use a separate feature worktree and fresh ignored host output. The
new observer is built there; the old pinned observer/engine binaries are not
overwritten. A future physical command must explicitly select the reviewed new
observer and record its new digest. The original expected observer digest does
not identify this new executable. No physical session is launched by this task.

Independent source review, final hosted host checks, a fresh complete machine
and artifact preflight, and separate operator readiness are required before the
single unused physical authorization can be consumed. Keep Issues #33/#37/#39
open, PR #46 untouched/unmerged, G5 frozen, recovery FAIL 6/9, connected PnP
FAILED / exit 1 and live Windows integration NO-GO. Existing licensing/source/
relink and redistribution holds remain open; only original GPL source changes
are proposed, with no binary, firmware, SDK, key or commercial-asset distribution.
