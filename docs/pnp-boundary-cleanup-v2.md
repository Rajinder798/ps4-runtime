# PnP boundary cleanup v2 â€” isolated offline host add-on

This module is a **HOST-ONLY process-ownership and file-only endpoint analysis prerequisite** for G4 / Issue #37. This change is intended as stacked Draft PR #44 based on Draft PR #43, the isolated PnP Readiness v2 foundation. It does not make PnP readiness, controller reconnection, or guest recovery pass.

## Provenance and boundaries

These three source files were originally extracted from reviewed G4 commit `418692a41bb11df5d81058880b4cad6549e0c81f`:

- `tools/boundary_cleanup_v2.py`
- `tests/pnp_readiness_v2/job_inert_v2.cpp`
- `tests/pnp_readiness_v2/boundary_cleanup_v2_tests.py`

The cleanup module and tests now harden the reviewed unexpected-exception path;
the inert worker is unchanged. The standalone CMake registration is restored from the same G4 source, while the foundation collector, Windows PnP provider, parser, observer, validator and production paths remain unchanged. This add-on does **not** integrate any rejection-v1 shared-cache acquisition, HID-list assessment, stage ledger or Windows live snapshot adapter. The integration-readiness audit's NO-GO remains in effect.

## Host cleanup contract

`cleanup_owned` handles already-owned helper roots. It requests observers to stop before the endpoint guard, waits for confirmed exits and exact Windows Job Object membership, retains first-failure provenance and records unknown membership or potential forced close without treating it as a clean shutdown. Inert Windows host tests cover normal close, descendants that outlive known roots, kill-on-job-close containment, stop-request failures, incomplete membership and premature guard exit. The inert worker does not query devices or run guest/SDL/engine code.

Unexpected membership, polling, clock, pause or handle-release exceptions cannot
skip final job closure. A nested `finally` path attempts explicit job termination
on bookkeeping failure, then closes the kill-on-close job even if containment
bookkeeping fails. Ordinary exceptions return an uncertified cleanup result;
KeyboardInterrupt/SystemExit propagate after the same fail-safe path. Fixed
warning categories retain the original first failure without serializing exception
messages. Nonfinite/reversed clocks and a stalled-clock iteration cap fail closed.

Normal guard ordering, the cooperative timeout (default three seconds), exact
membership proof and waited-root release remain unchanged. Once fail-safe cleanup
is needed it never becomes a certified normal shutdown. `fail_safe_used`,
`explicit_termination`, `close_ok` and `unreleased_root_handles` distinguish the
attempts and uncertainty. An independent kernel wait of at most 250 ms per retained
root can release a signalled process handle after termination/close, without
calling the failed poll/release/clock/pause callback. This post-containment handle
observation is not an extension of the cooperative deadline or proof of normal
exit. OS calls are not hard real-time guarantees. If exit/handle close cannot be
established, the caller retains that reported root handle and the job object on
close failure; it must finish disposal and may never treat the result as clean.

Deterministic fault matrices exercise OSError/RuntimeError at each requested
boundary, late failures, failed close/containment/emergency release, invalid or
stalled clocks and interruption. Owned inert Windows cases exercise the independent
kernel fallback for all five bookkeeping boundaries; no real observer is launched.

`endpoint_coverage` only analyzes preexisting in-memory/file-provided samples. It never opens audio endpoints or changes system settings. It returns sample-supported muted intervals, unverified gaps and identity/volume-change findings; `continuous_mute_proven` is always false. A muted sample is not proof of continuous mute.

`WindowsJob` only manages processes explicitly assigned by a caller. Callers must prevent process work before job assignment. The module has no automatic launch path and provides no permission to run live observers.

## Host-only validation

From repository root:

```sh
cmake -S tests/pnp_readiness_v2 -B build/pnp-boundary-host -DCMAKE_BUILD_TYPE=Release
cmake --build build/pnp-boundary-host --config Release
ctest --test-dir build/pnp-boundary-host -C Release --output-on-failure
```

The third registered suite, `boundary-cleanup-v2`, runs controlled deterministic Python scenarios on both hosts and owned inert Windows Job Object tests only on Windows. The foundation's `pnp-policy-v2` and `pnp-evidence-v2` remain registered. CI separately runs the boundary suite on Windows and Linux; the existing PnP foundation CI also executes all three.

## Review and historical holds

Draft PR #43 must be reviewed before this stacked PR is merged. Retarget this PR to `main` only after #43 merges and revalidate CI. Neither PR authorizes live PnP, controller USB operations, guest execution, driver/audio/settings changes or a production bundle repin.

The connected initial PnP snapshot stays **FAILED, exit 1**. Historical guest recovery remains **FAIL 6/9**. The current production Python executable fails the old pinned identity gate; old attestations, immutable historical evidence and all original failure verdicts must remain unchanged. Issues #33, #37 and #39 remain open.

GPL-2.0-or-later notices are retained; no new external package or binary is introduced.
