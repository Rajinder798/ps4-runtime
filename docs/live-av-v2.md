# Independent live AV v2 — Gate 1

Gate: G4, related unresolved tracking issue #37. Base is main after PR #42,
`b3b30bde5f46263a9e03ba559b87c421edc94a57`. This is an independent opt-in
fixture/direct-session implementation, not a replacement for registered live-av.
No registration/preference schema, Settings UI, shortcuts or title mappings change.
Engine redistribution/license/source holds remain separate and open. New original
source is GPL-2.0-or-later; no engine, SDK or guest executable is committed.

## Input and failure policy

The guest opens one original Pad handle and reads it once per loop. Return 0 plus
connected=true and a valid timestamp uses actual buttons/sticks/triggers. Return 0
plus connected=false retains every raw field and applies effective zero buttons,
centered axes 128, zero triggers and audio command zero. Clearing the atomic audio
command happens before journal/graphics work. A nonzero API result retains the
initialized/output bytes but explicitly marks the payload invalid and records a
fatal observation. Zero connected timestamps, backwards timestamps, and recovery
that reuses a pre-disconnect timestamp also record and fail. No handle reopen,
API-error polling loop, fabricated timestamp, phase file or hidden retry exists.
Equal cached timestamps during continuous connection remain admissible; recovery
requires a strictly newer timestamp. The existing engine's slot reuse is a source
possibility, not a general reliability guarantee or durable physical identity.

Graphics and the 2048-frame AudioOut worker continue on disconnection. The live
16,000-us post-flip sleep remains explicit. Rendering, file I/O and scheduling add
to it; this is not a claimed frame rate or input-latency bound. Clearing the atomic
audio command (`audio_command = 0`) occurs immediately in the main guest loop upon
detecting disconnection, prior to flip submission and journal writes. The audio
worker observes this on its next iteration and generates silence for subsequent
blocks. However, clearing a command cannot retract or flush PCM blocks already
submitted to `sceAudioOutOutput()`. At 48 kHz, a 2,048-frame block represents
approx 42.7 ms of audio queue latency (or ~85 ms if double-buffered in the host
subsystem), which drains naturally through host audio endpoints. Block progression
proves neither PCM nor acoustic correctness, and orderly guest/audio teardown is
not claimed. The intermittent doubled-amplitude PCM anomaly remains an open
research topic tracked under Issue #33.

## Versioned journal and resource contract

`/data/live-av-v2.bin` has a 16-byte little-endian `<8sII` header: magic
`LAV2\0\0\0\0`, version **2**, record size **72**. It cannot qualify as legacy
24-byte live-input or PADHP1 evidence. Each record is `<IiiIQQQIII16B4s`:

| Offset | Field |
| --- | --- |
| 0,4,8,12 | Sequence, original handle, actual signed API return, effective audio command |
| 16,24,32 | Guest observation clock, actual raw Pad timestamp, completed flip (all uint64) |
| 40,44,48 | Audio blocks, raw buttons, effective buttons |
| 52,56 | Four raw axes, four effective axes |
| 60,61 | Raw connected flag and SDK count |
| 62,64 | Two raw and two effective triggers |
| 66,67,68 | Payload-valid flag, classified state, four zero reserved bytes |

Status values are connected=1, disconnected=2, API-error=3, invalid-timestamp=4,
stale-recovery=5. Fatal records have flip zero and cannot qualify as presented
images. Each normal frame encodes the whole record in binary pixels plus the
connection strip and challenge-derived checkerboard. Full 640x360 comparison is
independent of the guest policy. The audit duplicates the record fields and the
validator checks byte-exact agreement, ranges, ordering, handle and counters.

The journal is capped at **4 MiB / 58,254 records**, not the isolated 4096-record
cap. Exhaustion prints an explicit failure, clears the command and is not normal
completion. Existing **4 MiB strict audit** and **64 MiB total session output**
limits remain unchanged and may stop a session sooner. Specifically, per-frame
guest stdout logging produces ~350 bytes of JSON-wrapped strict-audit events
per sample, saturating the 4 MiB strict audit budget at ~11,980 samples (~3.3 minutes
at 60 Hz), well before the 4 MiB binary journal limit (58,254 records / ~16.2 minutes).
Because the schema-2 evidence contract strictly asserts 1:1 byte-for-byte parity
between the binary journal and every stdout sample line (`raw == HEADER + b''.join(...)`),
reducing textual logging in the guest requires a coordinated evidence-contract redesign. No records are rotated,
overwritten or silently discarded. For example, hypothetical 60 records/sec means
259,200 journal bytes/minute; this is arithmetic, not measured FPS. The short
final smoke recorded 32 records (2320 journal bytes), iteration gaps
30,010–34,824 us; it does not qualify long-session duration or exhaustion in a
real guest. Host tests exercise the limits and records beyond 4096.

## Independent direct session

Build using the existing pinned SDK/toolchain recipe:

```powershell
python tools/build_homebrew.py --sample live-av-v2 --llvm-bin build/tools/llvm-mingw-20261006-ucrt-x86_64/bin --inspector build/native/ps4-runtime.exe
```

The reviewed hashes are in `config/live-av-v2.json`; the new binary is pinned
separately. The contract adapter repeats the strict engine-attestation checks
without changing the shared historical verifier or passing v2 off as live-av.
The runner stages fresh private palette/audio/input configuration and uses the
existing owner-handle/Job Object supervisor, startup readiness and output guards.
Run only with appropriate session authorization:

```powershell
python tools/run_live_v2_session.py --engine build/upstream/windows-x64-strict/shadPS4.exe --engine-report build/upstream/strict-evidence/strict-build.json --fixture build/homebrew/live-av-v2/live_av_v2.oelf --supervisor build/native/ps4-startup-supervisor.exe --output build/live-av-v2/manual-new --volume-percent 0
```

Direct flags support existing log levels, application volume 0/50/100 and N/G.
They do not read/write saved preferences or register a title. Windows endpoint
mute remains independent. The ordinary runner sends no input, screenshots,
window close requests or audio capture. `closed` requires genuine readiness,
reason exited, status 0, no forced cleanup, retained-root/owner verification and
an independently empty process tree, plus final journal consistency. It does not
claim independent AV qualification. Immutable `session-owner.json` is published
once, complete before it becomes visible, using the existing initial publication
helper. A second ownership publication is an explicit failure. The v2 runner no
longer creates `session-status.json`: no current v2 runner, guide, validator or
documented direct-session consumer needs that mutable snapshot. Observers read
the immutable owner and original append-only audit; the final result is written
after supervision. External v2 scripts that used the retired diagnostic filename
must adopt this contract. Legacy live-av snapshots and their helper are unchanged.

## Non-interactive verification and retained failures

Two added suites bring the host count to **31**: exact compiled guest policy and
22 Python tests (originally 15) covering raw/effective semantics, malformed journals/images,
limits, continuity, strict process outcomes, original runner coordination using
inert host boundaries, human protocol permissions and generated physical-plan
acceptance/rejection. Generated data is explicitly **not** guest/hardware proof.
The original 29 suites and PR #41/#42 replay contracts remain intact, including
all 17 frozen PR #42 source snapshots. No existing validator is modified.

All ten local OpenOrbis fixture builds pass their exact source/binary contracts.
The first unpinned v2 candidate correctly failed the placeholder hash contract;
its candidate build report/log remain preserved. Final builds are independently
checked after recording the reviewed binary hash. This is not a guest retry.

Actual automated guest sessions (not physical tests):

| Session | Result |
| --- | --- |
| Initial v2 no-input close | Passed; 32 records, normal zero/empty exit |
| V2 launcher death | Driver failed by reading supervisor.json too early; original later report proves owner_exited with forced cleanup |
| V2 requested stop | Passed expected failure/contained cleanup, never normal close |
| V2 N keyboard cycles | Failed before qualification: status snapshot pathname temporarily absent |
| V2 G keyboard cycles | Failed before qualification: status snapshot WinError32 sharing violation |
| Final v2 no-input close | Passed after observer corrections; 32 actual records / 2320 bytes, normal zero/empty exit |
| Legacy live-av normal close and requested stop | Both passed expected outcomes on unchanged fixture |

There were eight actual sessions total. All three failed driver attempts remain
failed; none was automatically repeated. Host regressions cover waiting for
supervisor/root exit before consuming the report, and reading immutable owner
metadata plus append-only audit. The final smoke verifies the new observation
path, but does **not** establish successful N/G two-cycle qualification or the
corrected launcher-death driver on a fresh real guest at that collection point.
The later bounded run below supersedes those gaps only where explicitly passed.
No physical session,
USB action, system audio setting change or PCM qualification occurred.

Original private logs, journals, configuration, engine diagnostics and cleanup
reports remain under `build/live-av-v2/`; a SHA-256 artifact manifest retains
all attempts. The public machine-readable implementation report distinguishes
runner responses from expected-outcome driver reports; requested-stop is an
intentional failed runner with a passing containment test. It records exact
fixture hashes and 27 unchanged source/pin hashes. No machine-private full logs
or device serials are published. Hosted results are collection-time pending in
that report and must be checked at the final branch head before further work.

## V2-only publication correction and diagnostics

A later, separately approved A/N/G guest verification ran once per case at
`b896cf18cce9f0336e1cd7e12deaa7ad4fa5724b`:

| Case | Retained outcome |
| --- | --- |
| Launcher death | Passed expected `owner_exited` forced containment, two actual records; not normal close |
| N two cycles | Passed five exact Vulkan images, 478 actual records / 34,432 journal bytes and normal exit 0 |
| G two cycles | Failed: runner WinError 1175 during mutable status publication; later driver ownership failure during containment; 462 records / 33,280 journal bytes and only one qualifying neutral image |

The G guest independently recorded Cross then neutral approximately **1.935 Pad
seconds** later. The old failed driver did not persist its in-memory key-action
list; a G-down action follows from its reviewed control path, but no independently
timestamped host post or G-up action was retained. Guest neutral is not proof of
a requested key release. The separate focus-loss observation preceded the
publication exception; their causal relationship remains unknown. The original
1175 actor and exact API instant were not recovered or reproduced by bounded
host diagnostics. Later requested containment explains the subsequent invalid
window observations in this session, without resolving Issue #39.

The correction removes v2's unused continuous publisher, not the underlying
Windows deletion cause, G mapping, focus behavior or historical window issue.
The owner/audit/journal, Pad policy, 16-ms source sleep, graphics/audio thresholds,
readiness budgets and process supervisor remain unchanged. After a first monitor
fault the v2 callback requests containment without parsing/publishing again;
even if later cleanup completes, the first fault remains a failed result.

`tools/live_v2_diagnostics.py` supplies **append-only JSONL, at most 1 MiB and
8192 records per stream**. Exhaustion or I/O failure is explicit: no rotation,
replacement, retry or successful fallback. `session-diagnostics.jsonl` records
owner publication, the first exception (phase/type/message, OS codes, QPC/UTC and
up to 8192 traceback characters) before containment, and the separate supervisor
outcome. A diagnostic failure cannot replace the original error in the final
result. A final-result write failure also fails explicitly; no code can promise
durable evidence when the output filesystem itself is unavailable.

The automated driver's bounded `*-window.jsonl` retains existing ownership/focus
observations plus ordered key requests **before** the API call, successful post
returns separately, and actual guest button/connection transitions separately.
An API post is not proof of delivery. Failed results retain completed actions,
qualified captures, first failure, worker cleanup and original supervisor/runner
outcomes. No neutral observation fabricates a host release. No focus restoration,
rebind, keyboard mapping change, new input automation or automatic retry is added.
Future physical source attestations include this new diagnostic module.

Host-only fault injection covers immutable-owner collision, missing/malformed
owner/audit, startup expiry, repeated callback after first failure, cleanup and
final-write failures, request/post ordering, failed-case capture retention and
diagnostic limits. Generated records and mocked execution are host evidence only.
The legacy shared publisher/runner hashes are locked in a compatibility test;
the existing snapshot sharing and process-tree tests still run unchanged.
Original attempt manifests (233, 113 and 60 entries), 27 protected source/pin
hashes and the PR #41/#42 historical replays remain preserved. No guest or physical
session was repeated to validate this correction. Fresh A/N/G execution requires
separate approval at the corrected commit; v2 is not yet qualified for USB tests.

## Automated A/N/G re-run at the corrected commit (1 November 2026)

The owner approved one automated attempt per case on `main` `d40d358`. That
commit includes the publication correction, D1 first-failure diagnostics and the
A1 fixed-inventory guard. The engine, engine report, supervisor and fixture were
identical to the earlier round; the fixture matched its contract. The explicit
`--endpoint-inventory` came from a fresh read-only observation: six active render
endpoints, all muted, plus the console, multimedia and communications defaults.
Its hash is recorded and the identities are not committed. Full data is in
[the result record](../research/results/2026-11-01-live-av-v2-ang-rerun.json).

| Case | Outcome |
| --- | --- |
| A, launcher death | Passed as expected: `owner_exited`, forced containment, root exit and empty tree verified. Not a normal close. |
| N, two Cross cycles | Passed: 4 key actions requested and posted, 5 guest input transitions, 5 exact Vulkan images, 480 journal records / 34,576 bytes, owned-window close, exit 0 without forced termination |
| G, two Cross cycles | **Passed**: 4 key actions requested and posted, 5 guest transitions, 5 exact images, 478 records / 34,432 bytes, owned-window close, exit 0 without forced termination |

Each fixed guard passed: 94, 428 and 419 samples, the same six identities and
roles, all muted, with cleanup confirmed. No case recorded a first failure,
cleanup error or diagnostic fault.

The earlier G failure (WinError 1175 in the removed status publisher) did not
recur in this one attempt. That is not proof that it cannot recur, and its
original actor is still unknown. This run used automated key posts, not physical
input. PCM correctness and acoustic output were not tested. It closes the
retained automated A/N/G gap only. The two physical attempts below still need
their own hardware approval.

## Later physical acceptance — separate approval required

The opt-in collector and human guide are implemented, but have **not run**.
Automated modes cannot activate them accidentally. Physical mode rejects missing
scenario, unplug/reconnect and read-only endpoint-protocol permissions before
creating output or accessing a device. It verifies observer/engine/SDL identities,
retains tested source snapshots and independent SDL/Pad/image/cleanup evidence.
The native observer remains unchanged; removal-generated releases never count as
human release edges. A controller or window identity loss fails; no rebinding.

First resolve the retained automated observer-verification gaps with explicit
approval. A later hardware approval should cover two separate attempts:

1. **Recovery, six-minute maximum:** nine human F12 captures: neutral, Cross,
   release, held Cross, unplugged, disconnected progress >=5 guest seconds later,
   freshly reconnected neutral, restored Cross, release. One unplug/one reconnect;
   same original guest Pad handle. Then separately confirm readiness and click X.
2. **Disconnected close, six-minute maximum:** neutral and two disconnected
   captures >=5 guest seconds apart, one unplug/zero reconnects, then separately
   confirm readiness and manually close while still disconnected.

Every physical action has its own instruction/confirmation. USB readiness is
confirmed before the explicit USB instruction. Each held state needs three
seconds and 20 independent guest/native samples before F12. Reconnect has a
30-second budget starting at its explicit instruction. Exact images, matching
journal, fresh raw recovery, continuing flips/blocks, strict ownership until
close, exit 0, no forced termination and an empty process tree are mandatory.
The approved read-only endpoint observer must verify all available tracked
endpoints muted and unchanged per-device volume; it has no settings setters.
Any failure stops and preserves the attempt, without an automatic repeat.

### Physical collector failure finalization (source-only hardening)

The physical collector now latches the original FIRST exception before closing
its output streams or containing children. Its explicit cause and original
exception identity survive later failures. Physical-only finalization records
bounded SECOND descriptors separately (at most 32 records and a 64 KiB projection,
with dropped-record counts); it does not alter automated A1/D1 acceptance.

Worker, window, SDL observer, endpoint observer, guide and output-stream cleanup
are attempted independently. Stop-file, status, bounded wait, kill when needed,
post-kill wait and final status failures cannot skip the next applicable stage.
The result records child PIDs, observed exit codes, termination attempts and
confirmed/unconfirmed exit. A successful API cleanup call is recorded only as
that stage completing; it does not prove routing quiescence or physical safety.
An unavailable final exit status, nonzero exit, forced termination, missing
qualification or any required cleanup failure prevents acceptance.

`physical-result.json` gets one exclusive publication attempt after helper
finalization. Existing or partial bytes are never overwritten, repaired or
retried. Publication failure keeps the attempt failed, retains FIRST and bounded
SECOND on the raised exception, and attempts a bounded failure marker in the
fresh `physical-finalization.jsonl` journal. If that sink also fails, its failure
is separately exposed in the in-memory/exception diagnostics. No missing result
is reconstructed. A readable JSON payload alone is not proof that write/close
completed: a close failure may leave valid-looking bytes. Successful collector
return and independently reviewed lifecycle/publication evidence are required;
no fsync, power-loss durability or uninterruptible-call deadline is promised.

The inert host tests exercise the actual physical coordination with substituted
process/window/SDL/endpoint boundaries, including simultaneous cleanup failures.
They perform no device query, playback, controller action or guest execution.
The CLI permissions, human phases, reconnect budget and strict evidence oracles
remain unchanged. The physical per-seen-Console-default protocol is still **not
fixed all-active-render A1 acceptance**; fresh machine inventory, helper/source
attestation and an explicitly approved physical endpoint policy remain separate
preflight requirements.

### Engine root-exit timing for the close check

`verify_physical` still requires `root_exit_qpc_seconds -
last_guest_seen_qpc_seconds <= 0.35`; the bound is unchanged.
`root_exit_qpc_seconds` used to be taken after `process.wait()` on the Python
worker, which exits only after its own verification and publication. In
`physical-recovery-v2-003` that was 0.622 s, while `supervisor.json` (engine root
exit and tree cleanup) was written at about +0.07 s.

The collector now polls the engine root itself during the close phase, as the
disconnected-close collector does. It uses `WaitForSingleObject(..., 0)` on the
process handle retained by the owned-window lifecycle diagnostics, and records
the first exit it observes. A wait result other than signaled or timeout fails.
A worker exit while that root is still alive fails. If the exit was not observed
during the loop, the later worker-exit time is used, which is stricter. Host
tests drive the real close loop. The earlier `physical-recovery-v2-003` FAILED
verdict is not revised.

This is a G4 software-safety prerequisite only. Historical window-diag-003 remains
FAILED; preflight-005/process-raw.json remains INVALID; DualSense recovery remains
FAILED at 6/9. Issues #33/#37/#39 stay OPEN, G4/Windows live integration remains
NO-GO and G5 remains FROZEN. Implementation and host CI authorize no physical
preflight or PR merge. Rollback requires an owner-authorized source revert; it
must not restore physical permission or erase historical failed evidence.

### Physical recovery attempt physical-recovery-v2-001 (1 November 2026)

The owner approved one recovery attempt. It had one unplug, one reconnect and the
legacy per-seen-Console-default endpoint protocol. The engine, fixture and
supervisor matched the contract, and the SDL probe attestation matched `main`
`a5eece4`. Full data is in
[the result record](../research/results/2026-11-01-live-av-v2-physical-recovery-v2-001.json).

**FAILED at 6 of 9 because of a configuration error, not a recovery result.**
Neutral, Cross, release, held Cross, unplugged and disconnected progress all
qualified. The reconnect came 8.7 s after its instruction, inside the 30-second
budget, and the controller was reopened. At that moment the Console default
briefly read a muted endpoint at volume 1.0. The observer then stopped with
"Observed Windows endpoint change", and the collector stopped the session.

The observer passed was the plain `ps4-endpoint-observer.exe`, which rejects
every default-endpoint change. The separately approved
`ps4-hotplug-endpoint-observer.exe` tolerates default changes while every seen
endpoint stays muted. Both accept `--watch`, and the collector found the wrong
helper only afterwards, when it rejected the report as an incomplete hotplug
observation.

- **Audio:** every one of the 5,084 samples was muted, and the guest ran at 0%
  volume. A read-only check afterwards found the original defaults and all six
  endpoints muted.
- **Cleanup:** the worker, SDL observer and endpoint observer all confirmed
  cleanup. No retry occurred.
- **Comparison:** earlier recovery attempts used the hotplug observer and failed
  at 6 of 9 for a different reason, a reconnect over 30 s.

`PhysicalMutedEndpoint` now refuses to continue unless the endpoint observer's
first complete record has the hotplug observer's sample schema. That check runs
before the SDL observer or the guest starts. `tests/hotplug_endpoint.py` is
unchanged. Host tests reject the plain, all-render, malformed and changed-default
first records. They also show that the previous `__enter__` accepted the plain
observer. Run read-only for two seconds each, the real hotplug observer is
accepted and the real plain observer is rejected. A new attempt needs new owner
approval.

### Physical recovery attempts physical-recovery-v2-002 and -003 (1 November 2026)

Each attempt had its own owner approval. Both used the separately approved
`ps4-hotplug-endpoint-observer.exe`, which passed the new first-sample check.
Inputs were identical to attempt 001, the guest ran at 0% volume, and every
child process confirmed cleanup. The hotplug endpoint evidence passed both times,
with no default changes and every tracked endpoint muted. Full data is in the
[002](../research/results/2026-11-01-live-av-v2-physical-recovery-v2-002.json)
and [003](../research/results/2026-11-01-live-av-v2-physical-recovery-v2-003.json)
records.

**002: FAILED at 4 of 9.** The controller was removed 6.9 s after the unplug
instruction. A new wired instance appeared 0.274 s later, before any reconnect
instruction, so the collector correctly stopped. The owner reports the plug may
have touched the port again while unplugging. This is not an engine or collector
fault.

**003: FAILED, with all 9 of 9 phases qualified.** This is the first time the
live AV v2 recovery sequence has qualified every phase:

- **Unplug and reconnect:** removal 4.4 s after the unplug instruction, and a new
  wired instance 9.5 s after the reconnect instruction.
- **Guest:** 4,821 journal records (347,128 bytes) verified. The engine exited 0,
  with no forced termination and an empty tree.
- **Audio:** 5,612 endpoint samples.

Every close condition passed except one. `verify_physical` requires
`root_exit_qpc_seconds - last_guest_seen_qpc_seconds <= 0.35`; the measured value
was **0.622 s**.

File modification times, mapped to QPC through window-trace events that carry
both clocks (12 pairs, 1.4 ms spread), place the events like this, relative to
the last guest record:

| Event | Offset |
| --- | --- |
| Bound window destroyed (owner's close) | −0.119 s |
| `supervisor.json` written, after engine root exit and tree cleanup | +0.073 s |
| Worker's diagnostics and `session-result.json` written | +0.306 / +0.529 s |
| Collector observed the **worker** exit | +0.622 s |

In this collector, `root_exit_qpc_seconds` is taken after `process.wait()` on the
Python worker. The sibling disconnected-close collector instead sets it when it
observes the engine root exit, and its passing physical run measured 0.226 s. The
same 0.35 s bound therefore covers the worker's post-exit publication here, not
only engine shutdown.

The rule and the FAILED verdict are unchanged. Measuring the engine root exit, or
changing the bound, is a separate owner decision. Issue #37 recovery is not
qualified.

### Physical recovery attempts physical-recovery-v2-004 and -005, and engine shutdown timing (1 November 2026)

Both attempts ran after the engine root-exit timing correction, each with its own
owner approval, and both used the hotplug endpoint observer with the guest at 0%
volume. Every child process confirmed cleanup. Full data is in the
[004](../research/results/2026-11-01-live-av-v2-physical-recovery-v2-004.json),
[005](../research/results/2026-11-01-live-av-v2-physical-recovery-v2-005.json) and
[shutdown timing](../research/results/2026-11-01-live-av-v2-engine-shutdown-timing.json)
records.

**004: FAILED at 6 of 9.** At reconnect, 7.6 s after its instruction, the tracked
default stayed the default and stayed muted. It was the virtual FxSound enhancer
endpoint, and its volume read 1.0 instead of 0.4208. The hotplug observer stopped
under its unchanged per-device-volume rule, and a later read-only check read
0.4208 again. Attempt 001 saw the same 1.0 reading at reconnect. For 005 the owner
exited FxSound and made Speakers (Realtek) the Console/Multimedia default.

**005: FAILED, with all 9 of 9 phases qualified.**

- **Audio and guest:** clean hotplug endpoint evidence (4,520 muted samples, no
  default changes) and 3,812 journal records.
- **Close:** exit 0, no forced termination. Every close condition passed except
  one: measured at the engine root, the exit came **0.442 s** after the last guest
  record, against the bound of 0.35 s.
- **Timeline:** the window was destroyed at −0.065 s and `supervisor.json` was
  written at +0.367 s.

**Shutdown timing.** Five owner-approved automated `no-input-close` runs, with
Realtek as the default, measured window destroy to `supervisor.json` at
0.181–0.203 s. Other sessions today:

| Session | Shutdown |
| --- | --- |
| Automated N and G, FxSound default | 0.201 / 0.202 s |
| Recovery 003 | 0.192 s |
| Pad-axes window-diag-005 | 0.163 s |

The hypothesis that Realtek slows shutdown is rejected. Attempt 005's 0.432 s is
the only slow close of ten. These are file-time approximations, not native exit
timestamps.

The 0.35 s bound is kept. As agreed beforehand, a fast typical shutdown makes one
more physical attempt fair. Issue #37 recovery remains unqualified.

### Physical recovery attempts physical-recovery-v2-006 to -008: first pass (1 November 2026)

Each attempt had its own owner approval. Speakers (Realtek) was the default,
FxSound was exited, and the hotplug observer ran with the guest at 0% volume.
Records:
[006](../research/results/2026-11-01-live-av-v2-physical-recovery-v2-006.json),
[007](../research/results/2026-11-01-live-av-v2-physical-recovery-v2-007.json),
[008](../research/results/2026-11-01-live-av-v2-physical-recovery-v2-008.json).

- **006: FAILED at 5 of 9.** The step-6 (disconnected-progress) screenshot was
  rejected as short-held. The owner reports pressing F12 before the panel asked.
  The reconnect instruction was never issued.
- **007: FAILED before guest launch.** The SDL hotplug observer recognized two
  DualSense gamepads and refused to continue. Windows had the controller on USB and
  Bluetooth at the same time. The preflight had checked only the USB interfaces.
  It now also runs the SDL probe's read-only `--discover` check (exactly one
  gamepad). The owner then turned Bluetooth off.
- **008: PASSED.** This is the first passing live AV v2 physical recovery. It
  qualified all 9 phases with 9 sequence-bound screenshots: one removal 7.0 s after
  the unplug instruction, and one reconnect 15.3 s after its instruction, on a new
  wired instance.
  - Acceptance reported 9 phases, 1 removal, 1 reconnection and a verified normal
    exit.
  - Guest: 4,704 journal records (338,704 bytes), exit 0, no forced termination,
    empty tree.
  - Close: the engine root exited 0.138 s after the last guest record, against the
    unchanged 0.35 s bound. `supervisor.json` was written at +0.071 s and the worker
    exited at +0.63 s, so the previous worker-exit measurement would have failed.
  - Audio: all 5,498 hotplug endpoint samples were muted, with no default changes.
    Every child process confirmed cleanup, and no synthetic input was sent.

This is one passing session of one versioned fixture on one wired-USB host setup.
It is not general hotplug reliability. PCM correctness, acoustic output, Bluetooth
and the separate disconnected-close scenario were not tested. Whether it resolves
Issue #37 is an owner decision.

General V2 USB recovery reliability, original live-av recovery, full G4 and
commercial-game compatibility remain unverified. Issues #33/#37/#39 stay open.
No PR creation, registered integration, default migration or merge is authorized.
