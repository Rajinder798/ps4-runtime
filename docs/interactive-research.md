# Combined guest graphics, input, PCM and window-close research

Gate: G4 integration increment. The original fixed `interactive-av` homebrew
exercises VideoOut/Vulkan, keyboard-mapped ScePad input and concurrent AudioOut
in one pinned shadPS4 process. Actual observed Cross state selects both the
displayed framebuffer and the audio worker's tone/silence command. The host
independently checks three images, guest pad records and emitted stereo PCM,
then requires normal engine window-close exit. This uses SDL's disk output
device; hardware playback and full G4 remain unverified.

## Behavior and acceptance

The [sixth fixture](../research/homebrew/interactive_av/main.cpp) reuses the
original project fixtures' reviewed service patterns, with no engine mocks or
imported upstream code. One guest thread presents CPU-generated framebuffers;
a real `scePthreadCreate` worker submits 2,048-frame, 48 kHz S16 stereo buffers
through AudioOut while graphics and input run. Atomic acquire/release commands
and progress counters coordinate the two guest threads. A successful join, audio
port close, pad close, observation-file write and VideoOut/memory teardown are
required before the final guest marker.

The conservative 2,048-frame buffer uses an already supported AudioOut size.
An exploratory 256-frame concurrent run completed graphics/input/close but
produced signal gaps that the unchanged PCM oracle rejected. This is a retained
limitation, not a passing small-buffer result or a demonstrated engine fix.
The standalone audio fixture keeps its original 256-frame recipe and regression.

| Observed pad state | Independently checked image | Audio worker output |
| --- | --- | --- |
| Initial connected neutral | Palette pattern 0 | Silence |
| Connected Cross pressed (`0x4000`) | Palette pattern 1 | Different left/right fundamentals |
| Connected Cross released | Palette pattern 0 restored | Silence restored |

The palette is a fresh four-color permutation from eight colors. The audio
challenge is a fresh permutation of four periods (64, 96, 128, 192 frames);
its first two values select the left/right fundamentals from 750, 500, 375 and
250 Hz. Samples are original integer square waves, peak magnitude 2,000/32,768.
Each recognized state remains active for at least 24 submitted audio blocks
(49,152 frames) and until the host acknowledges its verified image. Readiness
requires a completed video flip plus the worker's minimum submission count.
The host acknowledges only captures, and sends N down/up to the owned engine
window; neither the acknowledgement byte nor a timer substitutes for actual
connected, timestamped guest pad observations.

The exact source/ELF [contract](../config/interactive-av.json), strict engine pins,
zero unresolved imports, actual guest entry, all ordered state/completion markers
and a fresh isolated session are required. The existing pixel oracle checks all
230,400 pixels in each 640×360 image. The existing 48-byte pad-record verifier
requires neutral/Cross/released masks, connected state and increasing timestamps.
Transport PIDs and retained keyboard mapping must match the owned engine.

Only that supervisor/engine receives the process-local SDL disk hints documented
in [audio research](audio-research.md). The retained device-open diagnostic must
name the exact fresh F32LE stereo/48 kHz output file. The shared independent
Goertzel/RMS verifier requires sustained silence, the challenge-specific stereo
pair, then silence, in order. Thresholds/window lengths are unchanged from the
audio fixture; this interaction sequence permits 3–20 seconds of PCM because
input/image handshakes hold each state for variable time. The earlier audio
fixture retains its distinct two-pair sequence and original 3–12 second bound.
Neither verifier claims bit-exact/full-stream quality, AV synchronization,
dropout certification, latency or performance.

This profile requires `--shutdown window-close`. The existing
[close verifier](window-shutdown.md) requires a matching owned-window request,
zero root exit, no active job processes before cleanup and no forced termination.
All four surfaces must pass before `combined_verified` becomes true. A normal
engine exit alone cannot grant combined acceptance.

## Reproduce

Use Windows x86-64, Python 3.12+, the verified OpenOrbis/compiler inputs, strict
engine/build report, updated supervisor and Vulkan host from earlier research.
No physical controller, microphone or recording device is needed.

```powershell
python tools/build_homebrew.py --sample interactive-av --llvm-bin build/tools/llvm-mingw-20261006-ucrt-x86_64/bin --inspector build/native/ps4-runtime.exe
python tools/run_videoout_research.py --profile interactive-av --shutdown window-close --engine build/upstream/windows-x64-strict/shadPS4.exe --engine-report build/upstream/strict-evidence/strict-build.json --fixture build/homebrew/interactive-av/interactive_av.oelf --supervisor build/native/ps4-startup-supervisor.exe --output build/interactive/single-new
python tests/interactive_guest_tests.py --engine build/upstream/windows-x64-strict/shadPS4.exe --engine-report build/upstream/strict-evidence/strict-build.json --supervisor build/native/ps4-startup-supervisor.exe --fixture build/homebrew/interactive-av/interactive_av.oelf --hello-world build/homebrew/hello-world/hello_world.oelf --service-roundtrip build/homebrew/service-roundtrip/service_roundtrip.oelf --videoout-pattern build/homebrew/videoout-pattern/videoout_pattern.oelf --pad-videoout build/homebrew/pad-videoout/pad_videoout.oelf --audio-pattern build/homebrew/audio-pattern/audio_pattern.oelf --output build/interactive/acceptance-new
```

Use new output directories; Visual Studio puts native helpers in `Release/`.
The opt-in matrix checks two combined successes, actual absent/wrong-button input
failures and actual silent/swapped guest PCM failures. Invalid audio still
completes the guest, pixel/pad checks and normal close, but must fail combined
acceptance. Input failures must reach the guest's input-timeout diagnostic and
confirm forced cleanup. All five earlier fixtures are then run as regressions,
including normal close for the earlier pad and audio fixtures. The parent
environment must remain unchanged; disk hints must not leak into other sessions.

The [filtered local evidence](../research/results/2026-10-18-interactive.json)
records exact source/input/output/audit hashes, measured signal windows, checked
pixels, pad records, process reports and expected pass/fail outcomes. Raw local
data remains under `build/interactive/acceptance-003`. Aborted PCM file metadata
reads retry a Windows share lock for at most two seconds after forced cleanup;
signal checks are never relaxed. Hosted source builds and host tests are separate
results in the PR, not hosted guest execution.

## Limits and release holds

This is a bounded, acknowledged neutral/press/release scenario. Pad state is
sampled at each transition; it is not continuous low-latency input/audio control.
The renderer uses direct CPU framebuffers, not guest GNM/shader translation.
SDL disk output is not audible speaker/headphone playback or system-audio capture.
Engine WM_CLOSE/quick_exit is not natural PS4 guest exit or save durability.
Windows 10, physical controllers, manual focus/layout behavior, device selection,
codecs/AJM, saves and commercial gameplay remain unverified. No FPS or latency
measurement is inferred from submission counts or signal windows.

The fixture remains research-only outside the two registered launch IDs. No
placeholder graphics/audio Settings controls or installer are added. Existing
dummy/stub service, optional asset/module and Vulkan diagnostics remain documented;
SDL's two error-level disk-driver messages are required retained sink evidence.
New source is original GPL-2.0-or-later. No engine/SDK/fixture/audio/game binary,
firmware or key is committed/uploaded. The engine, patch, headers and dependency
pins are unchanged, and [source/relink/runtime/resource release holds](release-audit.md)
continue to block engine redistribution. Hardware playback is the next audio
boundary before claiming the complete interactive G4 experience.
