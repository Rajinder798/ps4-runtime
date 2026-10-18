# Guest framebuffer output through Vulkan

Gate: G4 graphics increment, not completion of interactive homebrew. The original
`videoout-pattern` fixture exercises direct GPU-accessible memory, VideoOut buffer
registration, repeated flip submission/completion and explicit resource teardown.
The host checks actual Vulkan image readbacks, beyond guest return values or logs.
Execution uses the separate pinned shadPS4 research engine; the independent
inspector/probe does not gain PS4 loading or rendering.

## Acceptance and evidence boundary

The [guest source](../research/homebrew/videoout_pattern/main.cpp) reads four
distinct palette indices (0–7) from `/app0/palette.bin`. It allocates/maps 4 MiB
of direct memory and fills two separate 640×360 linear A8B8G8R8 sRGB buffers.
Each is an 8×8 grid of 80×45 rectangles. Palette index bits select full-intensity
red/green/blue channels, avoiding gamma-rounding ambiguity. The second buffer
shifts the palette by one rectangle. Neither framebuffer is modified while active.

The guest registers both buffers with VideoOut. For each phase, it submits flips
and polls the returned sequence argument, buffer index and completed-flip count.
Only after observing a completed flip does it emit that phase's ready marker.
It keeps flipping until the host publishes the next control byte in
`/app0/phase.bin`. After both phases it checks unregister, close, unmap and release
return values before emitting the final PASS marker and sleeping for supervisor
termination. Natural guest process exit and comprehensive service conformance
are not established.

The host requires the exact reviewed source/converted ELF hashes in
[the fixture contract](../config/videoout-pattern.json), the unchanged strict
engine/patch/header/tree and absent-FDK build checks, ordered guest entry/phase
events, zero unresolved imports, finite output/time and Job Object cleanup.
No arbitrary ELF hash, expected pixel override or proprietary module is accepted.
This fixture is deliberately separate from the two registered launch IDs and
their Settings/shortcut contract.

At each ready phase, a test-only Windows adapter identifies the supervisor's
direct engine child by parent PID and executable path, then its single SDL window.
It posts F12 key messages only to that window. It does not switch foreground
applications or inject system-wide keyboard input. This invokes the pinned
engine's existing game-only screenshot hotkey; **it does not test PS4 pad input**.
The request PID must match the final supervisor root PID in guest acceptance.

The pinned [`PrepareFrame` screenshot path](https://github.com/shadps4-emu/shadPS4/blob/e6c79a5fe0ea2f3d03fcb9c5c50cf61af063f3f5/src/video_core/renderer_vulkan/vk_presenter.cpp)
downloads the guest output Vulkan image before FSR/postprocessing/host scaling,
then saves RGBA8 PNG through its existing staging-buffer path. The new host
verifier decodes that PNG with bounded dimensions, decompression, chunk CRCs and
all five standard filters. It independently calculates and compares **all 230,400
pixels per image**, including alpha. It publishes the next phase only after a
complete match, allowing brief Windows file-sharing contention within a finite
deadline. Fresh sessions cannot reuse old screenshots. No guest-created image
or host-prepared result file counts as a Vulkan capture.

This proves CPU-generated guest framebuffers reach that Vulkan image path for
this fixture on the recorded host. It does not verify final desktop compositor
pixels, guest GNM command/shader translation, controller input, audible output,
commercial gameplay or performance. No FPS/frame-time claim is made. Full G4
still requires input/audio where exercised and broader interactive behavior.

## Build and reproduce

Use Windows x86-64, Python 3.12+, the existing verified OpenOrbis SDK/LLVM compiler,
strict research engine and Vulkan host. No engine patch is added by this work.

```powershell
python tools/build_homebrew.py --sample videoout-pattern --llvm-bin build/tools/llvm-mingw-20261006-ucrt-x86_64/bin --inspector build/native/ps4-runtime.exe
python tools/run_videoout_research.py --engine build/upstream/windows-x64-strict/shadPS4.exe --engine-report build/upstream/strict-evidence/strict-build.json --fixture build/homebrew/videoout-pattern/videoout_pattern.oelf --supervisor build/native/ps4-startup-supervisor.exe --output build/videoout/single-run
python tests/videoout_guest_tests.py --engine build/upstream/windows-x64-strict/shadPS4.exe --engine-report build/upstream/strict-evidence/strict-build.json --fixture build/homebrew/videoout-pattern/videoout_pattern.oelf --supervisor build/native/ps4-startup-supervisor.exe --hello-world build/homebrew/hello-world/hello_world.oelf --service-roundtrip build/homebrew/service-roundtrip/service_roundtrip.oelf --output build/videoout/acceptance-new
```

Use a new output directory. Visual Studio builds put native helpers in `Release/`.
The single-run result is `videoout-result.json`; complete audit, logs, Vulkan host
diagnostics, palette/control inputs and PNGs remain under that output. Capture
deadlines and the supervisor budget fail closed, retaining available postmortem
entry/import/cleanup evidence. `--palette-case missing|truncated` supplies only
negative guest input; it must not pass graphics verification.

The opt-in acceptance script runs two successes with distinct random palettes,
two real guest failures for missing/truncated input, then actual hello_world and
service-roundtrip regressions. Every case requires actual guest entry and cleanup;
negative cases require their exact guest failure line and reject graphics success.
The filtered [local result](../research/results/2026-10-18-videoout.json) records
source/input/PNG/pixel hashes and observed outcomes. Raw files remain local under
`build/videoout/acceptance-002`; hosted results are separate in the PR.

CTest `videoout-evidence-contract` has six portable host tests: the independent
oracle's boundaries/orientation, known vectors for all PNG filters, malformed and
oversized/decompression rejection, valid-but-wrong/stale/altered pixel rejection,
strict phase/failure ordering, and pre-execution prerequisite failure. Its PNGs
are generated test data, not guest rendering evidence. The startup suite also
checks the new fixed source/binary binding and supervisor ownership callback;
an ordinary child cannot be selected as a foreign engine window.

## Warnings, licensing and remaining work

Successful local runs retain existing optional asset/font/module diagnostics,
PT_INTERP/SCE metadata messages and host Vulkan extension/format warnings seen in
the earlier fixtures. Strict import counts remain zero. Negative palette runs
add the expected input failure; no proprietary library is supplied to hide it.
The initial exploratory run also logged an absent phase control file; final runs
precreate its zero byte and no longer produce that avoidable diagnostic.

The new fixture/tools/tests are original GPL-2.0-or-later source. They add no
vendored third-party code or new packaged dependency. No SDK, engine, fixture/game
binary, proprietary asset, firmware or key is committed/uploaded. The fixture
workflow builds all three applications and uploads only build/symbol evidence.
The unchanged engine's existing build evidence remains a source-build result,
distinct from these local guest runs. Dependency/source/relink and runtime/resource
review holds in the [release audit](release-audit.md) still block redistribution.

The [next input increment](pad-research.md) now verifies keyboard-mapped guest
Cross press/release driving changed/restored output. Physical controllers, broader
input and audio/interactive shutdown remain unverified. Installer
distribution remains on its separate compliance track; further settings controls
must wait for corresponding tested launch capabilities.
