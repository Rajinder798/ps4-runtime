# 0001: Use shadPS4 as the upstream foundation; start with an independent inspector

Date: 17 October 2026. Status: selected direction; integration not yet implemented.

## Decision

Use shadPS4's general platform infrastructure as the foundation for future native
execution and Vulkan work. Keep upstream changes easy to compare and contribute.
Do not generalize the God of War III prepared-image format into our application
format. Start this repository with a small original C++20 inspector and a
deterministic synthetic probe, with no imported upstream implementation.

The inspector is a development tool, not a replacement for shadPS4's core. The
next integration should build a pinned upstream baseline and exercise the probe
through an explicit loader boundary before attempting a commercial title.
Whether the core is vendored or maintained as a fork will be decided after that
build; no standalone shadPS4 library interface has been established here.

## Evidence and revisions

- Local God of War III reference: `C:/gow3 repo/gow3_pc`, branch
  `rajinder/fix-diagnostics-layout`, HEAD ref
  `e48d9cd453a686956e12f16ed6da288a4e92ecba`. This was a read-only audit of
  the working files; they may include uncommitted changes. No reference files
  were altered. The branch/ref were read directly from `.git`.
- shadPS4 candidate revision:
  [`e6c79a5fe0ea2f3d03fcb9c5c50cf61af063f3f5`](https://github.com/shadps4-emu/shadPS4/tree/e6c79a5fe0ea2f3d03fcb9c5c50cf61af063f3f5).
  GitHub API `commits/main` resolved this revision during the audit. The files
  below were inspected at that revision. This is a research pin, not an
  installed runtime dependency.

| Area | God of War III working checkout | shadPS4 candidate | Implication |
| --- | --- | --- | --- |
| Executable preparation | `scripts/prepare.py` creates G3PROBE2; `scripts/link_modules.py` produces G3PROBE5 with default `libc.prx` and `libSceFios2.prx`, bindings and TLS metadata | `src/core/loader/elf.h`, `src/core/module.cpp` describe ELF/SELF and map module segments | Use module-oriented loading rather than require a game preparation pipeline. |
| Entry and linking | `src/probe.c` reads the custom image, resolves imports, sets TLS, installs hooks, and enters code; it also calls game-specific hook modules | `src/core/linker.cpp` coordinates modules, relocation, imports, TLS and guest entry; `src/core/loader/symbols_resolver.cpp` maintains symbol records | Reuse the general lifecycle as a coherent unit; a direct CPU call alone is insufficient. |
| System services | `src/runtime*.c` supplies threads, memory, files, audio, input, saves and services; `runtime.c` contains scoped imports and assumptions about the supplied libc | `src/core/libraries/kernel/` separates memory, files, threads and synchronization; `src/core/tls.cpp` has host-specific TLS support | Prefer shared platform implementations and explicit failure for unsupported imports. Coverage still needs tests. |
| Graphics | `gpu/shadps4/` contains video/shader code; `gpu/shim/gow3gpu.cpp` bridges symbols, faults, GnmDriver, VideoOut and host services | `src/video_core/renderer_vulkan/vk_rasterizer.cpp` depends on `core/memory`, buffer/texture caches, Liverpool state, scheduler and shader runtime | The backend is not an isolated renderer drop-in. Preserve memory and synchronization contracts together. |
| Title behavior | `src/probe.c`, `patches/`, `gow3_overlay.cpp`, settings, actor/orb hooks | A broad core is present, but that does not establish compatibility for any particular title here | Keep future title profiles outside core services; do not carry cheats or title defaults into the shared runtime. |

Source links for the pinned comparison:
[module](https://github.com/shadps4-emu/shadPS4/blob/e6c79a5fe0ea2f3d03fcb9c5c50cf61af063f3f5/src/core/module.cpp),
[linker](https://github.com/shadps4-emu/shadPS4/blob/e6c79a5fe0ea2f3d03fcb9c5c50cf61af063f3f5/src/core/linker.cpp),
[TLS](https://github.com/shadps4-emu/shadPS4/blob/e6c79a5fe0ea2f3d03fcb9c5c50cf61af063f3f5/src/core/tls.cpp),
[symbol resolver](https://github.com/shadps4-emu/shadPS4/blob/e6c79a5fe0ea2f3d03fcb9c5c50cf61af063f3f5/src/core/loader/symbols_resolver.cpp),
[Vulkan rasterizer](https://github.com/shadps4-emu/shadPS4/blob/e6c79a5fe0ea2f3d03fcb9c5c50cf61af063f3f5/src/video_core/renderer_vulkan/vk_rasterizer.cpp).

## Reuse and licensing boundary

The God of War III README states GPL v2 or later, with separate third-party
licenses. Its root and GPU LICENSE files contain GPL v2 text. The inspected
shadPS4 core files declare `GPL-2.0-or-later` in their SPDX headers; its root
[LICENSE](https://github.com/shadps4-emu/shadPS4/blob/e6c79a5fe0ea2f3d03fcb9c5c50cf61af063f3f5/LICENSE)
contains GPL v2. This is source provenance, not a complete dependency license audit.

No upstream source is copied or linked by this milestone. The repository's own
license has not been selected by its owner. GPL-2.0-or-later is the recommended
direction for a future upstream-derived core; resolve that choice before importing
or distributing such a core. Preserve upstream SPDX headers, copyright notices,
license texts, attribution and source obligations. Audit all bundled dependencies
at the actual integration revision rather than assume the root license covers them.

## Dependency inventory

Current product: C++20 standard library only. Build: CMake 3.24 or newer; tests and
probe generation: Python 3.9 or newer. There are no Vulkan, SDK or firmware
dependencies in this milestone.

The candidate shadPS4 CMake file uses C++23 and CMake 3.24+, with dependencies
including SDL3, Vulkan headers/loader, VMA, shader tools, fmt, Boost, audio and
image libraries. Its git tree also pins numerous external submodules. These are
not adopted by this build. A future integration must preserve the full pinned
submodule graph and record buildable versions and per-component licenses.

## First executable and acceptance criteria

`tools/make_probe.py` generates an original 8,200-byte ELF64 little-endian x86-64
fixture with FreeBSD OS ABI 9 and type `ET_SCE_DYNEXEC`. It has separate RX and RW
PT_LOAD segments and a zero-fill data tail. The RX stub is `mov eax, 42; ret`.
It has no imports, relocations, TLS, SDK, assets or firmware. It is a synthetic
PS4-format inspection fixture, not a validated PS4 homebrew application.
Its return stub is suitable for a later controlled function-call mapping test;
it is not a console process startup routine or proof of the PS4 entry ABI.

Expected SHA-256:
`a7ae081593a449bd9c77d4efcb6e800aed2c499ec4b9cc6bebf379ebed46d7e7`.

This milestone accepts only structural inspection: parse headers, identify
segments, expose permissions and zero-fill sizes, reject invalid ranges and
unsupported containers, and emit stable text/JSON diagnostics. Loading,
relocations, symbol resolution, thread initialization and execution remain future work.

Follow-up implemented: the bounded host mapper copies the synthetic segments,
checks the loaded probe bytes and zero-fill, applies final protections, and
calls the fixed stub to observe 42. This is a host function call, not PS4 process
startup. The current experiment is described in [development](../development.md).

Next: build the pinned upstream baseline on Windows x86-64. Select and pin an
actual OpenOrbis homebrew build before testing console process startup, imports
or services. Resolve the repository license before importing upstream code.

Follow-up research now provides [pinned baseline and homebrew build recipes](../upstream-baseline.md).
The selected official OpenOrbis hello_world sample builds and passes structural
inspection; it has not been executed. Upstream build results are recorded per
run, separately from runtime integration and startup compatibility.
