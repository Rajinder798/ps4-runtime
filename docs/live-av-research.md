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

Local build and initial actual guest observations pass. The complete consistent
eight-case matrix, all earlier guest regressions, 18 Windows/Linux host suites and
independent seven-fixture hosted builds remain pending. Final results and warning
review will be recorded before requesting merge review. The merged-main strict
engine rebuild is also checked separately; this task changes no engine inputs.

## Scope and licensing

This extends the proven VideoOut/Pad/AudioOut and file services; it establishes no
new arbitrary-game loader or standalone engine. Global/title preferences and
shortcut registration for this live fixture are a subsequent integration step,
after this execution behavior is proven. Human usability, acoustic output,
physical controllers, natural guest exit, Windows 10 hardware, commercial games
and complete G4 remain unverified. An endpoint mute is retained as found.

New source is GPL-2.0-or-later and reuses the project's original fixture logic.
No engine, SDK, fixture, game, firmware, key or audio binary is committed/uploaded.
The pinned OpenOrbis source inputs and reviewed engine boundary are unchanged.
All [source/relink/dependency/resource holds](release-audit.md) continue to block
engine redistribution. No installer, new frontend or placeholder setting is added.
