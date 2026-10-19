# Live keyboard, Vulkan and Windows audio research

Gate: G4 continuous interaction and active-guest shutdown increment. The seventh
original fixed fixture, `live-av`, repeatedly reads the guest pad and updates
both a Vulkan framebuffer and a concurrent AudioOut worker. There is no host
phase/advance file or finite neutral/press/release script in this guest. The
existing six fixtures, engine patch and inspector/probe restrictions are unchanged.

## Use and acceptance

This is a bounded source-based research command, separate from the registered
AV self-test and its shortcuts. Use the pinned strict engine and trusted helpers,
Python 3.12+, Vulkan and an active default Windows render endpoint. Process
loopback requires Windows build 20348+; ordinary Windows 10 build 19045 is not
supported by this capture path. The local test host is Windows 11 build 26220.

```powershell
python tools/build_homebrew.py --sample live-av --llvm-bin build/tools/llvm-mingw-20261006-ucrt-x86_64/bin --inspector build/native/ps4-runtime.exe
python tools/run_live_av.py --engine build/upstream/windows-x64-strict/shadPS4.exe --engine-report build/upstream/strict-evidence/strict-build.json --fixture build/homebrew/live-av/live_av.oelf --supervisor build/native/ps4-startup-supervisor.exe --capture-helper build/native/ps4-process-audio-capture.exe --output build/live-av/manual-new
```

Focus the SDL window, hold **N** (guest Cross) for about a second and release it
for about a second. Repeat twice, then close the window within the 30-second
research budget. N changes the checkerboard and enables the low-amplitude stereo
tone; releasing it restores the neutral image and silence. A physical controller
is not required. The default mapping is created in this isolated engine session.
The tool does not change the system's audio endpoint mute or volume, so successful
Windows-rendered PCM verification does not imply that speakers are audible.

The runner sends diagnostic F12 readback requests but sends no gameplay keys or
window-close request. Only external keyboard input changes the guest state; the
user closes the window. A deadline is a failed observation with bounded cleanup,
not a successful automatic close. This command is a research qualification probe,
not an installed game launcher or an unbounded manual-play session.

Passing requires all of:

- Exact engine/report/fixture/source hashes, real guest entry and zero unresolved imports.
- Two actual guest Cross press/release cycles, with strictly increasing pad timestamps,
  completed flip counters and an advancing guest audio-block count. Guest-written
  24-byte records must exactly match the strict output; readiness is never guest completion.
- Independently checked 640×360 images for each Cross transition. Eight sequence
  pixels bind each image to its exact observation, preventing an earlier neutral
  or pressed frame from satisfying a later cycle. Every pixel is checked.
- Owned-process Windows-rendered PCM containing sustained silence/tone/silence/
  tone/silence, independently calculated channel frequencies and the original
  ±2000 S16 amplitude. Closing while pressed additionally requires a final tone.
- Normal zero engine exit with an independently empty process tree and clean
  capture-helper exit, while both guest loops remain active. No guest resource
  teardown or natural guest exit is claimed.

An early close or insufficient/brief input fails qualification even if the window
closed normally. Rapid input can skip a readback; unqualified images never grant
success. Capture is restricted to the owned engine tree, not microphone or other
applications. Logs, guest records, images and raw PCM stay in the fresh local
output directory; nothing is uploaded by this runner. The host output limit and
8–30 second budget remain enforced.

## Reproduction and validation

```powershell
python tests/live_av_guest_tests.py --engine build/upstream/windows-x64-strict/shadPS4.exe --engine-report build/upstream/strict-evidence/strict-build.json --fixture build/homebrew/live-av/live_av.oelf --supervisor build/native/ps4-startup-supervisor.exe --capture-helper build/native/ps4-process-audio-capture.exe --output build/live-av/acceptance-new
```

Only this test driver injects owned-window gameplay keys and close requests. The
live runner runs in a separate process. The eight cases cover normal close after
two cycles, close during an additional held tone, silent/swapped audio rejection,
wrong-button rejection, no-input close, deadline cleanup and missing challenge.
Automated external transport is not evidence of a human operating the keyboard.
The portable suite tests strict ordering/faults, file corruption, missing cycles,
stale/wrong PNG identity, repeated-tone requirements and CLI budget rejection.
Generated host signals/images are never substituted for guest evidence.

All eight actual guest expected outcomes pass against the settled native helpers
in `build/live-av/acceptance-003`. Both positive cases verify repeated states and
normal active-guest close; all six negatives fail for their specific expected
reason with process-tree cleanup. The positive logs add no warning/error patterns.
The missing palette negative produces the expected file-open diagnostic.

All 18 local Windows host suites pass. The corrected source's hosted
[PR checks](https://github.com/Rajinder798/ps4-runtime/actions/runs/39193980381)
and [push checks](https://github.com/Rajinder798/ps4-runtime/actions/runs/39193971631)
also pass all 18 suites on Windows/Linux. The
[independent seven-fixture build](https://github.com/Rajinder798/ps4-runtime/actions/runs/39193971563)
reproduces every locked source/converted-ELF hash, including unchanged earlier
fixtures. Its source compilation is warning-free; each inspector build has the
same existing Windows multi-config unused `CMAKE_BUILD_TYPE` warning. Reports,
symbol inventories and completed logs were downloaded and reviewed. These
hosted builds do not execute any guest.

The canonical live source SHA-256 is
`f94e473c090e04fb679f79705ea758ef34fedbd9675171198a699abf44fe672d`;
converted ELF SHA-256 is
`a6a97f38dcd79d47cfb2aa8de3d88291aa9e4cb1160668d2d6c08311e791e608`.
The first source pin accidentally described CRLF working bytes; CI correctly
rejected the canonical LF source. The corrected pin reproduces the identical
guest binary. An earlier matrix was interrupted by a result-field rename, and
one native relink was blocked while its capture helper was in use. Both attempts
are retained separately. The helper rebuild completed before the final matrix;
the final helper hashes are preserved with that evidence.

The complete final-helper matrix passes **60 expected guest outcomes**: eight
live cases plus all 52 earlier Windows/disk audio, volume, registered CLI/Shell
and legacy Settings/UI cases. The full 18 local Windows suites pass again after
the CLI output-directory guard, and its
[PR](https://github.com/Rajinder798/ps4-runtime/actions/runs/39194415058) and
[push](https://github.com/Rajinder798/ps4-runtime/actions/runs/39194412685)
Windows/Linux workflows pass with no new warnings. Existing output directories
and their contents are rejected without modification.

The [filtered result](../research/results/2026-10-19-live-av.json) preserves the
eight live traces and expected failures, source/binary/helper identifiers,
independent fixture build identities, earlier regression summaries and raw
artifact hashes. Post-run checks reverified 46 audit files, 27 qualified PCM
files and 132 qualified images, with no new positive/regression engine warning
patterns. Raw outputs are under `build/live-av/{acceptance-003,
audio-regressions-001,volume-settings-001,registered-regressions-001,
legacy-settings-001}`; hosted reports/logs are under `build/live-av/ci-homebrew*`
and `build/live-av/ci-code-*`.

The existing strict engine inputs and local executable match the independently
reviewed [engine build 39172527522](https://github.com/Rajinder798/ps4-runtime/actions/runs/39172527522).
The subsequent [merged-main build 39192608940](https://github.com/Rajinder798/ps4-runtime/actions/runs/39192608940)
also passes and its downloaded artifacts/full logs are reviewed. It matches the
same source/patch/tree/header contract and unchanged 54-submodule inventory;
native exception/AAC/linkage checks pass. Its 73 unique compiler warning messages
and eight CMake warning blocks match the prior reviewed build, with no new
material warning. This task changes no engine inputs; hosted build evidence is
distinct from the local guest runs above. Final evidence-commit host checks are
reported in the PR. Owner review and explicit authorization remain required for merge.

## Scope and licensing

This extends the proven VideoOut/Pad/AudioOut and file services; it establishes no
new arbitrary-game loader or standalone engine. Global/title preferences and
shortcut registration for this live fixture are a subsequent integration step,
after this execution behavior is proven. Human usability, acoustic output,
physical controllers, natural guest exit, Windows 10 hardware, commercial games
and complete G4 remain unverified. These are CPU framebuffers presented through
Vulkan; GNM/shader translation is not exercised. An endpoint mute is retained as found.

New source is GPL-2.0-or-later and reuses the project's original fixture logic.
No engine, SDK, fixture, game, firmware, key or audio binary is committed/uploaded.
The pinned OpenOrbis source inputs and reviewed engine boundary are unchanged.
All [source/relink/dependency/resource holds](release-audit.md) continue to block
engine redistribution. No installer, new frontend or placeholder setting is added.
