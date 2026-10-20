# Physical DualSense buttons and sticks

Gate: a scoped G4 increment following the [USB Cross research](dualsense-verification.md).
Use the same physical Sony DualSense over USB-C and the exact pinned research
engine/SDL build. This is human-assisted guest verification, not broad controller
compatibility, calibration, Bluetooth support or completion of G4.

## Button stage

`tests/dualsense_guest_tests.py --guided --controls buttons` reuses the original,
unchanged `live-av` binary and its existing 24-byte Pad observations and
full-pixel Vulkan oracle. The guide now names the actual requested control:
initial neutral, two Cross press/release cycles, Circle and all four D-pad
directions with neutral releases between them. All 15 images, exact button
masks, physical SDL edges and normal close/cleanup are required. The host sends
no gameplay or F12 input; the human presses laptop F12 when prompted.

A retained first attempt exposed premature consumption of newly created,
still-empty PNG files. Their original bytes later independently qualified for
the expected states, including D-pad Left, but the guide had already discarded
them. That attempt stopped after release before phase qualification and remains
failed. The test reader now waits up to five seconds for the original PNG's
IEND trailer before passing it to the unchanged complete PNG/pixel oracle.
It does not resend F12, modify an image, loosen any threshold or retry a physical
action. A host regression covers empty/partial writes completing at the same
path and the explicit incomplete-write timeout. A new run required owner consent.

## Small isolated analog extension

The old guest never recorded axes. `research/homebrew/pad_axes/main.cpp` adds a
separate opt-in Pad/VideoOut fixture, using the existing SDK, imports, Vulkan
presentation and process supervisor. It does not modify/rebuild the engine,
replace the existing live binary, add a registered launch ID or change saved
settings. It opens no AudioOut stream. Existing fixture hashes remain fixed;
the new fixture has its own reviewed `config/pad-axes.json` contract.

Each approximately 100 ms sleep plus completed flip produces one actual
`scePadReadState` observation. A 16-byte little-endian header contains magic
`PADAX1\0\0`, schema 1 and record size 32. Each 32-byte record contains:

| Offset | Guest data |
| --- | --- |
| 0 | uint32 sequence |
| 4 | uint32 button mask |
| 8 | uint64 Pad timestamp |
| 16 | uint64 completed flip argument |
| 24–27 | uint8 LX, LY, RX, RY |
| 28 | uint8 connected |
| 29–31 | three zero reserved bytes |

The guest alone writes `pad-axes.bin` and corresponding strict console records.
It receives a random palette, never expected directions, phase commands, recorded
input or host-written observations. Four framebuffer bars show the four raw
values. Binary pixels encode the exact sequence, axes, button mask and connection.
The host independently checks every pixel against the palette and original
guest record, then compares every binary record against the strict guest audit.
PNG bytes and raw values are never normalized or rewritten.

The separate native observer's opt-in `--watch-axes` mode records real SDL axis
motion events and signed raw LX/LY/RX/RY snapshots, without injecting events or
changing controller/audio settings. It uses the same existing pinned SDL static
library. This is a second observer, not instrumentation inside the engine event
loop. The engine must independently report its sole controller in guest slot 0.

## Analog acceptance fixed before hardware execution

There are 17 human-guided stages: initial center, then full left/right/up/down
for each stick, with both sticks returned to center after every direction.
No stick click, trigger or button is requested.

- Guest center: each axis 120–136 inclusive; SDL center: each axis within ±2048.
- Guest directed axis: ≤32 for left/up or ≥223 for right/down. SDL directed
  axis: ≤−28672 or ≥28672 respectively. Other axes must meet center criteria.
- Button mask zero and connected true are required independently in each domain.
- Each phase needs at least three uninterrupted seconds and at least 20 samples
  in **both** domains after its instruction; a sample gap over 350 ms breaks the
  stability interval. Each directional stage also needs a real SDL axis-motion
  event for that axis, sign and physical instance after the instruction.
- Every phase requires a distinct, ordered, exact-record Vulkan screenshot.
  The human holds the position until the guide advances after verification.
- The human closes the game after the final center image. Require exit 0,
  no forced termination, an independently empty tree and verified root exit.

These are new direction/center acceptance bounds, not changes to existing PCM,
button or image thresholds. They tolerate small stick-rest variation while
retaining raw values. They do not establish full-range linearity, precise
calibration, deadzone correctness, diagonals, simultaneous two-stick movement,
long-term drift or latency. Pinned engine deadzone/scaling remains unchanged.

## Safety, attempts and reproduction

All guest tests require read-only endpoint observation of Windows already muted,
unchanged endpoint volume and unchanged default device. Polling gaps are reported;
between-sample changes cannot be excluded. No setter, speaker test, PCM capture,
driver installation or remapper stop is used. All tests use fresh output paths;
every failed run remains failed and preserved. There is no automatic repetition
of physical actions. No disconnect/reconnect test is authorized in this increment;
an unexpected removal fails and requests contained cleanup. [Issue #37](https://github.com/Rajinder798/ps4-runtime/issues/37)
remains open, alongside the older audio/input investigation in
[issue #33](https://github.com/Rajinder798/ps4-runtime/issues/33).

Build the observer with the existing [research toolchain recipe](dualsense-verification.md#reproduction),
then build the new fixture and run its assisted test:

```powershell
python tools/build_homebrew.py --sample pad-axes --llvm-bin build/tools/llvm-mingw-20261006-ucrt-x86_64/bin --inspector build/native/ps4-runtime.exe
python tests/dualsense_axes_guest_tests.py --engine build/upstream/windows-x64-strict/shadPS4.exe --engine-report build/upstream/strict-evidence/strict-build.json --fixture build/homebrew/pad-axes/pad_axes.oelf --supervisor build/native/ps4-startup-supervisor.exe --sdl-observer build/dualsense-extended/probe-001/dualsense-sdl-probe.exe --muted-endpoint-observer build/native/ps4-endpoint-observer.exe --output build/dualsense-extended/axes-new
```

The panel waits for the human Ready click before launching any observer or guest.
The active budget is 540 seconds; normal input progress never extends it.
The existing button runner takes the same arguments with the old live fixture,
`--guided --controls buttons` and its own fresh output directory.

Local evidence and final hosted results will be recorded separately. Generated
host negative-test records/images do not establish physical hardware behavior.
The new original source is GPL-2.0-or-later. No SDK, controller identifier beyond
device family/VID/PID, engine binary or fixture binary is committed. Existing
redistribution/source/relink holds remain open.

## Actual verification and retained limitations

The completed button attempt `buttons-002` verifies all 15 planned states/images
against physical SDL events and 360 bytes of actual guest observations. Cross
reference holds are 7.1211627 and 6.4064078 seconds. Circle and D-pad change the
guest mask and sequence pixels; only Cross changes the checkerboard palette
phase. The guest exits normally with code 0, no forced termination, an empty
tree and verified root exit. All 4,132 endpoint samples remain muted/unchanged
over 129,674 ms (maximum gap 56 ms).

The completed analog attempt `axes-003` verifies all 17 stages, including all
eight stick directions, initial center and every return. All 2,360 raw guest
records (75,536 bytes including header) match strict guest output. Seventeen
independent full-pixel Vulkan readbacks match their exact raw records. Every
captured center is `[128,128,128,128]`; directed axes reach 0 or 255 except the
qualified right-stick-down capture at 254. The right-stick-right image retains
an actual orthogonal value 129; values are never forced to center. The engine
selects its sole gamepad for slot 0. Human close exits 0 without forced cleanup,
with an empty tree and verified root exit. All 8,912 endpoint samples remain
muted/unchanged over 279,378 ms (maximum gap 46 ms). No ownership failure occurs
in this completed run.

`buttons-001` remains failed despite later verification of its original PNGs.
Both `axes-001` and `axes-002` also remain failed: 11 and nine stages qualify,
respectively, before the read-only observer loses the previously bound window
identity and requests contained cleanup. Their original guest files remain
consistent: 1,987 and 1,277 records, no unresolved import, no recorded controller
button press/removal and no guest Pad failure. Forced cleanup verifies root exit
and an empty tree in each. The exact window-loss cause is **unknown**. The owner
cannot recall whether F11 or F12 was pressed; that is not proof of an operator
error, fullscreen defect or controller regression. One earlier hold also has
orthogonal SDL value 2441, outside the fixed ±2048 center criterion, explaining
why capture was still pending in that phase but not why the window identity
was subsequently lost.

Each new physical attempt required explicit owner consent. Instructions now
distinguish F12 from F11 and explain straight-stick alignment. A narrowly scoped
read-only diagnostic records the exact failed Windows query and any separately
rediscovered owned SDL window before still failing; it never rebinds, restores
focus, injects keys or bypasses ownership. That diagnostic did not trigger in the
successful attempt. The passing follow-up does not establish a fix for either
earlier window loss. Original logs, PNGs, raw records, cleanup and exact attempted
test sources remain preserved under `build/dualsense-extended/`.

All 22 local Windows host suites and all 21 existing scoped guest regressions
pass: nine N/G CLI/Shell/Settings cases, nine prior volume/shortcut cases including
the 125-second no-input launch, and three normal-close/launcher-death/requested-stop
outcomes. Those older regressions use separate keyboard/window automation;
they are not physical-input evidence. The earlier 73-outcome audio/guest campaign
is historical and was not rerun. Final-head Windows/Linux/homebrew CI is pending
at collection; completed conclusions belong in the PR without a claim of hosted
physical guest execution or a new engine rebuild.
All five hardware-attempt engine logs match the same 29 prior warning/error
patterns; no new engine warning pattern appears. Test-reader/window failures
are recorded separately. No audio repair, calibration, Bluetooth or graceful
disconnect/reconnect claim is made, and G4 remains incomplete.

Exact inputs, per-attempt source hashes, qualified observations, all failures,
local results and artifact manifests are in the
[evidence report](../research/results/2026-10-20-dualsense-controls.json). The known
window-identity uncertainty requires owner review; a successful controlled
follow-up does not close it.
