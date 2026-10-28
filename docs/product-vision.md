# Product vision — PS4 Runtime for Windows

Status: target design, not a claim of current compatibility.

## The owner's non-negotiable end-user goal

Install PS4 Runtime **once** on Windows 10/11 x86-64. Thereafter, double-click an installed, **supported**, lawfully obtained PS4 game's desktop/Start-menu shortcut (or a specifically registered supported file type) and have the game launch directly, without opening a separate emulator library/interface or configuring the runtime manually on each launch. The game should have its own window/fullscreen, sound, input, saves, understandable errors and clean exit. Setup prompts are acceptable for missing prerequisites, especially at first launch.

Broad coverage of the PS4 library is the long-term ambition, never a present 100% compatibility guarantee. Windows does not execute PS4 ELF/SELF as PE files natively; double-click integration invokes the compatibility runtime.

## Long-term north star: a Windows runtime for PS4 first, PS5 later

The owner's intended product is **one Windows-first compatibility platform** that lets a user launch **supported, lawfully obtained** PlayStation games as ordinary desktop applications: **PS4 is the active engineering and release priority; PS5 is a possible later backend, not current functionality or a committed delivery promise**. The current project name, *PS4 Runtime*, reflects the first target platform.

**End-user experience:** install the runtime once; supply/register a supported local title; use its own desktop/Start-menu shortcut or a deliberately registered supported file type; double-click to launch directly into the game's own window or fullscreen mode. No mandatory emulator library window, repeated command-line commands, development checkout, Python setup, or per-run configuration. Optional Settings remains available for persistent global/per-title preferences. A launcher shortcut may invoke an installed runtime behind the scenes; the game does **not** have to become a standalone Windows PE executable.

**Engineering interpretation:** the project is a compatibility runtime, **not** a promise to decompile every game's complete source code, turn arbitrary console files into `.exe` files, or make untested games run automatically. Execute compatible x86-64 guest CPU instructions directly where technically sound; handle console-specific loading, ABI, imports, memory and system services, graphics/shader translation, audio, input and lifecycle in the runtime. Targeted reverse engineering and version-scoped workarounds may be necessary, but prefer fixes reusable across titles.

**Platform boundary:** share only validated host-side Windows infrastructure (launcher, settings, controller/audio adapters, filesystem and saves, logging, diagnostics, windowing and suitable Vulkan infrastructure). Keep the **PS4 guest backend** (PS4 executable formats, libraries, ABI and GNM-related graphics) distinct from a future **PS5 guest backend** (its own executable formats, services, ABI and AGC-related graphics). Similar x86-64 CPUs do **not** mean identical console APIs or shaders, and neither PS4 compatibility nor host-side smoke tests establish PS5 compatibility.

**Priority and evidence:** finish reproducible interactive PS4 homebrew, meaningful PS4 game-facing loading/graphics and one **demonstrably playable** supported PS4 commercial title before treating PS5 compatibility as an active product milestone, unless the owner explicitly authorizes a separate, isolated feasibility spike. Keep PS5 work from breaking, blocking or being counted toward PS4 gates. For each platform, report progression separately: inspect → load → guest entry → graphics/input/audio → menus → in-game interaction → repeatable playability, with title/build, hardware and observed tests. No PS5 guest entry, AGC translation, homebrew or commercial gameplay has been demonstrated in this project.

**Distribution and trust:** do not bundle games, firmware, proprietary SDKs, console keys or DRM-bypass material. The user supplies legally obtained, accessible game inputs; software may reject encrypted or unsupported inputs. Do not claim a universal converter, universal game support, zero emulation, or a shipping installer until evidence and legal/redistribution reviews support it.

## User-controlled settings (first-class product requirement)

The user may open **PS4 Runtime Settings** at any time, choose their preferences, and save them persistently. First launch must offer sensible auto-detected defaults; a successful double-click on an already configured and supported title must never require reopening Settings. Users may override defaults globally **and per title**, reset overrides to defaults, and inspect effective settings and compatibility warnings.

Settings planned for implementation as the related subsystems become functional:
- Graphics: renderer/backend when supported, resolution/scaling, fullscreen/windowed, V-Sync, frame pacing/caps, shader cache, and device selection.
- Performance: conservative/balanced/performance presets, relevant threading and compilation options when actually supported; do not promise unsafe overclocking or fictional optimizations.
- Input: controller/keyboard mapping, preferred device, vibration and accessibility controls.
- Audio: output device, volume and latency where exposed.
- Games: separate save/user profiles, installation locations, title/version-specific workarounds, per-game overrides and compatibility notices.
- Diagnostics/privacy: log level, crash reporting consent, optional telemetry **off unless explicitly opted in**, and a way to view/export logs.

Define a typed, versioned settings schema with validation and migrations. Keep safe defaults, detect unsupported combinations, and describe which preferences require restart. Separate a future optional Settings UI from the headless launch contract; neither settings nor a frontend are prerequisites for routine double-click launches. Do not add placeholder controls that silently do nothing.

## Future hardware-adaptive performance (planned; not yet implemented)

The target is **the smoothest correct performance the user's supported PC and title can sustain**, not 100% CPU/GPU utilization. Automatically choose validated defaults at first launch and retain an explicit, resettable user choice. Hardware adaptation is a future capability, **not** a claim of existing optimization, an extra G4 acceptance gate, or permission to begin G5 commercial-title work.

- **Capability detection:** locally identify the supported host CPU topology/features, system memory, Vulkan-capable GPUs, relevant driver/device capabilities and available VRAM budgets. Validate probe failures, changing hardware and unsupported configurations; fall back safely rather than assuming a dedicated GPU or a fixed core/VRAM count.
- **Safe automatic profile:** an Auto policy may choose among implemented conservative, balanced and performance settings using actual capability evidence and the supported title's needs. Explicit global/per-title overrides take precedence, can be reset, and must explain effective values and restart requirements. Never show an unsupported or nonfunctional tuning control.
- **Efficient resource use:** reduce proven CPU scheduling, compilation, shader-cache, resource lifetime and GPU synchronization bottlenecks. Favor Vulkan device suitability, bounded memory/VRAM use and correct frame pacing. Never force all cores, maximum clock rates, 100% GPU load, unsafe overclocking, host power-setting changes or correctness-breaking shortcuts.
- **Evidence-driven refinement:** only after a reproducible interactive guest workload exists, measure frame times (including tail latency/stutter), delivered FPS and 1% lows where meaningful, CPU/GPU bottlenecks, RAM/VRAM behavior, shader compilation and device/driver details at fixed settings. Compare Auto against a documented baseline across representative low-, mid- and high-capability PCs and supported workloads; record regressions, limits and thermal/power tradeoffs. No fabricated FPS or universal smoothness promises.
- **Adaptation boundaries:** any dynamic tuning must be limited to actually supported, reversible controls; protect guest timing, graphics correctness, audio/input latency, saves and lifecycle. Do not silently change Windows device, audio, driver, thermal or power settings. Provide a conservative fallback if probes, feedback or optimization fail.
- **Privacy and compatibility:** keep hardware profiles and performance diagnostics local by default, use existing versioned settings and per-title compatibility records, and require explicit opt-in for external telemetry. Title-specific exceptions must be evidence-backed rather than advertised as universal optimization.

This future work follows completion of the currently authorized G4 source/safety integration and appropriate interactive acceptance. It must be separately scoped and approved before implementation; it does not change G4 NO-GO, the G5 freeze, or physical-execution restrictions.

## Technical principles

- Execute compatible PS4 x86-64 instructions on the host x86-64 CPU directly where practical. Native CPU execution alone does not eliminate emulation or runtime compatibility engineering.
- Reproduce PS4 loading, relocations, import resolution, TLS, guest ABI, thread/process setup, system APIs, memory, filesystem, audio, input, time and synchronization correctly.
- Translate GPU commands/shaders and synchronization to a supported host backend, initially Vulkan; do not claim PS4 graphics commands run natively.
- Prefer a shared platform core with upstream-first shadPS4 research/reuse over manually converting each game or copying title-specific patches into the core. Establish actual integration boundaries and licensing before copying/linking components.
- Keep Windows shell/integration, installation and game discovery separate from the runtime engine and a stable launch interface. File association handlers must not inspect or execute untrusted guest code inside Explorer.
- Track title ID, game version, runtime revision, Windows version, CPU/GPU/driver, actual boot/gameplay status, failures and versioned patches. Favor shared fixes and reproducible evidence.
- No games, proprietary SDK, firmware, decryption keys or copyrighted assets in this repository. Do not promise automatic DRM removal or that a standard installer grants access to commercial game files.

## Proposed component boundaries

1. PS4 compatibility engine: validated loader, imports, relocations, TLS/ABI, native guest execution, HLE/system services, Vulkan, input/audio, saves, crash diagnostics.
2. Stable launch interface: an explicit launch command or API that returns precise errors, logs and session IDs; separate guest process where feasible for fault containment.
3. Windows integration: installer, updates/uninstall, game registration, guarded file associations, desktop/Start shortcuts, **optional user settings UI**, and user-friendly prerequisite checks.
4. Compatibility metadata: evidence-backed game/version profiles and tests; never label a title playable just because it boots.

## Measurable acceptance gates

- G0 — **Done in PR #2:** structural ELF inspection and restricted, verified synthetic RX/RW probe returning 42. Not a PS4 application launch.
- G1 — **Research in PR #3:** build pinned shadPS4 reference and official OpenOrbis hello_world fixture reproducibly; record hashes, dependencies, licensing, unresolved imports. A build or CLI help test is not guest execution.
- G2 — Actual PS4 homebrew startup: load a legitimate OpenOrbis sample using real PS4 module/ABI handling, capture expected messages through system services and bounded tests, document unsupported imports/faults.
- G3 — Windows one-click homebrew: install once and launch the supported homebrew from a desktop shortcut/double-click, with automated install, upgrade, invalid input, launch and uninstall tests. Add versioned global/per-title settings persistence and an optional settings entry point; test that changing a supported preference takes effect, reset works, and normal launches remain zero-prompt.
- G4 — Interactive PS4 homebrew: graphics on host Vulkan plus working input and audio where exercised; stable shutdown.
- G5 — First supported commercial title using lawfully obtained accessible inputs: reproducible gameplay with graphics/input/audio/saves. Distinguish boot, menu, in-game, and demonstrated playability.
- G6 — Scale: second title with different architecture/service demands, versioned compatibility reports, regression tests, general fixes and progressively less per-title setup.

No milestone is done based only on scaffolding, mocked execution, documentation, or a synthetic probe. The exact ordering of G3 and G4 may evolve, but functional startup takes precedence over UI polish.

## Development decision rules

- Every PR should name its gate, acceptance criteria, validation results, known limits and upstream/licensing implications.
- Preserve current inspector, CLI diagnostics, fixed-probe guard and tests. Never loosen the probe's hardcoded safe gate to run arbitrary guest code as a shortcut.
- Continue on task-scoped branches, PRs and owner-authorized merges; do not push directly to main.
- Prefer integrating and contributing upstream solutions when feasible; do not rebuild shadPS4's entire loader/renderer without evidence it is necessary.
- Do not confuse native CPU execution with zero emulation or imply full compatibility ahead of tests.

Related: [architecture](architecture.md), [roadmap](roadmap.md), [foundation decision](decisions/0001-foundation.md).