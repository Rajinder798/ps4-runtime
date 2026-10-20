# Isolated Pad hot-plug AV implementation

Gate: a G4 research prerequisite for [issue #37](https://github.com/Rajinder798/ps4-runtime/issues/37),
based on verified main `87d213caeff0a5b98113f7baf837e92233d3d903` after PR #40.
Status: **implemented and built; no actual guest/controller execution yet**.
Neither graceful physical disconnect/reconnect nor readiness to merge is established.
The owner approved implementation and non-interactive host/build tests only.
Do not start the opt-in hardware runner or open a PR without separate approval.

## Why a separate fixture

The preserved PR #36 unplug trial reports native removal, engine controller count
zero and `live-av: FAIL pad read/connection`. That fixture deliberately combines
API-error, disconnected and zero-timestamp checks in one fatal guard. The exact
old rejected field was not recorded. Contained forced cleanup is not graceful
support. All original failed attempts and the unchanged original `live-av`
source, binary, schema, preferences and shortcut profiles remain intact.

The pinned engine has a source path that successfully returns a disconnected Pad
report with zero timestamp/sticks/buttons/count. Its removal path leaves the
guest-handle-to-slot mapping intact; its add path can reuse the freed slot.
That supports testing a fixture policy without an engine patch, but does not
prove real reattachment, slot reuse or recovery. No engine defect has been established.

`research/homebrew/pad_hotplug_av/main.cpp` is an independent original fixture.
Only its new `config/pad-hotplug-av.json` is added. Existing engine, SDK, SDL,
dependency, research patch and eight fixture pins are unchanged. The new profile
is not registered for ordinary CLI/shortcut launch or Settings.

## Exact input policy

| Actual Pad result | Recorded status | Effective application input |
| --- | --- | --- |
| Return 0, connected, nonzero admissible timestamp | 1: connected | Raw buttons/axes/triggers; Cross drives audio command 0/1 |
| Return 0, disconnected | 2: disconnected | Zero buttons/triggers, centered axes 128, audio command 0 |
| Nonzero return, including positive/unexpected results | 3: API error | Neutral, then explicit fatal marker; output payload flagged invalid |
| Return 0, connected, timestamp zero | 4: invalid timestamp | Neutral, then explicit fatal marker |
| Backwards Pad timestamp, or reconnect reusing a pre-disconnect timestamp | 5: stale timestamp | Neutral, then explicit fatal marker |

The fixture opens one Pad handle once and reads it once per scheduled iteration.
It never retries an API error, reopens a handle, invents Pad timestamps or rewrites
raw values to make the read look connected. Repeated cached timestamps during a
continuous connection are admissible; resuming after absence requires a greater
timestamp than the last connected report. Host acceptance separately requires
Pad timestamp progression during the requested held/released input intervals.

The effective audio command is published atomically before file/graphics work.
Fatal paths also clear it. The AudioOut worker continues submitting 2,048-frame
stereo blocks; disconnected policy requests silence. Queued buffers can take
time to drain. Audio block counts establish progress only, not PCM correctness,
acoustic silence or an audio repair. Existing PCM thresholds remain unchanged;
[issue #33](https://github.com/Rajinder798/ps4-runtime/issues/33) remains unresolved.

The new fixture sleeps 100 ms after each completed flip, with a fixed 4,096-record
limit. This is a bounded research cadence, not an FPS/latency result. Each image
has a green connected or red disconnected strip, a challenge-derived checkerboard
responding to effective Cross, and binary pixels encoding its entire observation.
The guest receives only palette/audio challenges, never host phase expectations.

## Versioned raw/effective evidence

`/data/pad-hotplug.bin` begins with `<8sII`: magic `PADHP1\0\0`, version 1,
record size 72. Each little-endian record is fixed by C++ size/offset assertions:

| Offset | Data |
| --- | --- |
| 0 | uint32 sequence |
| 4, 8 | int32 original Pad handle, actual API return code |
| 12 | uint32 effective audio command |
| 16, 24, 32 | uint64 guest observation clock, raw Pad timestamp, completed flip |
| 40, 44, 48 | uint32 audio block count, raw buttons, effective buttons |
| 52–55, 56–59 | Four raw axes and four effective axes |
| 60, 61 | Raw connected and SDK count bytes |
| 62–63, 64–65 | Raw and effective L2/R2 bytes |
| 66, 67 | Payload-valid byte and status enum |
| 68–71 | Four zero reserved bytes |

On an API error, bytes read from the initialized output buffer are retained
but marked invalid; they are not a successful observation. Fatal reports have
flip 0 and are journalled/logged before the failure marker, without claiming
completed graphics. Successful disconnected reports retain timestamp/axes/count
as returned; effective neutral is explicitly a fixture decision, not a measured
physical stick center. Count is not a durable physical-device identifier.

The pinned SDK names the connection-count field `count`; its offsets for connected,
timestamp and count are asserted against the used ABI. No SDK header is changed.
The strict text log duplicates every field. `tools/pad_hotplug_evidence.py`
independently checks raw/effective policy, fixed schema/reserved bytes, unchanged
handle, clocks, progress and byte-exact agreement between file and guest log.
Its image oracle checks every 640×360 pixel against that exact original record.
Fatal evidence can pass record-integrity checks for preservation while still
being explicitly rejected for successful physical acceptance.

## Opt-in native observer and safety

The existing observer adds `--watch-hotplug` only with both
`--disconnect-authorized --reconnect-authorized`. Legacy `--watch` and
`--watch-axes` behavior is retained. One genuine removal and one newly added
instance are allowed. The new instance must be the sole nonvirtual PS5-type
Sony `054c:0ce6` device and report USB wired. It is opened once; ambiguity,
open failure, remapping, another cycle or timeout fails without retry.

`hotplug_opened`, `hotplug_removed`, `hotplug_state` and `sdl_button` records
contain episode/instance identity and QPC timing; device events/edges also retain
SDL timing. The initial inventory has SDL event timestamp zero explicitly,
because it is not a new-device event. Disconnected snapshots have invalid input
with null buttons/axes, rather than fabricated native neutral values. IDs belong
to their own process; engine and observer IDs are not compared as a shared ID.

SDL itself generates recenter/release events on removal. The new mode labels
edges as SDL events with no asserted physical cause. They cannot count as the
separately instructed post-reconnect human release. No key/controller injection,
virtual device, rumble/LED/sensor setter, system audio/device/controller change,
global key capture or focus restoration is added.

The future runner requires both separate owner permissions before creating an
output directory/UI/session. It verifies source/build/helper/engine/library
identities, uses a fresh source snapshot and waits for a real Ready click.
It reuses the read-only muted-endpoint guard, unchanged supervisor/tree ownership,
PNG completion reader and PR #40 lifecycle diagnostics. The first failure is
retained and stops phase advancement; there is no window rebind or action retry.
[Issue #39](https://github.com/Rajinder798/ps4-runtime/issues/39) remains unresolved.
Unexpected endpoint changes, including an OS default-device change during a
future USB action, abort; the runner never restores settings automatically.

## Non-interactive reproduction

```powershell
cmake -S . -B build/native -DCMAKE_BUILD_TYPE=Release
cmake --build build/native --config Release
ctest --test-dir build/native -C Release --output-on-failure
python tools/build_homebrew.py --sample pad-hotplug-av --llvm-bin build/tools/llvm-mingw-20261006-ucrt-x86_64/bin --inspector build/native/ps4-runtime.exe
```

`pad-hotplug-policy` compiles the exact pure guest decision function through a
test-only guard, without SDK, SDL, controller or audio access. Its 65 checks
cover actual policy outputs and clearing held Cross. The portable evidence suite
contains 14 tests covering raw/error preservation, false reconnect, wrong IDs,
authorization, missing stages, stale timing/images, control edges and stalled
disconnected progress. Generated host data never establishes physical behavior.

The SDL helper builds against the already attested static SDL library using
`tools/build_dualsense_probe.py` and the unchanged old live fixture for engine
attestation. The future guest runner separately attests its new fixture. Setting
`PS4_HOTPLUG_OBSERVER_CLI` to that freshly built helper enables only invalid-argument
tests, all rejected before SDL initialization. Hosted host CI explicitly skips
that optional local-helper case; no independent SDL/engine rebuild is claimed.
The homebrew workflow builds and hash-checks all nine fixed fixtures, without
executing them or publishing SDK/guest binaries.

The [implementation report](../research/results/2026-10-20-pad-hotplug-av-implementation.json)
records exact local inputs/results and pending hosted checks at collection.
All 25 local host suites passed, including 65 native policy checks and all 14
Python evidence tests with the local helper argument guards enabled. The original
1,088-entry and 918-entry hardware artifact manifests rehashed without mismatch;
all eight prior local fixture binaries still match their recorded build hashes.
The new source SHA-256 is `b38f394c619cfbabba2e2066ecccd62949dcd15f2a77dfbb193e9ac16826af28`
and OELF SHA-256 is `bde543dc632bb3c39b152a459e44249c2ae8c299a0a176b660ed0f3228414535`.
No actual guest boot/import resolution, controller recovery,
Vulkan readback or audio stream is verified by these builds or generated tests.
Full G4 and existing source/relink/redistribution holds remain open. Original code
is GPL-2.0-or-later; no engine or third-party binary is committed.

## Later physical procedure — requires separate approval, not started

One session, one unplug/reconnect cycle, seven images, fixed 240-second budget.
Read-only Windows/SDL preflight must first confirm the expected sole USB device
and already-muted endpoint. If discovery is blocked, stop before asking for input.
The operator must explicitly approve both USB actions and each physical action
is prompted only when the corresponding stage is ready:

1. The human would click Ready, leave controls neutral and capture initial neutral
   with F12 after at least three seconds/20 actual guest and native samples.
2. The human would hold Cross, then capture its qualified held image with F12.
3. At the unplug prompt, the human would unplug once, then release the physically
   disconnected Cross. Capture disconnected state; no removal-generated edge is
   accepted as evidence of that human release.
4. Keep it disconnected. Capture a second distinct image at least five guest
   seconds later, requiring continuing guest observations, flips, audio-block
   progress and effective neutral input.
5. Only at the reconnect prompt would the human reconnect the same USB controller
   once, controls untouched. Require an actual new native instance, engine slot-zero
   registration and fresh connected Pad reads on the original handle within 30
   seconds. Capture qualified reconnected neutral.
6. The human would hold then release Cross, with distinct qualified images for
   each state and separately instructed native edges on the new instance.
7. The human would close the game normally. Require exit 0, no forced termination,
   verified root exit and an empty process tree. Leave USB connected and Windows muted.

Connected neutral/hold phases retain guest axes 120–136, SDL axes ±2048,
three-second/20-sample stability and maximum 350 ms gaps. Other controls,
triggers, extra presses/cycles, wrong devices, API failures, ownership loss,
endpoint changes, corrupt/missing images and deadlines fail explicitly. There
is no automatic repeated physical action. Disconnect and reconnect outcomes are
reported separately if recovery fails. Repeated cycles, close while disconnected,
multiple users/devices, Bluetooth, calibration and general game recovery remain
unverified even if that one future session succeeds. No PR or merge is authorized
by the current implementation approval.
