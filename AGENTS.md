# Instructions for Codex and contributors

**Read [docs/product-vision.md](docs/product-vision.md) before planning or coding.** The owner's end goal is a Windows 10/11 x86-64 application installed once, after which a double-click on a supported PS4 game shortcut/file launches it directly without a traditional emulator frontend or repetitive per-launch setup.

This is a native-x86-64-execution PS4 **compatibility layer**. It cannot skip PS4 OS/API/ABI and graphics translation requirements, and it must never claim every game currently works.

## Before each task

1. Review README.md, docs/architecture.md, docs/roadmap.md, docs/development.md, docs/decisions/0001-foundation.md and docs/product-vision.md, plus the relevant current research/release decisions.
2. Check merged, open and draft PRs, active CI runs, and the current `main` baseline. Do not duplicate unfinished work or assume a stale PR number is still open.
3. Define the smallest relevant milestone/gate, its concrete acceptance tests, dependencies and risks before changing files.
4. Work on a dedicated branch and submit a PR; **do not push directly to main or merge without explicit owner authorization**.

## Priorities and choosing the next task

- The central product goal is **more supported PS4 software running correctly through a simple Windows launch path**, not the number of PRs, passing builds, or release paperwork alone. A verified OpenOrbis `hello_world` run in an isolated shadPS4 research engine establishes one G2 sample, not arbitrary-game support or a standalone PS4 Runtime engine.
- After G2, prioritize an **independent second homebrew fixture** that exercises additional real services and yields independently checked guest output. Then advance the stable Windows launch contract, zero-prompt supported-homebrew shortcuts, validated persistent global/per-title settings, and interactive Vulkan/input/audio homebrew along the product-vision gates. The precise order must follow proven dependencies and test outcomes.
- Keep **runtime/functionality work** and **redistribution/license compliance** as explicitly separate tracks. Continue necessary dependency, source and relinking audits, but do not let packaging-only PRs indefinitely displace verifiable execution/launch milestones. Never distribute an engine or third-party binaries until the applicable license/security requirements are satisfied; local research may continue within those boundaries.
- When asked for the "next task," inspect evidence and propose the smallest testable step toward a missing functional capability, with a clear reason, blocked dependencies and a fallback. Do not invent a new roadmap gate or build unrequested frontends/features.
- Prefer reuse and upstream contributions where technically and legally appropriate. Keep pinned research engine modifications and the independently owned inspector/probe distinct; don't claim shadPS4 execution is execution by a standalone engine.

## Verification and CI evidence

- Distinguish **source builds**, **host-side/unit tests**, **real PS4 guest entry and observable behavior**, **interactive rendering**, **commercial gameplay**, and **release readiness**. Success at one level must never be represented as success at another.
- Run relevant local tests and hosted Windows/Linux checks for each changed surface. Where applicable, include full strict-engine, homebrew and dependency-audit workflows rather than treating the baseline inspector CI as sufficient.
- Before saying a PR is ready to merge, inspect the final status of all relevant completed workflows and available log/evidence artifacts. Identify actual errors and **new, material warnings**; distinguish existing upstream/dependency warnings from regressions. Do not demand removal of all unrelated upstream warnings.
- When checks are running or evidence is unavailable, report **pending/unverified**, identify exactly which validation remains and update the PR description once completed. Do not claim green CI, an independent rebuild or guest execution on the basis of a proposed workflow or local summary alone.
- Preserve representative reproducibility data: source/patch and fixture identifiers, commands, platforms/toolchain, output/artifact paths, pass/fail results, and explicitly unresolved limitations. Never fabricate log contents, FPS, 1% lows, timing measurements or compatibility claims.
- Use actual graphics/gameplay benchmarks only after working interactive guest software exists, and record host CPU/GPU/driver, resolution, settings, FPS/frame times and reproducibility. A title-specific game's performance is a reference, not a result for PS4 Runtime.

## Settings are part of the end goal

Users must be able to personalize supported graphics, performance, input, audio, game and privacy settings. Auto-detected defaults enable an uncomplicated double-click; a separate optional Settings UI supports global preferences, per-game overrides, reset and validation. Implement controls only when the corresponding runtime capability exists; never expose fake knobs. Store validated/versioned preferences, honor consent for telemetry, and test persistence and effective configuration.

## Engineering guardrails

- Windows 10/11 x86-64 first; preserve useful Linux CI tests.
- Preserve existing inspected-ELF and verified synthetic-probe behavior, CLI JSON/exit contracts and regression tests. Never loosen fixed probe validation to execute an arbitrary ELF.
- Separate shell integration/installer from guest execution and keep a stable launch API or CLI; do not execute guest code from Explorer handlers.
- Prefer evaluated/pinned upstream shadPS4 components. Establish a supported integration boundary and audit GPL/dependency licenses before importing code.
- PS4 game files do not become Windows PE executables through file associations; native CPU instructions still need correct PS4 loader, imports, TLS, system services and Vulkan translation.
- Keep game-specific workarounds in versioned profiles, not core. Keep reliable logs, crash containment and documented unsupported behavior.
- Never commit copyrighted games, firmware, proprietary SDK, keys or DRM-bypass material.
- Report tested versus planned capabilities honestly. A homebrew compile, native synthetic return, boot or menu does not prove commercial playability.

## Definition of done

Every PR identifies the product-vision gate, scoped user-visible or runtime capability (or explicit prerequisite), acceptance criteria, tests, local/hosted results **with pending checks named**, known missing functionality, licensing/security review and reproduction instructions. For functional guest claims include actual guest evidence; for dependency/release work state exactly which holds remain open. Request owner review; no autonomous merging.