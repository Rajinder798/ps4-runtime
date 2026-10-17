# Pinned upstream baseline and first homebrew

This research build is separate from our runtime. It does not import or link
shadPS4 into the application, change either upstream project, or establish game
compatibility. Pins and checksums live in `config/upstream-lock.json`.

## shadPS4 Windows build

Source: [shadPS4 e6c79a5f](https://github.com/shadps4-emu/shadPS4/tree/e6c79a5fe0ea2f3d03fcb9c5c50cf61af063f3f5).
The recipe checks out the exact revision and initializes recursive submodules at
their recorded gitlinks. An existing checkout at another revision or with local
changes is rejected rather than reset. All upstream source lives under ignored
`build/upstream/shadps4`; the runtime's CMake targets remain independent.

The pinned [Windows guide](https://github.com/shadps4-emu/shadPS4/blob/e6c79a5fe0ea2f3d03fcb9c5c50cf61af063f3f5/documents/building-windows.md)
states that MinGW is broken. Our working LLVM-MinGW toolchain is therefore not
used to build shadPS4. Use Windows x86-64 with Visual Studio C++/Windows SDK,
clang-cl, Ninja, CMake and Python 3.12+. The CI job uses
`windows-2025-vs2026`, matching the pinned upstream Windows runner choice.

From an x64 Visual Studio developer shell:

```powershell
python tools/upstream_baseline.py prepare
python tools/upstream_baseline.py inventory
python tools/upstream_baseline.py build --jobs 4
```

The build uses Release, bundled dependencies, no LTO, no updater, no Discord RPC,
and no upstream unit-test build. These options are explicit in the lock file.
The upstream command-line executable is built and `--help` must succeed and
identify itself as the shadPS4 CLI. This smoke test does not initialize graphics,
start a guest process, or measure runtime compatibility.

FFmpeg is a prebuilt dependency in the upstream build. The recipe verifies its
gitlink and seeds the build's expected archive path from the locked release,
checking SHA-256 before CMake uses it:

- FFmpeg source revision: `94dde08c8a9e4271a93a2a7e4159e9fb05d30c0a`.
- Release: `94dde08`, asset `ffmpeg-windows-x64.zip`.
- SHA-256: `5038087e7798a0b129dbb4ff4a0caf4b6995aff91f5bf424096f65840385661d`.

`build/upstream/evidence/` records exact recursive submodule revisions, discovered
notice filenames/hashes, build options, tool versions, runner image, executable
hash, CLI help and the build log. CI uploads this evidence, without upstream
binaries or SDK material. See the
[baseline workflow runs](https://github.com/Rajinder798/ps4-runtime/actions/workflows/upstream-baseline.yml).

Validation on 17 October 2026:
[independent Windows source build](https://github.com/Rajinder798/ps4-runtime/actions/runs/39042281651)
passed, including the compiled executable's CLI-help smoke test and a clean
source-tree check after the build. The report records 54 recursive submodules
and inventories root notice candidates for 55 components. One component,
`externals/mesa-kosmickrisp/externals/mesa`, has no matching root notice filename;
that needs manual review, along with the rest of the unreviewed inventory.

Recorded environment: Windows Server 2025, runner image `20261007.264.1`,
Clang-cl 20.1.8, CMake 4.4.4, Ninja 1.13.2, Git 2.56.0.windows.2.
The produced executable's SHA-256 was
`cebde6eb17c5476645d7877146136d9f122ba7ad8ca6871e8a7931f208e5e3f9`.
The evidence explicitly records `guest_execution_tested: false`.

Source/dependency pins make inputs traceable; this is not a bit-for-bit
reproducible upstream binary claim. Hosted runner images, compilers, Windows SDKs
and upstream timestamp/version metadata can change. The evidence captures the
actual environment and output for each run.

## Selected homebrew: OpenOrbis hello_world

Use the official sample from [OpenOrbis v0.5.4](https://github.com/OpenOrbis/OpenOrbis-PS4-Toolchain/tree/b458dfd9d2f5c40aa249b127c9b9b4488afdc686/samples/hello_world),
revision `b458dfd9d2f5c40aa249b127c9b9b4488afdc686`, title ID `BREW00083`.
The official `toolchain-llvm-18.tar.gz` archive is pinned by URL and SHA-256:
`3c7cd5bb593ca74fa1c13fd59f3938dc0fc07985167f7275063019e63abe4526`.

This sample logs a greeting, calls `sceKernelUsleep` for two seconds, logs that
it is looping, and enters an infinite loop. It does not set up graphics. Its
static musl/libc++ dependencies still introduce 45 undefined dynamic symbols in
our build. The full list is captured in `dynamic-symbols.txt` and the JSON report.
They include file I/O, memory mapping, signals and pthread synchronization; the
sample is not merely one print call and one sleep call.

Build it on Windows using the same portable LLVM-MinGW `20261006` compiler used
by our probe development (Clang/LLD 23.1.3), targeting FreeBSD ELF explicitly:

```powershell
python tools/build_homebrew.py --llvm-bin build/tools/llvm-mingw-20261006-ucrt-x86_64/bin --inspector build/native/ps4-runtime.exe
```

For an MSVC build, use `build/native/Release/ps4-runtime.exe`. The research script
requires Python 3.12+. The normal runtime build still only needs Python 3.9+ for
its existing tests. The homebrew CI workflow downloads the compiler release
archive and verifies SHA-256 before extraction; its checksum is also recorded in
[development](development.md).

The recipe downloads and verifies the SDK archive, safely extracts it into the
ignored research directory, and compares 1,626 selected build input files
(headers, libraries, linker script, converter and sample inputs) with their
archive contents before compiling. It does not package a PKG or use Sony SDK
files. It creates only research outputs under `build/homebrew/hello-world`:

| Output | Purpose | Observed SHA-256 with the recorded compiler |
| --- | --- | --- |
| `hello_world.elf` | Linked FreeBSD ELF before conversion | `9b45aeb048720fa7e064f0654eec4437d903b9293b34f33a1999542e4f36561b` |
| `hello_world.oelf` | Converted Orbis ELF for inspection/startup research | `c5329274bc6cc356f2926d9ec89403e35907ec5f540ecd2e7b7d41ae552be670` |
| `eboot.bin` | Fake SELF produced by the official converter | `73636b3073fd50a8ddeb4b1f3cbcdfd369265c00f68b6813958a46f3ebcff5dd` |

Two repeated local builds and the independent
[Windows homebrew CI run](https://github.com/Rajinder798/ps4-runtime/actions/runs/39042600077)
produced these same hashes, with the same verified SDK input tree hash. They are
evidence for the recorded compiler and inputs, not a promise for every compiler version. The
converter embeds its input filename, so the script passes a fixed basename from
the output directory to avoid checkout-path differences in module metadata.

The `.oelf` is structurally inspected by our CLI. It contains ET_SCE_DYNEXEC,
16 KiB segment alignment, SCE RELRO/process parameters/dynamic data, relocations
and TLS. Our restricted `probe` command rejects its unsupported alignment;
it does not execute the sample. The script asserts that rejection. The SDK,
sample source and binaries remain outside tracked application source. CI uploads
only the build report and symbol inventory.

## Startup acceptance test for the next integration

The audited upstream launch path is not headless: `Emulator::Run` creates an SDL
window, then `InitHLELibs` registers GnmDriver and constructs a Vulkan presenter
before guest entry. Even this non-graphics sample therefore needs either an
appropriate graphics host for an upstream launch or a deliberately isolated
startup harness. A hosted `--help` pass does not test those facilities. Evidence:
[Emulator](https://github.com/shadps4-emu/shadPS4/blob/e6c79a5fe0ea2f3d03fcb9c5c50cf61af063f3f5/src/emulator.cpp),
[library initialization](https://github.com/shadps4-emu/shadPS4/blob/e6c79a5fe0ea2f3d03fcb9c5c50cf61af063f3f5/src/core/libraries/libs.cpp),
[GnmDriver registration](https://github.com/shadps4-emu/shadPS4/blob/e6c79a5fe0ea2f3d03fcb9c5c50cf61af063f3f5/src/core/libraries/gnmdriver/gnmdriver.cpp).

1. Load the `.oelf` through a general module loader with 16 KiB guest alignment,
   SCE metadata, relocations and import resolution. Do not relax the probe's
   fixed-byte execution guard to make this test run.
2. Establish the actual process entry stack/arguments, TLS and initializers before
   entering the sample. Record unsupported imports as failures with names.
3. Capture the greeting and the post-sleep loop message. Treat the infinite loop
   as expected sample behavior, not a process-exit success signal.
4. Use a bounded test process (for example, a 10-second budget); stop it after
   observing both markers or record the first failure/timeout. Preserve logs and
   host/runtime/source revisions. No startup result has been established yet.

## Licensing and integration boundary

The inspected shadPS4 core declares GPL-2.0-or-later. The OpenOrbis repository's
root license is GPL v3; bundled libraries/tools have their own notices. The
automated notice inventory discovers root files and hashes but does not review
license compatibility or prove that every dependency notice was found.

This repository's original material is now [GPL-2.0-or-later](licensing.md).
Before importing upstream implementation, inspect and retain each component's actual
copyright, license, attribution and source obligations at the chosen integration
revision. Building an isolated upstream checkout and separately building a
homebrew sample does not adopt those implementations into our runtime.

The [G2 decision and focused audit](decisions/0002-g2-engine-boundary.md) selects
the coherent pinned engine in a separate process for the first startup
experiment. The next implementation is a bounded harness and strict import
diagnostics, with startup/import/TLS behavior tested against this selected
sample. The current upstream path still requires SDL/Vulkan; its default build
has unresolved release licensing issues, including linked FDK AAC. The audit
does not authorize redistribution or establish execution. No game-specific
patches or reference-project changes are introduced here.
