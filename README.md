# PS4 Runtime

A planned general-purpose PS4 compatibility runtime for x86-64 PCs.

The goal is one shared runtime capable of supporting the PS4 game library, with
compatibility established through testing each title and version. Universal
compatibility is a long-term goal, not a current capability or guarantee.

## Current status

Project planning only. This repository does not yet contain a loader, runtime,
graphics backend, or playable games.

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

No code from either project has been imported. The first milestone is to inspect
the existing implementations and select the foundation before building a loader.

## Project documents

- [Architecture](docs/architecture.md)
- [Roadmap](docs/roadmap.md)

No game executables, assets, firmware, keys, or proprietary SDK files are included.
