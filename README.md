# PS4 Runtime

A general-purpose PS4 compatibility runtime project for x86-64 PCs.

The goal is one shared runtime capable of supporting the PS4 game library, with
compatibility established through testing each title and version. Universal
compatibility is a long-term goal, not a current capability or guarantee.

## Current status

The C++ command-line tool inspects ELF headers and segments and can now map and
execute the known synthetic return probe. The probe returns `42` after copied
bytes, zero-fill and final memory protections are checked. General PS4 process
startup, system services, graphics and playable games are not implemented.

```powershell
cmake -S . -B build/native -DCMAKE_BUILD_TYPE=Release
cmake --build build/native --config Release
ctest --test-dir build/native -C Release --output-on-failure
python tools/make_probe.py build/probe.elf
.\build\native\ps4-runtime.exe inspect build/probe.elf --json
.\build\native\ps4-runtime.exe probe build/probe.elf --json
```

Visual Studio builds place the executable under `build/native/Release/`.
See [development instructions](docs/development.md) for requirements, supported
formats, diagnostics and limitations.

The `probe` command is restricted to the generated fixture's segment layout and
loaded bytes. It does not run an arbitrary ELF or a commercial game. The stub
uses a plain function return; it does not exercise the PS4 process entry ABI.

## Intended approach

- Execute supported PS4 x86-64 game code directly on an x86-64 host CPU.
- Provide compatible implementations of PS4 system functions and services.
- Translate PS4 GPU commands and shaders through a Vulkan graphics backend.
- Keep title-specific patches and workarounds in separate, versioned profiles.
- Report unsupported features explicitly and track compatibility using evidence.

Direct CPU execution does not remove the need to reproduce console behavior.
The system and GPU layers still use emulation techniques.

## Starting point

This project grew from studying the game-specific God of War III PC runtime:
https://github.com/FelipePrado0/gow3_pc

shadPS4 is an important candidate foundation for shared platform and graphics work:
https://github.com/shadps4-emu/shadPS4

No code from either project has been imported. The initial audit selects an
upstream-first shadPS4 foundation for future platform and Vulkan integration.
The [foundation decision](docs/decisions/0001-foundation.md) records the source
revision, reuse boundaries, license status and next loader experiment.

## Project documents

- [Architecture](docs/architecture.md)
- [Roadmap](docs/roadmap.md)
- [Foundation decision](docs/decisions/0001-foundation.md)
- [Build, test and CLI contract](docs/development.md)
- [Pinned upstream build and selected homebrew](docs/upstream-baseline.md)

No game executables, assets, firmware, keys, or proprietary SDK files are included.
