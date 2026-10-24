# Offline diagnostic isolation and lifecycle contract

This is an additive HOST TEST prerequisite for G4 / Issue #37, based on main
`79d4d3368a75f31a9cf8321640d5fc98211846cb` after PRs #43/#44. It imports no legacy
Source/Acquisition, Windows provider, live worker, supervisor, permit or engine.
It does not change production acceptance, parser policy or any existing source.

## Forwarding and immutable replay

`diagnostic_v1::Recorder` implements the merged pure `pnp_v2::Provider` contract.
Each method calls the original provider once with its original arguments, returns
the original value and rethrows the original exception. It neither memoizes nor
retries mandatory operations. Recording, copy failures and clock checks are
contained separately. Even oversized results are forwarded intact while their
optional copy is dropped. The capture budget never limits mandatory calls.

`std::move(recorder).Freeze()` consumes the capture epoch after native collection.
The caller must end mandatory work for that epoch at freeze. `Frozen` owns its
data and exposes only const access; it has no provider/clock reference. `Replay`
has its own cache of ordered node observations. Repeated IDs do not become a
single cached fact. Returned observation copies cannot mutate the frozen data;
missing observations remain unknown and invoke no provider method.

This is a serial capture epoch, not a concurrent Provider synchronization layer.

Caps are 64 facts, 1 MiB retained payload (record contents, lists, keys and event
entries), 128 relationship tokens, eight ancestry edges, 4,096 output rows,
1 MiB output and depth 32. The current manifest uses depth one; internal native
cache/Resolve/per-API stages are opaque. Fixed event storage is independently
bounded to at most 4,096 entries (default 1,024). Record and event drops are
separate counters. Capacity reservations and allocator bookkeeping add bounded
implementation overhead beyond payload bytes. No silent eviction or native
cache mutation is permitted.

A single 25 ms diagnostic budget starts before native calls. Native collection
does not restart it for optional replay. Expiry stops copying facts and prevents
starting new optional replay; mandatory calls continue. Diagnostic clock errors,
reversal, frequency mismatch and checked deadline overflow remain sticky failures.
The existing 250 ms native scan policy and real native clock are unchanged.
`host_test_ticks` is a separate declared domain: the reader never relabels native
QPC values as fake clock values. Instrumentation costs time; native Overhead
verdicts near the boundary are retained, not forced equal to another run.

The Provider seam exposes typed facts, not raw HID UTF-16. This contract does not
repair/prove equivalence of the unmerged legacy Source/Acquisition/companion,
acquire missing raw properties or qualify the HID assessor. Those remain separate
integration gates. The module is not wired into any live path.

## Mandatory lifecycle and independent binding

New schema: `pnp-diagnostic-contract-v1`, origin `HOST TEST` only. Required order:

1. Header and scope start.
2. Bracketed native collection with bounded mandatory-call observations.
3. Bracketed capture freeze and retained-fact accounting.
4. Native-result proof bound to a separate complete-format native JSONL stream.
5. Bracketed optional replay decision.
6. Bracketed cleanup, final publication and scope completion, each exactly once.
7. Scope end and terminal footer.

Only replay can be explicitly skipped, for expiry; invalid clocks use explicit
not-measurable states. Failed phases and unknown/drop states cannot certify
completeness. The reader validates fixed stages, parents, order, cardinality,
states, caps, types, clocks, call/fact ordinals, counters and terminal timestamps.
An empty set of balanced brackets is insufficient. A summary at or beyond the
exclusive deadline cannot remain complete. Old schema rows are rejected.

The independent file-only reader also invokes the unchanged native reader and
checks native frequency, first reason/QPC, readiness, coverage, cleanup and
collection completeness. The proof's `cleanup_ok` is bound to the validated native
summary (which must match its cleanup row); `collection_complete` is bound to the
native reader's independently computed result. Producer booleans alone cannot
establish success. Native and diagnostic first failures remain distinct. This
version conservatively requires independently complete native collection,
successful native cleanup, complete native coverage and no native exception/failure
for diagnostic completeness. Failed but structurally valid evidence remains
inspectable with `require_complete=False`; false success claims are rejected even
in that mode, and default validation rejects incomplete evidence. Native
readiness may be false even when diagnostics are complete. Recovery acceptance
is always false.

Output uses fixed categories/counters and native failure provenance, never raw
IDs, opaque paths, instance keys, property fingerprints or exception messages.
Captured IDs/keys remain bounded transient memory. It is an explanatory host
contract, not a cryptographic attestation or a production evidence loader.

`Finish` writes a fresh `.partial`, checks write/flush/close, and publishes by
rename only after those succeed. A returning late/invalid post-close check
withholds a purported success. Truncated writes, insufficient output caps or
failed publication produce no valid published success. The CLI refuses partial
paths, including Win32 case/trailing-dot/space/unnamed-stream suffix aliases.
This name guard is not authentication against renaming or hard links.
`self_close_measured` stays false: a row cannot time its own write/close;
this is not an external supervisor receipt or hard real-time cancellation.
The cleanup stage is an explicit host outcome, not an invented Windows job proof.

## Reproduction and tests

```sh
cmake -S tests/pnp_diagnostic_contract_v1 -B build/contract-host -DCMAKE_BUILD_TYPE=Release
cmake --build build/contract-host --config Release
ctest --test-dir build/contract-host -C Release --output-on-failure
```

The new target compiles actual merged pure PnP core sources, never the Windows
provider or observer. The host executable compares forwarding transcripts and
exception types/results, preserves changing repeated-node/ancestry observations,
and verifies replay makes zero provider calls. It produces 30 synthetic-provider
fixtures with native evidence, optional results and partial writer failures.
The native-overhead fixture intentionally uses a 300 ms host sleep, not a device
query, to verify the real native timing failure remains reason 9.

Python regressions remove/resequence brackets, delete each phase, omit the footer,
duplicate/reorder terminals, forge drops/unknowns, alter native proof, make only
the footer late, corrupt JSON/types/schema/privacy and claim false finalization.
Windows/Linux CI retains all new generated artifacts and test output. Existing
PnP/cleanup and 29-suite baseline workflows remain separate regressions.

Original audit red probes remain unchanged. Before implementation the old
file-only reader's missing-stage/late-summary counterexamples were reproduced
and a deliberately synthetic shared-cache negative control was retained under
local `build/live-av-v2/pr45-implementation-001`. That control demonstrates the
cache risk mechanism; it is not a new observed Windows or legacy-provider result.
New-host results and exact-head CI belong in the Draft PR, never retroactively
in old reports. No successful host case establishes physical readiness.

## Native completeness binding correction

Independent review found a P1 false-completeness defect at the original PR head
`455c8b88d42dd1d32eeab789263cb1c083425a2b`. With the saved Good contract unchanged,
native cleanup code 5 and truthful summary `cleanup_ok=false`,
`collection_complete=false`, `coverage_complete=true` were accepted as diagnostic
success. The native reader correctly reported incomplete collection; the old
contract reader discarded that result. The red counterexample and two failing
targeted regressions are preserved separately; historical evidence is unchanged.

The existing Native proof and producer now carry cleanup and collection outcomes,
and the reader requires independent native completeness. Regression cases cover
the Good control, failed native cleanup, incomplete collection despite successful
cleanup/coverage, forged/missing/ill-typed proof, false complete claims, incomplete
inspection/default rejection and original native first-failure preservation.
The incomplete-collection fixture is explicitly file-only: it conservatively
changes a newly generated synthetic native summary to decline completeness while
retaining coverage and cleanup. It is not a newly observed Windows failure.
Earlier provisional contract rows lacking these required proof fields are rejected;
they are retained unchanged as historical evidence rather than retroactively fixed.

## Continuing holds

Connected snapshot remains **FAILED / exit 1**, guest recovery **FAIL 6/9**, and
Issues #33/#37/#39 stay open. Live integration remains **NO-GO**. Raw-source/cache
equivalence, own-state/edge proof, failure-domain/session ordering, external
publication receipt and new source/binary/Python attestation still require
independent review. No production Python pin or settings are changed.

Original GPL-2.0-or-later notices and root LICENSE remain; dependencies are the
existing C++20 standard library, CMake and Python. No external package/binary,
engine implementation or proprietary material is added. Existing redistribution,
dependency/source/relink/security holds remain open. Owner review is required;
this PR must remain Draft until separately authorized. No live permission follows.
