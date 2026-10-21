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
to it; this is not a claimed frame rate or input-latency bound. Clearing a command
cannot retract already queued PCM. Block progression proves neither PCM nor
acoustic correctness, and orderly guest/audio teardown is not claimed.

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
limits remain unchanged and may stop a session sooner. No records are rotated,
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
once; the diagnostic `session-status.json` retains only the latest sample and
record count. The acceptance observer reads immutable owner metadata and the
original append-only audit, avoiding status replacement races.

## Non-interactive verification and retained failures

Two added suites bring the host count to **31**: exact compiled guest policy and
15 Python tests covering raw/effective semantics, malformed journals/images,
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
corrected launcher-death driver on a fresh real guest. These remain explicit
verification gaps for a separately approved bounded run. No physical session,
USB action, system audio setting change or PCM qualification occurred.

Original private logs, journals, configuration, engine diagnostics and cleanup
reports remain under `build/live-av-v2/`; a SHA-256 artifact manifest retains
all attempts. The public machine-readable implementation report distinguishes
runner responses from expected-outcome driver reports; requested-stop is an
intentional failed runner with a passing containment test. It records exact
fixture hashes and 27 unchanged source/pin hashes. No machine-private full logs
or device serials are published. Hosted results are collection-time pending in
that report and must be checked at the final branch head before further work.

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

V2 USB recovery, general reliability, original live-av recovery, full G4 and
commercial-game compatibility remain unverified. Issues #33/#37/#39 stay open.
No PR creation, registered integration, default migration or merge is authorized.
