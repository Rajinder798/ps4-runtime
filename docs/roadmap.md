# Roadmap

## 0. Repository setup

- [x] Create a separate repository.
- [x] Document the project goal and current limitations.
- [x] Draft architecture and development milestones.

## 1. Choose the foundation

- [x] Inventory the God of War III loader, runtime, GPU integration, and title-specific assumptions.
- [x] Compare that inventory with the general infrastructure in shadPS4.
- [x] Record a foundation direction, candidate revision, reuse boundaries and inspected licenses.
- [x] Select a reproducible synthetic test executable for initial bring-up.
- [x] Adopt GPL-2.0-or-later for the project's original code and supporting files.
- [ ] Complete the dependency/license audit before upstream integration.
- [x] Identify the locked Windows FFmpeg binary/source inputs and add a [repeatable metadata audit](release-audit.md); full release/source compliance remains open, with separate FDK linkage addressed by the follow-up below.
- [x] Replace separate FDK linkage in the patched research engine with [bounded native FFmpeg AAC](aac-replacement.md), real host decoder/adapter tests and G2 regression evidence. Full source/notice and remaining dependency review still block redistribution.
- [x] Assemble an offline-verifiable [FFmpeg source input kit](ffmpeg-source-kit.md) with all ordered source patches, complete pinned wrapper/vcpkg snapshots, notices and deterministic packaging.
- [ ] Independently rebuild the pinned FFmpeg recipe, verify tool/dependency closure and supply tested release-specific source/relink materials.

## 2. Establish a development baseline

- [x] Add a minimal build and command-line entry point for Windows x86-64.
- [x] Add executable inspection and clear format validation errors.
- [x] Establish text/JSON diagnostics and meaningful parser/CLI tests.
- [x] Add continuous integration configuration for the implemented build and tests.

Local validation and hosted CI results are recorded separately. A workflow file
alone does not establish a passing hosted build. See [development](development.md).

## 3. Bring up executable loading

- [ ] Implement or integrate segment mapping, relocations, imports, and thread-local storage.
- [x] First map the synthetic probe, check zero-fill/protections and observe its return value of 42 through a controlled call.
- [ ] Report declared SCE import modules, libraries and NIDs read-only in the original inspector (`imports`), with generated-fixture tests and a hosted cross-check against real converted OpenOrbis files. Resolution, relocation and execution stay in the research engine.
- [x] Build and CLI-smoke-test the pinned upstream Windows baseline.
- [x] Select and reproducibly build actual OpenOrbis hello_world homebrew for future startup/service tests.
- [x] Review pinned startup coupling and focused component notices; select the [G2 process boundary](decisions/0002-g2-engine-boundary.md).
- [x] Implement a [bounded upstream homebrew harness](startup-research.md) with strict unresolved-import diagnostics and tested process cleanup.
- [x] Run the selected test executable with a minimal system layer: the [strict OpenOrbis startup result](startup-research.md#validation-and-limits) records guest entry, both messages, the two-second delay and bounded cleanup in the isolated research engine.
- [x] Report missing functions explicitly rather than silently accepting them; the [first local strict attempt](startup-research.md#converted-fixture-import-review) confirms three missing libkernel exports and stops before guest entry.
- [x] Exercise an [independent second homebrew](homebrew-services.md) with guest file read/write/seek, worker create/join, independently checked random-input output, explicit negative cases and hello_world regression.
- [x] Add a [versioned local supported-homebrew launch contract](launch-contract.md) with one-time registration, repeat launches by fixture ID, session logs and structured failures; this source-based research command is a G3 prerequisite, not an installed product.
- [x] Add [local Windows homebrew shortcuts](shortcuts.md) with verified metadata and repeated real Shell-activated guest results; this remains source-based local research without an installer.
- [x] Add [validated persistent global/per-title diagnostic preferences](settings.md), effective-value inspection and reset, with real engine log-filter effects through CLI and existing shortcuts.
- [x] Add an optional Windows [Settings window](settings.md#optional-windows-settings-window) for supported diagnostic preferences, with scope inheritance/reset and real guest effects through existing shortcuts.
- [ ] Add further controls only as their runtime capabilities are supported; installer/upgrade/uninstall and engine distribution remain gated on the separate release audit.
- [x] Verify the source-based [registered AV self-test](av-self-test-launch.md) launch increment: nine real launches and 17 local suites pass. The subsequent [small-buffer audio repair](small-buffer-audio.md) passes the full earlier guest matrix, repeated 256-frame cases and three minimized-window comparisons; paired baseline diagnostics remain documented. This does not complete installed G3 or full G4.
- [x] Verify [persistent global/per-title AV volume](av-volume-settings.md) at the implemented Mute/Half/Full levels through CLI, optional Settings and existing shortcuts, with actual Windows PCM amplitude/mute checks and legacy/regression preservation. Other preferences, installer delivery and full G4 remain open.

## 4. Reach the first playable title

- [x] Verify an original [VideoOut framebuffer fixture](videoout-research.md) with completed guest flips, two challenge-derived Vulkan readbacks checked pixel-for-pixel, teardown and earlier guest regressions. This is a G4 graphics increment, not input/audio or full interactive-homebrew completion.
- [x] Verify [keyboard-mapped guest Cross press/release](pad-research.md) with actual pad-state records, changed/restored Vulkan output, absent/wrong-button negatives and all earlier guest regressions. Physical controllers, broader input and audio remain unverified.
- [x] Verify [guest AudioOut stereo PCM through SDL's disk sink](audio-research.md), with independent ordered tone/channel/silence checks, silent/swapped negatives and all earlier regressions. Hardware playback and full interactive G4 remain unverified.
- [x] Verify [owned engine window-close exit](window-shutdown.md) after pad/graphics and audio guest behavior, with zero exit, no forced cleanup and absent-close/orphan/ignored-close rejection. Natural guest exit, hardware playback and combined interactive G4 remain unverified.
- [x] Preserve [Windows host C++ stack handling](host-exception-boundary.md) before guest fault dispatch and lifecycle shutdown, with actual native fault/throw tests, three minimized AudioOut comparisons, 52 earlier guest outcomes and an independently rebuilt engine. This scoped fix does not establish arbitrary guest-fault delivery or full G4.
- [x] Verify a [combined graphics/input/PCM/close fixture](interactive-research.md) with concurrent guest audio, independently checked state changes and absent/wrong-input/silent/swapped negatives. Hardware playback and full G4 remain unverified.
- [x] Verify [continuous live Cross input and active-guest close](live-av-research.md), without host phase files, using sequence-bound Vulkan images, repeated Windows-rendered tones and normal close during active audio. External automated transport is tested; human usability, acoustic output, registered live shortcuts and full G4 remain open.
- [x] Verify [user-closed live-session lifetime](live-session.md) beyond the old two-minute cutoff, with no-input normal close, launcher-death containment and all 60 prior guest outcomes preserved.
- [x] Verify [registered live CLI/shortcuts and preferences](registered-live-launch.md), with persistent log/volume values, normal no-input close and preserved legacy/self-test contracts. A transient captured PCM overshoot remains unlocalized and documented; reliable audio and full G4 are not claimed.
- [x] Verify [muted Windows live launches](muted-live-launch.md), with independent saved application volume, read-only endpoint observation, Settings/shortcut persistence and lifecycle cleanup. Repair the reproduced status-file sharing failure; no PCM or acoustic qualification is claimed.
- [x] Verify [saved N/G Cross letter preferences](live-cross-key.md) for the fixed live fixture, with global/title persistence, optional Settings, existing shortcuts and preserved other bindings. Intermittent input interruptions remain documented; broad input reliability is not claimed.
- [x] Verify [physical USB DualSense Cross](dualsense-verification.md) with two human press/release cycles, held input, guest Pad records, five Vulkan images and normal close. An explicitly authorized unplug produces guest pad failure with containment; graceful disconnect/reconnect, other controls and Bluetooth remain unverified.
- [x] Verify [physical USB Circle/D-pad and both analog sticks](dualsense-controls.md): 15 original live-guest button states/images, plus 17 center/cardinal/return stages and 2,360 raw guest records in an isolated Pad/VideoOut fixture. Failed attempts are retained; two window-identity losses remain unlocalized. Calibration, diagonals, simultaneous sticks, Bluetooth, graceful reconnect and complete G4 remain open.
- [x] Verify one [physical USB-C Pad hotplug cycle](dualsense-hotplug.md) in an isolated AV fixture: disconnected effective neutral, continuing graphics/audio blocks, fresh same-handle recovery, restored Cross, seven exact images and normal close. Preserve every failed attempt and explicitly record muted default-endpoint changes. General reliability, original live-fixture recovery, PCM/acoustic verification and full G4 remain open.
- [x] Verify one [normal user close while USB remains disconnected](dualsense-disconnected-close.md) in the same unchanged isolated fixture: 607 raw/effective guest records, one removal/no reconnect, three exact images, 9.683422 guest seconds of disconnected graphics/audio-block progress and zero/empty process exit without forced cleanup. Preserve the failed/unmuted preflight. Ordered guest teardown, general reliability, original live-fixture recovery and complete G4 remain open.
- [x] Verify [owned-process Windows render PCM](windows-audio-research.md) through SDL WASAPI, with active render-session evidence, signal rejection and engine/helper cleanup. Acoustic output, Windows 10 and full G4 remain unverified.
- [x] Verify [combined-homebrew volume and mute](audio-volume-research.md) through SDL disk and Windows-rendered PCM, including restoration, wrong-gain rejection and earlier guest regressions. Persistent audio preferences and full G4 remain future work; hosted results are reported separately in the PR.
- [ ] Integrate the chosen Vulkan backend and required runtime services.
- [ ] Add input, audio, save storage, and an isolated title profile.
- [ ] Document reproducible gameplay results and remaining issues.

## 5. Expand across different games

- [ ] Bring up a second title with different engine and service requirements.
- [ ] Move reusable fixes into the shared runtime.
- [ ] Track compatibility by title and version with test evidence.
- [ ] Expand coverage based on missing shared features and reproducible failures.

Support for the whole PS4 library is the project direction. No completion date or
universal playability claim is established by these milestones.

## Future work — hardware-adaptive performance (planned, not a new gate)

**Dependency:** complete the authorized G4 safety/integration work and obtain reproducible interactive guest performance evidence before implementing or benchmarking adaptive tuning. Do not use this roadmap entry to expand the current G4 PR stack or unfreeze G5.

- [ ] Specify a safe read-only CPU, system-RAM, Vulkan GPU/driver and VRAM-capability inventory with graceful failure handling and no host setting changes.
- [ ] Define a typed, versioned Auto preference that selects only genuinely implemented conservative/balanced/performance controls; preserve persistent global/per-title overrides, reset and transparent effective values.
- [ ] Establish reproducible local performance baselines for supported interactive workloads, including FPS/frame-time distributions, stalls, CPU/GPU bottlenecks, RAM/VRAM budgets, shader activity, configuration and hardware/driver identities; never invent benchmark results.
- [ ] Evaluate CPU scheduling and Vulkan/shader/resource optimizations against those baselines; prove guest correctness, audio/input responsiveness, saves, normal exit and rollback/fallback behavior.
- [ ] Qualify adaptive policies on representative low-, mid- and high-capability Windows hardware, compare to fixed presets and document when automatic selection helps, regresses or must be disabled.
- [ ] Keep diagnostic data local by default and external telemetry opt-in; do not silently modify clocks, OS power settings, drivers, Windows audio endpoints or thermal controls.

**Acceptance:** the selected Auto profile and measured outcomes must be reproducible and verifiable for named supported workloads; failed or unsupported detection must select a safe documented fallback. No universal frame-rate, hardware saturation or commercial-game compatibility claim is implied.
