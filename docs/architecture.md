# Proposed architecture

This is an initial design, not a description of implemented functionality.

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

Before importing code, compare extending shadPS4 against extracting reusable parts
of the God of War III runtime. Assess library coverage, loader assumptions, GPU
integration boundaries, maintainability, and upstream licenses and attribution.
Record the selected approach and the evidence in a design decision document.

The existing God of War III project remains a separate reference checkout.

## Compatibility evidence

Track results by title ID, game version, runtime revision, host OS, CPU, GPU, and
driver. Distinguish loading, reaching menus, entering gameplay, and demonstrated
playability. Record known issues and the scope of testing; a boot is not proof of
full-game compatibility.
