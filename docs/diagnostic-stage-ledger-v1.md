# G4 host-only diagnostic stage ledger, version 1

Issue #37 prerequisite, approved baseline
`48185ae9777971502a167d69a6ab29e57451b13b`. This prototype measures synthetic
diagnostic work and enforces a total 25 ms scope. It is not connected to a live
worker, Windows acquisition adapter or the new HID-list assessor. Original
connected snapshot: FAILED, exit 1. Guest recovery: FAIL 6/9. No HID qualification,
reconnect repair, physical test or completed G4 is established.

## Independent implementation boundary

The standalone `tests/diagnostic_stage_ledger_v1` project compiles a new
`stage_ledger_v1` library and a driver accepting only `--host-test OUTPUT`.
`HostSource` is a separate interface subtype; the existing WindowsSource is not
an instance of that subtype. The driver supplies fixed fake raw properties and
an explicit fake clock. No live entry point or Windows acquisition source is
linked into the new driver. Its file operations only create fresh host evidence.

The project reuses the unchanged frozen `Acquisition`/`Resolve`/`Collector` and
the earlier test-only clock-substitution build. No historical source/binary or
production selection changes. Original required classification prefetch continues
after diagnostic expiry, using the same immutable fake-provider facts the
Collector subsequently consumes. Optional system-root discovery, extra ancestry
and detail preparation stop. Required prefetch is labeled **optional=false**;
it is not a claim that extra diagnostics remain permitted after expiry. No new
identity assessment supplies the Collector's readiness predicate.

A skipped optional property read throws an internal stop before cache insertion;
it cannot cache fabricated missing metadata. A real synchronous call begun before
expiry may return late. Its actual result can remain cached for original work,
but cannot establish completed diagnostic traversal after the deadline. This
sequential cache is not an atomic topology snapshot, and this fake-provider
equivalence is not a claim of equivalent behavior on racing real devices.

## One total deadline

The scope begins before PRESENT enumeration, with an explicit 10 MHz clock and
deadline `begin + 250000` ticks, exactly 25 ms. Preparation never resets it.
The prototype uses an exclusive boundary: a new optional operation may begin
only while `now < deadline`; a return or final check at equality is expired.
This stricter host-only boundary does not change frozen live v1's comparisons.

Every additional diagnostic acquisition/cache access and ancestry step checks
before and after its measured work. The final publication and scope-completion
stages also check the same deadline. On expiry, the first diagnostic time failure
is retained once; optional traversal/serialization stops, omitted details are
counted unknown, and original classification aggregates continue. Earlier resource,
clock or cleanup errors are not overwritten by later time/storage errors.

Already collected bounded details can be published after expiry as evidence of
earlier collection; their `collected_qpc` must precede the deadline. An expiry
during final publication invalidates diagnostic completeness even when all fifty
details were collected and no detail was omitted. Publication is mandatory failure
evidence, not another opportunity to traverse devices. The final two bounded
control rows report the last observed scope check; a row cannot measure the return
of its own final write. No hard real-time or complete filesystem-close timing
guarantee is claimed. A storage stall may prevent any footer and yields an invalid
stream, never a complete diagnostic.

The frozen Collector still independently measures its original 250 ms snapshot,
including interleaved provider work. Its first-failure and cleanup semantics are
unchanged. Cleanup/publication after `Collector::Snapshot` are outside that
Collector interval, but remain inside the stricter diagnostic scope until scope
completion. Time expiry is detected after a returning synchronous call; it cannot
cancel an already blocked provider. Existing five-second worker/two-second cleanup
supervision is neither reimplemented nor installed by this host prototype.

## Closed ledger schema

Every JSONL row has exactly `schema=diagnostic-stage-ledger-v1`, `origin=HOST TEST`,
contiguous `sequence`, integer `qpc`, `event` and that event's fixed fields.
`tools/diagnostic_stage_ledger_v1.py` contains the exhaustive field sets and
independent validator. No row grants recovery. Publication QPC is nondecreasing;
failure occurrence QPC is separate from the later observation/publication time.
Equal-resolution failure timestamps are reported as a tie, not invented ordering.

| Event | Fixed evidence |
| --- | --- |
| header | 10 MHz frequency; unchanged 25/250 ms limits; row/byte/detail/token/edge/call caps |
| scope_start | begin, deadline, clock validity |
| stage_begin | sequential ID, parent stage ID, fixed stage category, optional flag, remaining ticks |
| stage_end | matched ID, begin/end, inclusive elapsed ticks, remaining ticks, clock validity |
| anchors | local qualified USB tokens, independent system-root token, discovery/PRESENT completeness |
| first_failure | independent original/diagnostic domain, fixed reason, occurrence QPC |
| detail | attempt ordinal, source category, original reason, relation, local chain, collection QPC |
| scope_end | final observed begin/end/elapsed/remaining and clock validity |
| summary | original/diagnostic first reasons, readiness/cleanup facts, reason histogram, retained/omitted/ancestry totals, completeness, recovery_accepted=false |

Stages are PRESENT enumeration, system-root lookup, qualified target-root discovery,
raw property acquisition, acquisition/cache population, rejection classification,
bounded ancestry, detail serialization, interface enumeration, cleanup, final
publication and scope completion. Stages nest: cache population includes a cold
raw read; classification can include several cache accesses. Durations are
inclusive and **must not be summed as disjoint work**. A raw-property bracket
measures one combined Source::Read batch, not individual Windows hardware-ID,
enumerator, status or parent API calls. Metadata serialization stages prepare
bounded detail payloads; the publication bracket covers emitting/flushing them.

Backwards, throwing or overflowing clocks stop optional work. Remaining/elapsed
values become -1 with clock_valid=false, using the last known timestamp only as
an explicitly uncertain publication anchor. Unknown durations are not fabricated.
The checked deadline addition cannot overflow. A clock-fault stream without an
original trace is inspectable only as an unbound failed diagnostic.

The reader checks types (including rejecting booleans as integers), closed keys,
duplicate JSON keys, nonfinite values, monotonic publication, nested brackets,
budget arithmetic, exclusive optional-work starts, early detail collection,
anchor proof, all count partitions and original trace equality. Target relations
must end at a qualified local anchor. Other-branch relations require complete
PRESENT/root discovery and a successful independent root. Code 13, a partial
chain, missing root proof, cycle or depth cap remains unknown. Tokens are
stream-local and cannot identify a device across captures.

The original validator is called separately with host origin allowed and observer
completeness not required. It still checks the native schema/coverage contract.
Original node/interface/reason counts, readiness, native first failure and cleanup
must exactly match ledger summary. A missing/partial/capped/footerless ledger is
rejected independently even if the native original remains valid.

## Deterministic regressions

The explicit fake clock uses a fixed start and controlled provider/stage costs;
normal scenarios advance one 100 ns tick per clock read. Exact-boundary cases use
zero read cost and a scheduled final cost, allowing below/equal/above comparisons.
This is synthetic QPC-shaped time, not Windows performance. Negative advances and
overflow are tested. Repeated schedules produce identical evidence in one process.

Twenty-two provider schedules and three clock-fault cases cover all requested
stages, slow preparation/property/parent calls, expiry before any detail and after
a partial set, the final-tail gap, original 250 ms overrun, both first-failure
orders, late writer/cleanup faults, unknown ancestry, row caps, exact boundaries
and clock uncertainty. Reader negatives cover missing/truncated streams, forged
counts/completeness, private/unknown fields, duplicate keys and nonfinite values.

The public fifty-attempt fixture has original 27 node + 23 interface rejections,
with original reason totals 22 invalid syntax / 7 missing ID / 21 unrecognized.
A 20 ms preparation plus a deliberate fifth millisecond during attempt 41 yields
40 retained / 10 omitted, with original totals intact. The fixture does not
reconstruct the original fifty properties or the ten omitted physical details.
Its unknown attribution count is ten; physical evidence has eleven, including
one retained depth-limit case. A six-string synthetic property reproduces safe
shape categories only and is not the unrecorded physical list.

The post-last-detail case collects all fifty details but incurs a scheduled
26 ms final completion cost: diagnostic_time_limit is recorded and completeness
is false. At 24.9999 ms with zero clock-read cost the final check passes; at 25 ms
and 25.0001 ms it fails. Original Coverage=1 remains independent. A 251 ms
enumeration yields original Overhead=9; the diagnostic's own failure occurs
earlier without changing that original reason. Later cleanup/writer errors cannot
replace the recorded first failures.

## Limits, privacy and stability

Limits: 4,096 ledger rows, 1 MiB, 64 details, 128 local tokens, eight ancestry
edges, 32 nested stages and 32,768 logical Source calls. Enumeration truncates at
2,048 nodes / 2,048 interfaces per class; the unchanged acquisition cache retains
its original bound. A source must honor its bounded raw-return contract before
returning; this host prototype is not a sandbox against an arbitrary malicious
provider. Mandatory classification is finite, but may outlast the 25 ms budget.

No raw IDs, VID/PID strings, serials, paths, DEVINSTs or device fingerprints are
serialized. Fixed reason/source/stage categories and snapshot-local tokens are
sufficient for the diagnostic ledger. Original source/binary hashes are provenance,
not device identity. New CLI flags cannot select a live source.

The preserved Windows CI failure in the prior development workflow expected fifty
details but retained zero and lacked a mixed-bus detail row; the independent
frozen workflow passed at that same head. This is consistent with wall-clock
scheduling/storage causing budget-sensitive fixtures to omit details. Raw per-case
files were temporary, so no exact stage, API, scheduler or I/O cause can be proved.
Those logs remain sealed; assertions, timeouts, frozen budgets and independent
existing workflows are unchanged. New tests exclusively use deterministic clocks.

## Reproduction and evidence preservation

```powershell
cmake -S tests/diagnostic_stage_ledger_v1 -B build/ledger-host -DCMAKE_BUILD_TYPE=Release
cmake --build build/ledger-host --config Release
ctest --test-dir build/ledger-host -C Release --output-on-failure
```

The local project includes all earlier host suites. The new Windows/Linux workflow
runs its new deterministic suite only; the unchanged independent workflows run
HID-list, rejection, v2, snapshot, coordinator and full root baseline at the same
final commit. `LEDGER_V1_EVIDENCE` selects a fresh parent for saved fixtures;
`HID_V1_EVIDENCE` separately preserves earlier synthetic regressions. No parent
may be reused for another run. Failed development logs are retained.

`tools/replay_stage_ledger_v1.py` verifies the captured preservation baseline and
reads historical guest/PnP evidence without invoking any runner. All 3,602 earlier
protected files, all 3,293 bundle-reference files and all 975 frozen inputs were
checked before edits. The previous task's 638 sealed artifacts and twelve source
additions are protected too. No historical verdict or original manifest changes.

At preflight the external app-managed Python executable had changed to SHA-256
`3ceb740cb3eb2c1c38602cf75a199e6331dd1295957e0d91e4dd4ef248466bf4`.
The original production bundle expects
`7c4ee3011932a75b30db176f35fb91b28f0b299e608eaf643fb1bf36ed5ace99`.
Its reference files verify, but its separate production runtime gate remains
**python_identity_changed**, not passed. No exact old Python was found in the
available runtime archive, and nothing was substituted or repinned. Offline builds
use the identified current Python 3.12.14. File-only replay reports this mismatch
separately; it never labels the old production verification a pass.

Final commit, changed paths, source/binary hashes, final CI logs and preservation
are recorded in the fresh `build/live-av-v2/diagnostic-stage-ledger-v1-001/` report.
A workflow definition alone is not successful CI or live evidence.

## Smallest future integration proposal — separate review and authorization

Review this provider/clock/schema design and its required-prefetch versus optional
work accounting independently. A future Windows diagnostic version would need a
new adapter that exposes only actually measurable stage batches, bounded calls,
race uncertainty and own started/problem-free facts. It must retain frozen
classification/readiness and keep the HID-list candidate separate until approved.
First build/review versioned sources and binaries, resolve the Python/toolchain
identity hold, attest a new bundle without changing the old one, and independently
validate host corruption/cleanup cases. Only then propose a separately authorized
initial connected snapshot with explicit physical preflight. No such integration,
device query or physical procedure is initiated here.

The exact physical HID strings, its own startup/problem status, the ten omitted
properties, per-API preparation costs and guest reconnect cause remain unknown.
Windows mute/volume/default devices are left untouched and unqueried. No source
distribution or engine release approval is added; original GPL-2.0-or-later applies
with no new dependency. Existing release/license holds and Issues #33/#37/#39 stay
open. No PR/merge. Stop after offline implementation, verification and reporting.
