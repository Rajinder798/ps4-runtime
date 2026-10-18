# Keyboard input observed through PS4 pad services

Gate: G4 input increment, not full G4 or general controller support. A physical
controller is **not required**. The original `pad-videoout` homebrew observes
keyboard-mapped Cross press/release through actual `scePadReadState` calls in the
separate pinned shadPS4 research engine, changes its framebuffer based on the
observed button bit, then restores the initial image. Audio, physical controllers,
axes/touch/vibration, general pad conformance and commercial gameplay are unverified.

## What is checked

The new [fixture source](../research/homebrew/pad_videoout/main.cpp) initializes
pad/user services, obtains the initial user, opens its standard virtual pad and
polls connected, timestamped observations in this order:

| State | Actual required button mask | Framebuffer palette shift |
| --- | --- | --- |
| Initial neutral | `0` | 0 |
| Cross pressed | `0x4000` | 1 |
| Cross released | `0` | 0 |

The rendered buffer is selected from the **observed button bit**, not a host
command or the expected state number. The host's phase byte only acknowledges
that the current screenshot was verified; advancing that byte cannot substitute
for the required pad observation. The guest waits at each recognized state,
repeatedly presents its selected buffer, and reports readiness only after a
completed VideoOut flip. It has an eight-second input polling budget per state.

The shared bounded research harness verifies the new fixture's exact source/ELF
[contract](../config/pad-videoout.json) and the unchanged strict engine pins. It
uses the existing [Vulkan readback verifier](videoout-research.md) for all 230,400
RGBA pixels in each of three 640×360 images. The first and third must match;
the pressed image must differ. The earlier VideoOut source/binary contract is
unchanged and its original two-phase behavior remains a regression test.

After checking the initial image, the host posts N key-down to the owned engine
SDL window. After checking the pressed image, it posts N key-up. At the pinned
default mapping, N maps to Cross and B to Circle. The saved default mapping is
checked and hashed. Only the reviewed F12/N/B keys and explicit press/release are
allowed. The adapter checks the supervisor parent PID, engine executable path
and unique SDL window before each operation; input/screenshot request PIDs must
match the final supervisor root PID. It does not switch foreground applications
or inject system-wide keyboard state. These are automated window-message tests
of keyboard mapping, not manual hardware or focus/layout testing.

After all three states, the guest closes its pad, writes `/data/input-result.bin`
and tears down VideoOut/direct memory before its final PASS marker. The 48-byte
file contains three little-endian records: `uint32 buttons`, `uint8 connected`,
three reserved zero bytes, and `uint64 timestamp`. The host requires connected=1,
button masks `[0, 0x4000, 0]`, zero reserved bytes, positive strictly increasing
timestamps, and the exact file size. The host never prepares that output file.
Fresh per-run state prevents reuse of old observations or captures. Structured
guest markers alone cannot satisfy the observation-file and pixel requirements.

The guest intentionally sleeps after completion; the supervisor owns final
process-tree termination. Natural process exit, final desktop compositor pixels,
guest GNM/shader translation and performance are not established.

## Reproduce without a physical controller

Use the same Windows x86-64, Python 3.12+, verified compiler/OpenOrbis SDK,
strict engine and Vulkan prerequisites as the preceding graphics fixture.

```powershell
python tools/build_homebrew.py --sample pad-videoout --llvm-bin build/tools/llvm-mingw-20261006-ucrt-x86_64/bin --inspector build/native/ps4-runtime.exe
python tools/run_videoout_research.py --profile pad-videoout --engine build/upstream/windows-x64-strict/shadPS4.exe --engine-report build/upstream/strict-evidence/strict-build.json --fixture build/homebrew/pad-videoout/pad_videoout.oelf --supervisor build/native/ps4-startup-supervisor.exe --output build/pad/single-new
python tests/pad_guest_tests.py --engine build/upstream/windows-x64-strict/shadPS4.exe --engine-report build/upstream/strict-evidence/strict-build.json --fixture build/homebrew/pad-videoout/pad_videoout.oelf --supervisor build/native/ps4-startup-supervisor.exe --videoout-pattern build/homebrew/videoout-pattern/videoout_pattern.oelf --hello-world build/homebrew/hello-world/hello_world.oelf --service-roundtrip build/homebrew/service-roundtrip/service_roundtrip.oelf --output build/pad/acceptance-new
```

Choose new output directories. Visual Studio native helpers are under `Release/`.
The single runner defaults to its original VideoOut profile; the input profile
must be selected explicitly. `--input-case absent|wrong-button` applies only to
`pad-videoout`. Absent input must remain neutral and fail inside the guest on
timeout. Wrong-button input posts B and must be observed as Circle (`0x2000`),
never satisfy the Cross requirement, and then time out. Both retain the one
verified neutral capture while rejecting overall input/graphics success. Neither
negative case may produce the completion observation file.

The acceptance script runs two successful press/release sessions, those two
negative sessions, then actual regressions for VideoOut, hello_world and
service-roundtrip. Every run requires guest entry, zero unresolved imports and
confirmed cleanup. The [filtered local evidence](../research/results/2026-10-18-pad.json)
records observed masks/timestamps, source/input/config/image hashes and outcomes;
raw audits, logs, PNGs and observation files remain under `build/pad/acceptance-001`.
Hosted source builds and host tests are reported separately in the PR.

The existing 14 CTest suites remain. The evidence suite expands to ten portable
tests, including malformed/stale/disconnected/wrong-button observations, strict
three-state ordering, reviewed native-key validation and rejection of an input
test option on the non-input profile. The 19-test startup suite also checks the
new fixed fixture binding. Host test data is not guest-execution evidence.

## Known engine diagnostics and release holds

These runs newly exercise existing pinned upstream diagnostics:

- `scePadInit` logs `(STUBBED) called`; its implementation only sets the initialized
  flag and returns success. This test does not establish full initialization behavior.
- `sceUserServiceInitialize` logs `(dummy) called`; service initialization conformance
  is not established.
- `scePadClose` logs a warning on invocation while removing the handle mappings.

These are retained, documented limitations of the unchanged engine, not newly
introduced engine regressions or unresolved imports. Actual keyboard-driven pad
state reads and pixel changes are checked independently of those return values.
Earlier optional asset/font/module, PT_INTERP/SCE metadata and Vulkan host
format/extension diagnostics also remain. No proprietary module is supplied to
hide them. Windows 10, physical controller hotplug/disconnection and alternate
keyboard layouts/focus paths were not locally tested.

The new fixture and tools/tests are original GPL-2.0-or-later source with no new
packaged dependency or imported engine code. SDK/engine/fixture/game binaries,
proprietary assets, firmware and keys are not committed or uploaded. Hosted
homebrew builds upload only build/symbol metadata. The separate engine remains
subject to the [dependency/source/relink and runtime/resource release holds](release-audit.md).
The new fixture remains research-only, outside the two registered launch IDs;
there are no new product Settings controls. Further input coverage and guest
audio/interactive shutdown remain functional work before full G4 completion.
