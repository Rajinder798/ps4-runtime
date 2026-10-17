# Instructions for Codex and contributors

**Read [docs/product-vision.md](docs/product-vision.md) before planning or coding.** The owner's end goal is a Windows 10/11 x86-64 application installed once, after which a double-click on a supported PS4 game shortcut/file launches it directly without a traditional emulator frontend or repetitive per-launch setup.

This is a native-x86-64-execution PS4 **compatibility layer**. It cannot skip PS4 OS/API/ABI and graphics translation requirements, and it must never claim every game currently works.

## Before each task

1. Review README.md, docs/architecture.md, docs/roadmap.md, docs/development.md, docs/decisions/0001-foundation.md and docs/product-vision.md.
2. Check existing and draft PRs (especially upstream baseline/homebrew PR #3) to avoid duplicating unfinished work.
3. Define the smallest milestone/gate, its concrete acceptance tests, and implementation risks before changing files.
4. Work on a dedicated branch and submit a PR; **do not push directly to main or merge without explicit owner authorization**.

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

Every PR identifies the product-vision gate, tests, local/hosted results, known missing functionality, licensing/security review, and instructions for reproduction. Request owner review; no autonomous merging.