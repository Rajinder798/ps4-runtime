# Proposed architecture

Most of this design is not yet implemented. The current code provides structural
ELF inspection and a bounded segment mapper that can execute only a verified
synthetic return stub. It does not start a PS4 process or run games.

## Host platform

Start with Windows on x86-64 and keep host-specific code behind narrow interfaces.
Vulkan is the proposed graphics API. Other host platforms can follow after a
working baseline exists.

## Shared components

| Component | Responsibility |
| --- | --- |
| Executable loader | Validate executable formats, map segments, process relocations, resolve imports, and prepare thread-local storage. |
| Symbol registry | Resolve PS4 library identifiers and function imports, and report missing implementations. |
| System runtime | Implement memory, threads, synchronization, files, time, and required service behavior. |
| Graphics backend | Translate supported PS4 graphics commands, shaders, resource layouts, and synchronization to Vulkan. |
| Audio and input | Supply audio output and controller interfaces through host adapters. |
| Save storage | Isolate saves by title and user with predictable host paths. |
| Game profiles | Match title IDs and versions; apply scoped patches without embedding title assumptions in shared code. |
| Diagnostics | Capture missing imports, faults, graphics failures, and reproducible run metadata. |

## Foundation decision

The [first foundation decision](decisions/0001-foundation.md) selects shadPS4's
general infrastructure for future platform and Vulkan integration, with an
upstream-first approach. The original inspector is independent; the upstream
engine remains external to its targets. A pinned upstream Windows build and selected
homebrew build are now validated in [baseline research](upstream-baseline.md);
the project has adopted [GPL-2.0-or-later](licensing.md), while the component
license and dependency review remains a prerequisite for integration.

The existing God of War III project remains a separate reference checkout.

The [G2 integration decision](decisions/0002-g2-engine-boundary.md) keeps the
pinned upstream engine in a separate process for initial homebrew research.
The inspected startup path couples loading, services, TLS and graphics; no
standalone loader library has been established. The focused audit records
release holds for FDK AAC and incomplete dependency/source compliance review.
The [bounded startup harness](startup-research.md) and strict research patch are
implemented with process/evidence contract tests. The selected OpenOrbis
hello_world now passes actual startup through this research boundary, including
strict import checks, guest messages, the two-second delay and process cleanup.
This validates one fixture, not general guest compatibility; no engine is linked
into the inspector. See the [bounded service coverage](startup-research.md#bounded-kernel-services).
An independent [second fixture](homebrew-services.md) now checks guest file
read/write/seek and worker create/join with random input and independently
verified output, through the same research process boundary.

The [local launch interface](launch-contract.md) now persists verified input
paths separately from execution and allocates a fresh logged session per fixture
launch. The original research runner supplies the shared strict execution path;
the new source command supplies versioned registration, response and failure
contracts. [Local Windows shortcuts](shortcuts.md) start a separate console-free
process through that command's shared launch path. No custom Explorer handler
is installed. Installer and user settings remain separate components.

The [settings core](settings.md) stores only supported diagnostic preferences
separately from registration. It resolves defaults/global/title overrides once
per launch, records that snapshot, and translates it into the fresh research
engine session configuration. This keeps user preference persistence outside the
guest engine and preserves the zero-prompt shortcut path. The optional Windows
Settings window uses that same validated store without launching an engine;
Tk is imported only by the separate UI entry point. Further capability-backed
controls remain future work.

## Implemented mapping experiment

`MappedImage` owns a rebased, anonymous host mapping. It preserves relative guest
segment addresses, copies file bytes, initializes zero-fill tails, and applies
R/RX/RW protections on separate pages. Unmapped gaps remain inaccessible. The
whole address range is released on destruction, including partial construction
failure. The current host adapters use VirtualAlloc/VirtualProtect on Windows
and mmap/mprotect on Linux.

The mapper rejects unsupported executable types, non-load metadata (including
dynamic linking and TLS), overlapping host pages, RWX permissions and image
spans above 64 MiB. These are experimental restrictions, not PS4 hardware limits.
The `probe` execution path validates the canonical layout, code, marker and BSS
before calling the six-byte return stub. It has no general guest entry trampoline,
relocation processing, import resolver, exception recovery or guest thread state.

## Compatibility evidence

Track results by title ID, game version, runtime revision, host OS, CPU, GPU, and
driver. Distinguish loading, reaching menus, entering gameplay, and demonstrated
playability. Record known issues and the scope of testing; a boot is not proof of
full-game compatibility.
