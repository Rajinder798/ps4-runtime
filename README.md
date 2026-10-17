# PS4 Runtime

A general-purpose PS4 compatibility runtime project for x86-64 PCs.

The goal is one shared runtime capable of supporting the PS4 game library, with
compatibility established through testing each title and version. Universal
compatibility is a long-term goal, not a current capability or guarantee.

## Long-term Windows experience

**Install once, then double-click a supported PS4 game's Windows shortcut to launch it directly**, without a traditional emulator frontend or manual per-launch setup. This is a product goal, not a current capability or a universal compatibility promise. Users can also open optional **Settings** to customize supported graphics, performance, input, audio and per-game preferences; good defaults preserve one-click launching. See [product vision and acceptance gates](docs/product-vision.md). Compatible CPU instructions may execute natively, but PS4 system and graphics behavior still requires a compatibility layer.

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

No upstream engine is linked into the inspector/probe. A reviewed research patch
adds strict startup diagnostics in a separate pinned shadPS4 checkout. The
initial audit selects an upstream-first shadPS4 foundation for future platform
and Vulkan integration.
The [foundation decision](docs/decisions/0001-foundation.md) records the source
revision, reuse boundaries, license status and next loader experiment.

## Project documents

- [Windows product vision and acceptance gates](docs/product-vision.md)
- [Architecture](docs/architecture.md)
- [Roadmap](docs/roadmap.md)
- [Foundation decision](docs/decisions/0001-foundation.md)
- [G2 engine boundary and focused component audit](docs/decisions/0002-g2-engine-boundary.md)
- [Bounded homebrew startup harness and strict diagnostics](docs/startup-research.md)
- [Build, test and CLI contract](docs/development.md)
- [Pinned upstream build and selected homebrew](docs/upstream-baseline.md)

No game executables, assets, firmware, keys, or proprietary SDK files are included.

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
