# Close while the USB DualSense remains disconnected

Gate: G4 lifecycle research for issue #37. Base: main
`25e9216a1b7cda02d33881e40bee5c7d667df765`, after merged PR #41.
Status: **one physical disconnected-close session passed**, using implementation
commit `d7ef5df24b310962b60fd8de17a68cb05a4a79ff`. The owner separately approved
that physical session and final PR preparation. Further physical sessions/USB
actions and merging still require explicit approval. No engine,
fixture, production launch, preference, supervisor or dependency pin is changed.

## Actual physical-001 result

The [published evidence](../research/evidence/2026-10-21-disconnected-close/manifest.json)
contains original guest audit/journal, SDL state/removal events, three unchanged
PNG readbacks, human confirmations, ownership diagnostics, endpoint observations
and supervisor cleanup records. No new physical test was run during finalization.

| Captured state | Guest sequence | Actual rc / connected / Pad timestamp | Completed flip | Audio blocks |
|---|---:|---|---:|---:|
| Connected neutral | 89 | 0 / 1 / 11214975 | 90 | 244 |
| Disconnected | 310 | 0 / 0 / 0 | 311 | 850 |
| Disconnected progress | 393 | 0 / 0 / 0 | 394 | 1077 |

All 607 actual Pad records match the 43,720-byte journal. The original handle
remained 1. All 354 disconnected records preserve connected=0, raw timestamp=0
and raw axes [0,0,0,0], separately recording effective axes [128,128,128,128],
zero buttons/triggers and audio command zero. Actual return code was 0 throughout;
no error return was presented as success. The two disconnected images are
**9.683422 guest seconds apart**. The observed absent guest interval spans
41.249735 seconds. Three full 640x360 comparisons verify 691,200 pixels total.

The sole wired nonvirtual DualSense used SDL instance 2: one actual removal,
zero reconnections, 711 native state observations and no button events. Engine
controller counts were [1,1,0] with one slot-zero registration. Human confirmations
separately precede the unplug and normal-close instructions. No input or close
message was injected. Normal user close produced exit reason `exited`, exit 0,
zero active processes before cleanup, no forced termination, verified retained
root exit, verified owner watch and an empty process tree. All observers exited
normally; postflight discovery finds no remaining DualSense USB interface or
conflicting test process.

Ready-to-final-confirmation time was 74.665569 seconds within the six-minute
budget. Root exit was observed 12.783955 seconds after the explicit close
instruction, within 30 seconds. This includes the human's delay before clicking
X and is not click-to-exit latency. No window-identity failure was recorded;
bound-window destruction occurred after the instructed close. Polling/lifecycle
diagnostics do not rule out all transitions between observations or resolve #39.

The session has 2,426 endpoint observations over 75.842 seconds: one observed
endpoint identity, zero default changes, every available tracked endpoint muted,
and unchanged per-device volume 0.699999988. No settings setters were used. This
does not establish continuous endpoint identity, PCM/acoustic correctness or
ordered guest-thread/audio-worker teardown.

### Failed preflight preserved

`preflight-001` stopped before guest launch when the original read-only sample
reported muted=false. Its raw sample/stderr and explicit failed status are
published separately. The owner manually muted Windows and explicitly approved
repeating read-only preflight; `preflight-002` then passed. Those discovery checks
are not physical acceptance stages or additional USB attempts. No failed physical
session occurred, and no action/session was automatically repeated.

Six error-labelled startup messages exactly match the previous successful
physical-004 baseline: an interpreter-path notice, missing optional Fios2/libc
module pairs and stub-labelled scePadInit. They remain disclosed. Strict imports
had zero unresolved entries, actual guest observations passed and there was no
guest FAIL marker or new warning. These labels were not suppressed or repaired.

### Source equivalence and publication

The tested runner, guide, SDL observer, raw/phase/image/endpoint validators,
ownership diagnostics, fixture and startup helper sources are unchanged during
finalization. All 17 original tested-source snapshots are retained and compared
against current LF-normalized source in a new host replay suite. Final changes
after the physically tested commit add only replay tests, their CMake registration,
evidence and documentation. Exact input/source hashes and provenance are in
[attestation.json](../research/evidence/2026-10-21-disconnected-close/physical-001/attestation.json).

Published original files are byte-identical copies. Qualification/attestation,
engine review and summary files are explicitly labelled derived projections;
their original private result/context/log hashes remain recorded. Absolute input
paths and full engine/machine inventory are omitted from those projections.
Generic vendor/product/type, session SDL ID, PID/thread/HWND and timestamps are
retained as relevant evidence; serials, MACs and private device paths are absent.
No original private artifact is rewritten. A nested evidence-only attributes
file preserves recorded line endings without changing engine/workflow inputs.
Historical implementation/summary records retain their collection-time approval
and CI status; the [final report](../research/results/2026-10-21-disconnected-close.json)
and PR description record the later finalization approval and completed checks.

## Separate acceptance contract

The PR #41 seven-stage runner, guide, validator and original successful/failed
artifacts remain unchanged. Its `[connected, disconnected, connected]` contract
cannot qualify this separate `[connected, disconnected]` scenario. The new
`tests/pad_disconnected_close_guest_tests.py` reuses only existing raw record,
exact image, ownership, supervisor and read-only endpoint primitives. Its own
validator is `tools/pad_disconnected_close_evidence.py`.

The SDL observer adds `--watch-disconnect report stop ready timeout-ms
--disconnect-authorized`. This mode needs no reconnect authorization and never
opens a second gamepad. After the initial inventory event, any added device or
repeated removal fails; no retry occurs. Original watch/hotplug modes retain
their existing behavior. Disconnected native payloads remain invalid/null;
removal-generated button-up events are never evidence of a human release.

The guest is the unchanged `pad-hotplug-av` source/OELF. Actual return code,
timestamp, connection/count and raw controller payload are journalled separately
from effective neutral buttons/triggers/axes and audio command zero. A nonzero
Pad result remains an API failure, not successful absence. The same guest handle
must remain unchanged. Connected controls must be neutral; Cross is not part of
this procedure. No keyboard/controller input is injected.

Three full 640x360 Vulkan readbacks must match their entire guest record and
random palette, with no stale/extra/reused images:

1. Initial connected neutral.
2. Disconnected, effective neutral.
3. Still disconnected at least five **guest observation seconds** after image 2,
   with strictly increasing completed flips and audio-block counts.

Each capture retains the existing three-second/20-sample guest and SDL holds,
350 ms observation-gap limit and connected neutral axis limits (guest 120-136,
SDL +/-2048). Raw disconnected timestamps/payloads are preserved, never invented
or normalized. Guest-clock differences, not disconnected raw Pad timestamps,
measure progress. Audit and 72-byte journal/header/reserved bytes must agree
exactly. Partial final writes are rejected and preserved, never truncated to pass.

Audio blocks demonstrate completed AudioOut submission progress only. They do
not establish PCM correctness, acoustic output/silence or queued-buffer draining.
Normal engine window close uses `std::quick_exit(0)`; the fixture has no worker
stop/join protocol. This verifies process shutdown, not natural guest completion,
ordered guest-thread teardown or an engine lifecycle repair.

## Close permission and cleanup

The human must confirm every action and F12 notification in a UTF-8 instruction
panel. Unplug readiness precedes the actual instruction; early removal fails.
After all three verified images, a separate close-readiness click checks the
still-owned, running window and fresh disconnected guest before displaying
**CLOSE GAME NORMALLY NOW**. No close message is sent by the harness.

Ownership is strict until that explicit close instruction. Afterwards only
bounded process exit is expected; lifecycle diagnostics continue without
selecting or using another HWND. The process object retained by the existing
diagnostic/supervisor is observed, not a PID reopened after exit. Premature
window loss/root exit remains a failure. The instructed close has a 30-second
exit deadline within the six-minute total session budget.

Successful supervision requires `reason=exited`, exit 0,
`active_before_cleanup=0`, `forced_termination=false`, `tree_cleanup=true`,
`root_exit_verified=true`, and `owner_watch_verified=true`. A zero root exit
with leftover descendants fails even if forced cleanup subsequently empties the
job. The SDL observer must keep recording absence through root exit and human
close confirmation, then stop normally. Observer, lifecycle and endpoint cleanup
errors also fail. Failed attempts retain logs, images, source/tool hashes and
original supervisor reports. There is no automatic restart/repeated action.

## Non-interactive checks

`pad-disconnected-close-contract` is the 28th host suite. Generated records,
images and inert UI widgets test authorization gates, actual confirmation paths,
exact journal/pixel rejection, connection identity/continuity, five-second
progress, endpoint-protocol consent, early/unowned close, nonzero/forced/orphaned
exit and remaining absence. They are not physical hardware evidence. Optional
`PS4_DISCONNECTED_CLOSE_OBSERVER_CLI` checks use only invalid native arguments,
rejected before SDL initialization. Hosted CI skips that optional local helper.

The new SDL helper is built with `/W4 /WX` against the already pinned static SDL,
without initializing it. Original fixture/engine/dependency inputs and PR #41
evidence are rechecked; the existing 27 suites and original seven-stage replay
must still pass. Windows/Linux host CI can run without starting a guest or
accessing a controller/audio device. No new fixture build is needed for unchanged
guest bytes. See the implementation result for exact local hashes/results;
host tests/builds never grant physical acceptance.

`pad-disconnected-close-recorded-evidence` is the 29th suite. Its five tests
rehash all published bytes, replay actual 607 records and three exact PNGs,
verify SDL/human/ownership/endpoint/cleanup evidence, compare the 17 tested source
snapshots and reject corrupted variants of actual evidence. Replay does not
start a guest, controller or audio device and is not a second physical run.

The historical [implementation report](../research/results/2026-10-21-disconnected-close-implementation.json)
records 28/28 final local suites (51.14 seconds), all 15 new methods with the
optional prebuilt helper enabled, the successful `/W4 /WX` observer build and
exact source/tool/fixture hashes. An initial sandbox run failed two unchanged
launch/shortcut suites because hard-link creation was denied; its log is
preserved. A deliberate run outside that restriction passed without modifying
production behavior, followed by the final full run including the new inert
runner test. All 67 original published hotplug artifacts and nine local fixture
binary sets rehashed correctly. Main's post-merge Windows/Linux, nine fixture
and strict source-engine builds passed; the latter's completed log/evidence
review found only existing warnings and three Git line-ending notices. Branch
CI is recorded separately after pushing the finalized source; the report retains
its collection-time pending status. No physical or guest session was started
during that implementation-only phase.

## Reproducing the human procedure — requires new separate approval

1. Obtain separate owner approval for one physical test, one USB unplug and the
   existing hotplug endpoint observation protocol. Recheck already-muted Windows,
   sole wired nonvirtual DualSense, pinned tool/fixture hashes and absence of
   conflicting owned processes. Do not change system settings or reconnect USB
   as setup without the owner's authorization. Stop on a preflight blocker.
2. Open one fresh session. The human clicks Ready, keeps controls untouched and
   confirms neutral; F12 is requested only after qualification. Confirm the
   screenshot notification. Use F12, never F11.
3. The panel asks readiness, then explicitly instructs one unplug. The human
   unplugs once and confirms; leave USB disconnected for the rest of the test.
4. Confirm/capture disconnected state, then confirm continued absence and capture
   again after at least five guest seconds of independently checked progress.
5. Confirm readiness to close. Only at CLOSE GAME NORMALLY NOW, click the game
   window X and confirm completion. Keep the instruction panel open until the
   observer/engine evidence and cleanup checks finish.
6. Leave USB disconnected and Windows muted. Stop; do not reconnect or rerun.

A future separately approved invocation uses:

```powershell
python tests/pad_disconnected_close_guest_tests.py --engine <pinned-engine> --engine-report <strict-report> --fixture <unchanged-hotplug-oelf> --supervisor <supervisor> --sdl-observer <newly-built-probe> --muted-endpoint-observer <hotplug-endpoint-observer> --output <fresh-output> --physical-test-authorized --disconnect-authorized --hotplug-endpoint-protocol-authorized
```

The existing alternate endpoint observer only reads settings: every seen
available default endpoint must remain muted at its own unchanged volume.
Default transitions and unavailable fields are recorded honestly. It neither
changes devices nor guarantees continuous endpoint identity or between-sample
state. The old stricter endpoint protocol is unchanged.

Remaining limits: one physical disconnected-close pass does not establish
repeated hotplug reliability, original `live-av` recovery,
Bluetooth, multiple devices/users, PCM/acoustic correctness or full G4. Issues
#33, #37 and #39 remain open. Code is GPL-2.0-or-later; no SDK, engine or guest
executable binary is published, and release/source/relink holds remain open.
