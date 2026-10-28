# Issue #39: correct three independent host-review blockers

G4 host-only prerequisite on existing Draft PR #48, still stacked on PR #47 at
`992ed612cbf69f5d6d6c4b58fccb5ccd4bcfb832`. The reviewed head was
`1d5bfa55f87d2b747bfeabfaa54d06e4175a61f4`. No engine/guest/controller test,
keyboard automation, audio watch, Windows setting change, PR retarget/merge or
G5 work is authorized or performed. The physical authorization is consumed.

## Exact bounded cutoff coverage

The original publication barrier checked only timestamp order/reach. The final
suffix predicate dropped post-cutoff records, leaving its crossing gap unchecked.
Thus last sample4.1, frozen cutoff4.2, first watermark4.9 could qualify despite
an unobserved0.8s interval. Last24.1/cutoff24.8/next25.0 also qualified. This was
an inherited final-rule omission, exposed by the new live barrier.

Live and final now use the same `_sdl_cutoff_window` rule. A valid observation
exactly at cutoff suffices. Otherwise valid before/after observations must
bracket the unchanged cutoff with a total gap <=0.35s. The comparison is integer
`gap_ticks*20 <= frequency*7`; 0.350000s passes and one native tick beyond fails.
No first-after sample means still pending; existing liveness/deadline checks
continue and the540s session budget still fails closed. A witnessed excessive
gap fails, rather than moving cutoff or waiting for favorable directional input.

The cutoff is still assigned once at the original post-PNG-validation point.
Native QPC/perf_counter is an integral tick clock. The rounded seconds encoding
is recovered to the nearest native tick; new phase records also save that
integer tick and live/final cross-check it against seconds. Legacy seconds-only
records remain readable. Recovery fails closed if double precision cannot
distinguish native ticks. All edge inclusion/gap decisions use native integers;
this representation recovery does not seek or choose a different input window.
Invalid frequencies, cutoff values, signed-native-range violations or conflicting
integer/seconds fields reject. Historical cutoff85125.7320741 at10MHz recovers
851257320741 exactly. No physical F12 time is inferred.

All original2048 sideways/28672 target bounds, guest bounds, >=3s/20observations,
interior0.35s gaps, motion, connection, image and phase ordering checks remain.
Well-formed post-cutoff direction/button changes are irrelevant to the earlier
hold; their schema and timestamps must still be valid as publication evidence.
This implements the explicitly authorized edge application of the existing gap
bound, not a relaxed tolerance or an earlier favorable cutoff policy.

## Strict publication witnesses

Every encountered axis_state must have four signed16-bit integer axes (booleans
and floats excluded), bool connected=true, unsigned32-bit integer button mask,
and positive strictly increasing signed64-bit native QPC. Unknown/missing record
events, missing fields, invalid frequency or sole opened device identity fail.
The opened identity must be the wired nonvirtual Sony054C/0CE6 with a valid
instance ID and native frequency. No nonexistent per-axis schema/identity field
is invented: this is the actual native observer record contract. Malformed rows
are not skipped to find a later convenient witness. Raw JSON duplicate members
are rejected; an incomplete last writer line cannot grant coverage.

The original increasing-QPC witness with axes=[] now fails before advance,
including at the last phase of an otherwise valid17-phase synthetic run. A
valid after-cutoff off-axis row remains a valid witness, without changing the
prior directional decision.

## Preserve first ownership failure

The in-poll RuntimeError handler previously emitted postmortem diagnostics before
re-raising. An OSError during that emit replaced the ownership error before the
PR #47 supervisor could remember it. That gap was inherited.

The original ownership failure is now recorded immediately with poll phase,
message and available codes. Discovery and emit errors are separately retained
with phase/provenance, including in existing supervisor secondary diagnostics.
A metadata failure has an explicit fallback and retains available codes. The
original object is re-raised; the existing ValueError poll contract keeps it
as explicit cause and carries available codes through supervisor diagnostics.
The supervisor's existing final ValueError still chains that original object.
Native binding, process containment, root/tree verification and shared PR #47
modules are unchanged. Reporting errors cannot grant successful qualification.

The ownership-reporting helper has no no-prior-ownership path. Unrelated write
failures remain primary when no earlier error exists. Tests cover successful
emission, write OSError, multiple secondaries, failed metadata, actual poll error
object/code, real supervisor diagnostics/final JSON publication and cleanup.

## Extra PNG accounting: unchanged scope

The contract qualifies17 credited, sequence-bound images; it does not inventory
and reject every extra file after a final capture becomes pending. Two files
already present before pending reject, but another PNG arriving during pending
final capture is ignored once closing begins. Full host-only production-runner
replay still permits18files with17genuine phases. It does not bypass any credited
phase predicate. No new extra-file fail-closed rule is implemented; that is a
separate owner decision. Prior blanket claims that all extras fail closed were
too broad and must not be relied on.

## Evidence, tests and limits

Original review scripts and red results are preserved separately from corrected
green replays under fresh ignored issue39-axis-qualification-fix-001. Source
snapshots preserve the reviewed implementation; no old counterexample is edited.
The three original actual-poll cases now reject stale/malformed input and retain
FIRST identity when SECOND postmortem emit fails. Full synthetic17-phase valid
input still passes with real generated PNG decoding and binary/final validators.
The original raw window-diag-003 still fails:16/17 sustained,17/17 matching
images, normal engine exit0. This is recorded-data replay, not physical testing.

The capture suite has29methods; existing8axes methods remain. New cases include
both review gaps, inclusive/exact/one-tick boundary, malformed raw witnesses,
unknown/duplicate JSON, bad identity/clock/ranges, delayed/missing publication,
actual poll and supervisor/final-result error propagation. Run these plus the
normal baseline CTest, PnP readiness/cleanup and diagnostic-contract projects
in fresh host build directories. Exact-head Windows/Linux CI outcomes are
recorded in PR #48 and the final report; the versioned source record keeps
pending-at-creation separate from completed validation.

Original GPL source/tests/docs only; no binary/dependency/fixture distribution
or release approval. Existing license/relink holds remain. Preflight005 process
snapshot stays invalid, original bytes unavailable, original manifest preserved.
All physical raw files and earlier review evidence remain unchanged.

PR #47 itself is not patched or retargeted. Its Ready review state is not
physical readiness: its unchanged branch still contains the inherited ownership
masking path, and it has no new physical authorization. PR #48 must receive a NEW
independent review of the corrected head before any readiness recommendation.
PR #46 remains separate, with combined-tree integration unqualified. Keep all
three PRs unmerged, Issues33/37/39open, recoveryFAIL6/9, connected PnP FAILED,
Windows integration NO-GO and G5 frozen. No physical readiness request follows.
