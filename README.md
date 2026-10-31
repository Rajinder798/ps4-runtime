# PS4 Runtime

**An experimental PS4 compatibility runtime for x86-64 PCs, with Windows as the first target.** The long-term user experience is: install the runtime once, register a **supported** game, and launch it from a normal desktop or Start-menu shortcut. The game should have its own window, input, audio, saves, diagnostics, and predictable shutdown, without a traditional emulator library UI or repeated setup.

**Project status: research and homebrew validation, not a playable-game release.** No commercial PS4 game has been established as playable by this project. No PS5 support is implemented. Compatibility with every PlayStation game is an aspiration, not a promise.

This README is a project overview and **proposed execution plan**, not a record that uncompleted milestones have shipped. For authoritative acceptance evidence and individual tasks, use the [roadmap](docs/roadmap.md), [architecture](docs/architecture.md), and [product vision and acceptance gates](docs/product-vision.md).

## What "native" means here

PS4 uses x86-64 CPU instructions, so compatible guest instructions may execute directly on a suitable x86-64 host CPU. This avoids the need to interpret every CPU instruction, **but it does not turn a PS4 executable into a Windows program**. The runtime still needs to load console binaries, honor the guest ABI and memory behavior, implement imported system services, translate GPU commands/shaders, and manage audio, input, storage, faults, and lifecycle.

The intended architecture is a **compatibility layer with native guest CPU execution where possible**, not a source-code port of each game. System-service and graphics compatibility necessarily use techniques also found in emulators; "native" must not be read as "zero emulation."

## Current verified state

| Area | Verified today | Not yet demonstrated |
| --- | --- | --- |
| Original C++ tool | ELF inspection, read-only inventories of declared SCE import modules/libraries/NIDs, relocations and startup metadata (TLS template, process parameters), and a tightly restricted synthetic mapped-code probe returning `42`, with segment, zero-fill, and protection checks | Arbitrary PS4 ELF/SELF execution, import resolution, applying relocations, TLS allocation, or commercial games |
| PS4 guest startup (separate research engine) | Pinned shadPS4 research build runs selected OpenOrbis `hello_world` with observed guest entry, strict imports, messages, delay, and bounded cleanup | An integrated distributable PS4 Runtime engine |
| Kernel-like services | Independent homebrew roundtrip for file read/write/seek and thread create/join, with checked data | Broad PS4 library/API compatibility |
| Video | Original CPU-framebuffer `VideoOut` fixtures reach the research engine's Vulkan presentation path with pixel-checked captures | PS4 GNM command/shader translation validated for an actual game |
| Input | Keyboard-mapped guest Cross reads; physical USB DualSense Cross, Circle, D-pad and selected stick tests; one isolated USB disconnect/reconnect cycle | General controller reliability, Bluetooth, broad mappings, and robust hotplug in the normal live profile |
| Audio | Guest stereo PCM tested through SDL disk output and independently checked Windows WASAPI render-path capture | Verified acoustic speaker/headphone output in general use; every audio path/game |
| Combined live research | One fixed original homebrew runs continuous input-driven graphics with guest audio, and normal user-initiated window close has been observed | Fully accepted interactive G4 homebrew or commercial-game playability |
| Windows launch experience | Source-based fixture registration, repeat launches, local shortcuts, structured session logs, optional Settings window, and tested log/Mute-Half-Full preferences | Installable, redistributable, Python-free one-click supported-game product |
| Release compliance | Narrow pinned dependency audits, patched research AAC replacement, and an offline-verifiable FFmpeg source input kit | Completed Windows dependency/license/source-material audit and approval to redistribute the engine |
| PS5 | No PS5-specific runtime work is verified | PS5 loading, services, graphics, homebrew, or games |

**Important separation:** The standalone `ps4-runtime.exe` inspector/probe and the pinned, separately built shadPS4 research engine are **not the same integrated runtime**. Successful research-engine fixtures must not be described as general executable support in the standalone tool.

### Research results and known limitations

- [Startup checks](docs/startup-research.md) and [service roundtrip](docs/homebrew-services.md) validate two small guest programs; they are not game compatibility evidence.
- [VideoOut](docs/videoout-research.md), [Pad/VideoOut](docs/pad-research.md), [AudioOut](docs/audio-research.md), and [combined AV](docs/interactive-research.md) verify bounded behavior under independent checks.
- [Live AV](docs/live-av-research.md), [ordinary session lifetime](docs/live-session.md), [Windows render-path audio](docs/windows-audio-research.md), and [registered live launch](docs/registered-live-launch.md) demonstrate useful components but do not establish a complete interactive product.
- [Physical DualSense evidence](docs/dualsense-verification.md), [additional controls](docs/dualsense-controls.md), [isolated hotplug](docs/dualsense-hotplug.md), and [close while disconnected](docs/dualsense-disconnected-close.md) cover specific USB cases, **not** broad controller reliability.
- Known research issues include an unexplained transient Windows PCM capture overshoot, intermittent input interruptions, and previously observed window-identity losses. Keep their failing artifacts and reproduce them before claiming the corresponding reliability gates are closed.
- Natural guest teardown, ordinary manual playability, general PS4 shader translation, commercial title startup, installed distribution, and PS5 support remain separate open questions.

## Desired product boundaries

The smallest credible end-user release is a **Windows x86-64 runtime that reliably launches one explicitly supported, legally obtained title** with a verified installation and exit path. It is not "supports all PS4 games."

- **Runtime core:** guest module loader and process setup, symbol resolution, memory/thread services, fault isolation, graphics translation, audio/input, saves, and version-aware diagnostics.
- **Host adapters:** Windows process management, Vulkan, controller and audio integration, filesystem paths, and settings storage; interfaces should also allow other host systems later without rewriting the guest runtime.
- **Launcher:** stable, headless per-title launch contract. A desktop shortcut invokes the runtime; Windows Explorer does not load or inspect untrusted guest code in-process.
- **Optional Settings:** typed, versioned global and per-title preferences with conservative defaults. A visible setting must have a tested effect or be clearly unavailable.
- **Compatibility evidence:** report the exact title ID, game version, runtime revision, OS, CPU, GPU/driver, required workarounds, and test outcome; keep patches isolated to versioned title profiles.

## Feasible development plan

This order prioritizes **one small, independently demonstrated capability per change**. Some work can run in parallel, but a later acceptance gate does not pass merely because prerequisite scaffolding exists. The [detailed roadmap](docs/roadmap.md) remains the task-level record.

| Gate | Outcome required | Current assessment |
| --- | --- | --- |
| **G0 – bounded native probe** | Inspect a known synthetic executable; check safe mapping and observed return | **Demonstrated** in the original tool |
| **G1 – reproducible research baseline** | Build/identify pinned engine and legal homebrew inputs with hashes and regression tests | **Research baseline demonstrated** |
| **G2 – actual PS4 homebrew startup** | Guest entry, real imported service behavior, independent observations, and bounded cleanup | **Demonstrated for selected fixtures** in the separate engine |
| **G3 – install-once Windows launch** | Install/upgrade/uninstall, register a supported title, double-click launch with no Python/source checkout and tested persistent settings | **Partial:** source launcher, shortcuts, Settings, and preferences exist; installer/distribution is blocked |
| **G4 – accepted interactive PS4 homebrew** | Reproducible human-controlled rendering, input, audible output where claimed, stable guest/runtime lifecycle, and regression evidence | **Partial:** important isolated and combined research tests pass; full gate remains open |
| **G5 – first supported commercial PS4 title** | Reproducible in-game interaction plus tested graphics, input, sound, saves, and normal restart/exit on a specified version | **Not demonstrated** |
| **G6 – generalize across titles** | Second architecturally different title; move common fixes into the platform layer and publish versioned compatibility results | **Not demonstrated** |

### Track A — consolidate the existing PS4 research path (next priority)

**Goal:** convert isolated fixture successes into a repeatable, independently observable live homebrew result without weakening the existing tests.

1. Pin the exact Windows engine, toolchain, dependencies, fixtures and run configuration; keep an executable baseline manifest and reproducible acceptance commands.
2. Reproduce and localize intermittent pad/input interruptions, window-identity failures and transient PCM overshoot. Apply the smallest fix to the responsible layer; retain failed and passing comparisons.
3. Exercise a manually controlled live homebrew in ordinary launch mode: multiple input transitions, sustained rendering, guest audio, normal user close, and bounded orphan-free failure cleanup.
4. Independently compare guest-written input traces, Vulkan frame captures, Windows-rendered PCM, timing/lifetime logs, and process termination. Keep a negative test for each claim.
5. Declare the relevant part of **G4** complete only when its exact requirements are met. A CPU-generated framebuffer displayed through Vulkan **does not** prove PS4 GNM/shader support.

**Exit evidence:** a documented Windows hardware/software matrix, successful clean repeated runs, reproducible input/audio/frame observations, no unexplained qualifying failure, and explicit statements about untested hardware or output paths.

### Track B — build the missing game-facing PS4 compatibility features

**Goal:** progress from controlled homebrew APIs toward the actual module and graphics behavior a game needs.

1. Extend or integrate general guest loading: executable validation, segment mapping, relocations, import/library resolution, thread-local storage, ABI-safe guest entry and robust faults. Do not broaden the inspector's synthetic probe into an arbitrary binary runner without these protections.
2. Record imports and service calls needed by selected permitted tests. Implement reusable memory, threads/synchronization, timers, files, save paths, process and device services incrementally, with negative tests for missing or unsupported functions.
3. Establish a bounded **real PS4 GPU-command and shader workload**. Translate the exercised GNM commands, resource layouts, barriers, shader semantics and synchronization into Vulkan; independently validate rendered output. Keep this separate from the already verified CPU-framebuffer VideoOut path.
4. Test shader correctness, cache invalidation, GPU/CPU synchronization, memory lifetime and device-loss behavior before performance tuning. Fix general problems in shared code; reserve per-title patches for documented exceptions.
5. Select the first candidate **only after** legally accessible executable/data inputs, basic import coverage and a GPU path are available. Choose for small, observable dependencies—not fame, graphics quality, or presumed ease.

**Exit evidence:** a repeatable title-specific startup-to-render path with crash/import/shader diagnostics that distinguish unsupported platform behavior from a bad title profile. Do not call a title playable at this stage.

### Track C — make an installable Windows product (parallel after legal gates)

**Goal:** fulfill the project's one-click experience without silently depending on local research checkouts.

1. Finish the [engine redistribution and dependency audit](docs/release-audit.md): independently reproduce the pinned FFmpeg build, verify linked components, required notices/source and static-link obligations, review remaining libraries/resources and runtime packaging. The narrow AAC fix and source-input kit are **not** blanket redistribution approval.
2. Package only verified, legally redistributable components. Add versioned installer/upgrade/uninstall behavior and clean recovery from interrupted installation.
3. Register supported, explicit title profiles or safe shortcut targets. Test fresh installs, moved/missing game files, bad input, unsupported versions, broken prerequisites and user cancellation.
4. Retain a headless launch path. Persist validated default/global/per-title settings, permit reset, and check visible setting effects against real output—not just configuration text.
5. Qualify clean exit, per-title saves, crash-log privacy and local diagnostic export. Do not opt users into telemetry or associate unknown executable types system-wide by default.

**Exit evidence:** clean Windows test-machine installation followed by an actual supported fixture launch from a desktop shortcut **without Python, a source checkout, or manual per-run commands**, plus successful upgrade and uninstall. This closes **G3** only for tested supported inputs, not commercial playability.

### Track D — qualify the first commercial title (G5)

This track starts only after a permitted title candidate, meaningful game-facing loading/services, and an observable graphics path exist. It is **not** a short follow-up to the synthetic `42` probe.

1. Establish exact title/build hashes, legal input provenance, hardware/driver baseline and a protected, reproducible launch profile.
2. Report progress honestly as **load → guest entry → graphics initialization → menu → in-game → reproducible playability**; each is a different outcome.
3. Verify controller input, actual sound, correct rendering, save/load persistence, repeat launches, reasonable resource usage, and clean close. Capture failures with limited, privacy-aware logs and deterministic repro cases.
4. Apply title-specific fixes only after determining whether the defect belongs in common loader, services, GPU, audio/input or timing code. Regression-test existing homebrew fixtures before accepting any workaround.
5. Publish a version-specific compatibility report listing tested scenes and duration, hardware, defects and what has **not** been exercised. Never extrapolate from a boot screen to full-game support.

**Exit evidence:** a supported version demonstrably enters and sustains interactive gameplay across repeated clean runs, with working saves and a documented reliability envelope. There is no promise of a particular game or delivery date.

### Track E — expand to a second title and beyond (G6)

Choose a second title with **different** system-service or rendering requirements. Use its failures to expose shared missing behavior rather than accumulate unreviewed per-game patches. Build a regression corpus of verified homebrew plus permitted title cases, measure compatibility by version, and improve Windows UX only as actual capabilities exist.

A second title must not require copying an entire game-specific runtime. A scalable implementation has a small, auditable common core and contained versioned exceptions.

### Dependencies and stop/go decisions

- **G3 and G4 can progress in parallel:** packaging/release auditing is separate from live guest research, but an installer cannot ship the unaudited engine.
- **GPU proof blocks meaningful G5 rendering claims:** a Vulkan-presented CPU framebuffer alone is insufficient for real PS4 GPU workloads.
- **Stable input/audio/lifecycle blocks playability claims:** a single captured frame or scripted fixture does not demonstrate a playable title.
- **Only tested compatibility is advertised:** stop a milestone and document the missing API, crash or legal blocker rather than substituting a mock or weakening the acceptance criteria.
- **Avoid speculative schedules:** estimate only small, reviewed tasks with an actual fixture and exit test. Project-wide completion dates or universal compatibility percentages are not justified by current evidence.

## Optional future feasibility study: PS5 (not on the committed PS4 roadmap)

A PS5 compatibility backend is **technically plausible as research**, because compatible x86-64 guest instructions could execute directly on an appropriate PC CPU. It is **not** equivalent to "run PS5 executables unchanged on Windows." PS5-specific loading, guest OS interfaces, memory semantics and an AGC-to-host-GPU translation layer would require independent research and implementation. No PS5 functionality or game compatibility is claimed here.

**Decision rule:** keep PS4 work the primary focus. Revisit a PS5 feasibility branch only after a stable shared host interface and meaningful PS4 G4/G5 evidence, unless separate maintainers can do isolated exploratory work without delaying those gates.

If a PS5 spike is undertaken, its bounded plan is:

1. **Evidence/legal gate:** identify lawfully accessible, authorized PS5-format test inputs and document their provenance. No keys, firmware, proprietary SDK, commercial binaries or circumvention tooling belong in this repo.
2. **Architecture study:** inventory PS5 executable/module formats, imports, TLS/ABI, system calls, process/thread behavior, memory requirements and GPU interfaces. Mark unknowns explicitly; do not assume PS4 services or GNM translation can be reused unchanged.
3. **Host-only proof:** first validate candidate x86-64 host execution and stable shared host adapters with original synthetic tests, without labeling them PS5 guest execution.
4. **Guest startup proof:** only when lawful test inputs and required format knowledge exist, build a separate PS5 loader/service backend and demonstrate actual guest entry plus one independently observed service roundtrip.
5. **Graphics proof:** use a permitted minimal graphics workload to evaluate AGC/shader/resource/synchronization translation into Vulkan, with independent image comparisons and performance measurements.
6. **Go/no-go:** proceed only if guest entry, service behavior, observable graphics, reproducible tests, licensing and maintenance cost all justify a new platform track. Otherwise document feasibility findings and stop.

**Reuse where verified:** Windows launching, process isolation, logging, settings, audio/input host adapters and some memory primitives. **Do not assume reuse:** PS4 guest loaders, symbol sets, system services, shader formats or GPU command translation. Any future PS5 plan would need its **own** acceptance gates and compatibility database; it must not be counted as PS4 progress.

## How to build and test the original probe

The following commands exercise the **standalone inspector/probe**, not the separately built shadPS4 research fixtures:

```powershell
cmake -S . -B build/native -DCMAKE_BUILD_TYPE=Release
cmake --build build/native --config Release
ctest --test-dir build/native -C Release --output-on-failure
python tools/make_probe.py build/probe.elf
.\build\native\ps4-runtime.exe inspect build/probe.elf --json
.\build\native\ps4-runtime.exe probe build/probe.elf --json
```

Visual Studio builds place the executable under `build/native/Release/`; adjust the path accordingly. The `probe` command verifies only a known generated fixture, not arbitrary PS4 code. Consult [development instructions](docs/development.md) and [pinned research baseline](docs/upstream-baseline.md) for separate development and research-engine prerequisites.

## Engineering rules for changes

- Start with one failing, reproducible case and a stated expected observation. Preserve the last passing baseline.
- A passing compiler, unit test, or synthetic probe is **not** proof of guest execution; a boot is **not** proof of playability.
- Keep the original inspector, external research engine, Windows launcher and optional UI boundaries explicit. Integrate upstream components only after technical and license review.
- Favor small patches, independent output oracles, positive/negative tests, host/guest distinction, exact build hashes, and retained failure artifacts.
- Record every compatibility result with title ID/version, host/driver, engine revision, reproduction steps, achieved stage and unsupported functionality.
- Do not commit games, firmware, console keys, proprietary SDK files, or copyrighted assets. Use legally obtained inputs and respect third-party licenses.
- Treat guest input as untrusted: validate paths/modules and imports, isolate faults where possible, provide clean process-tree shutdown and limit log collection. A hash or launcher wrapper does not constitute a security sandbox.

## Project documentation

| Topic | Details |
| --- | --- |
| User experience and gates | [Product vision](docs/product-vision.md), [roadmap](docs/roadmap.md) |
| Design and foundation | [Architecture](docs/architecture.md), [foundation decision](docs/decisions/0001-foundation.md), [research-engine boundary](docs/decisions/0002-g2-engine-boundary.md) |
| Startup and host services | [Startup research](docs/startup-research.md), [service roundtrip](docs/homebrew-services.md) |
| Graphics/input/audio evidence | [VideoOut](docs/videoout-research.md), [Pad](docs/pad-research.md), [AudioOut](docs/audio-research.md), [combined AV](docs/interactive-research.md), [live AV](docs/live-av-research.md), [render-path audio](docs/windows-audio-research.md) |
| Controller evidence | [DualSense USB](docs/dualsense-verification.md), [buttons/sticks](docs/dualsense-controls.md), [hotplug](docs/dualsense-hotplug.md), [disconnected close](docs/dualsense-disconnected-close.md) |
| Launcher and Windows UI | [Launch contract](docs/launch-contract.md), [shortcuts](docs/shortcuts.md), [settings](docs/settings.md), [AV self-test](docs/av-self-test-launch.md), [registered live launch](docs/registered-live-launch.md), [volume settings](docs/av-volume-settings.md) |
| Release and licensing | [Release audit](docs/release-audit.md), [FFmpeg source input kit](docs/ffmpeg-source-kit.md), [AAC replacement](docs/aac-replacement.md), [third-party boundaries](docs/licensing.md) |
| Build and development | [Development](docs/development.md), [pinned upstream baseline](docs/upstream-baseline.md) |

## Origins and upstream research

This project grew from studying the game-specific [God of War III PC runtime](https://github.com/FelipePrado0/gow3_pc). The [shadPS4 project](https://github.com/shadps4-emu/shadPS4) is a selected research foundation for platform and Vulkan work, **not** a claim that its engine is integrated into the standalone inspector or cleared for bundled release. See the [foundation decision](docs/decisions/0001-foundation.md) and [release audit](docs/release-audit.md) for exact boundaries.

## License

Copyright (C) 2026 Rajinder Singh.

PS4 Runtime's original code, build scripts, configuration and documentation are
free software: you can redistribute and/or modify them under the GNU General
Public License as published by the Free Software Foundation, either version 2
of the License, or (at your option) any later version (`GPL-2.0-or-later`).

This project is distributed without any warranty, including the implied
warranties of merchantability or fitness for a particular purpose. See
[LICENSE](LICENSE) for the full terms and [licensing and third-party boundaries](docs/licensing.md)
for contribution and distribution guidance. Third-party material retains its
own copyright notices and license terms.
