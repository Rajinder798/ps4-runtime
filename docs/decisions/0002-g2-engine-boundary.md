# 0002: Preserve the upstream engine behind a process boundary for G2

Date: 17 October 2026. Status: selected research boundary; execution and release
approval remain open. This is a prerequisite for G2, not completion of G2.

## Decision

Use the pinned shadPS4 engine as a **separate child executable** for the first
OpenOrbis startup experiment. Keep module loading, relocation, import resolution,
TLS, guest threads, memory and services together in that engine. Maintain any
required changes as a small patch series against the pinned checkout; an
upstream contribution or maintained fork can carry those patches later. Do not
vendor individual loader files into this repository's inspector targets.

The upstream executable's launch options are the available integration surface,
not a promised stable library API. Start with a bounded research harness on a
Windows x86-64 machine with working Vulkan. A minimal headless engine target is
a possible later upstream change, not an existing capability. Preserve the
inspector/probe CLI, JSON/exit contracts, fixed-probe validation and tests.

This choice is about preserving the engine's behavior and controlling its
lifetime. A child process is not a security sandbox, and it does not solve
licensing issues inside the engine or authorize redistribution. No upstream
source, executable, SDK or sample binary is added by this decision.

## Evidence and review scope

Upstream pin:
[`e6c79a5f`](https://github.com/shadps4-emu/shadPS4/tree/e6c79a5fe0ea2f3d03fcb9c5c50cf61af063f3f5).
The [audit manifest](../../config/g2-integration-audit.json) records 28 inspected
source/build files, their Git blob IDs and SHA-256 hashes, and 17 focused
component notice reviews with exact revisions, URLs and hashes. Each inspected
source/build file declares GPL-2.0-or-later. This is an explicit set of reviewed
files, not a computed transitive include/link closure or complete SBOM.

The recursive pins and notice hashes were cross-checked against the
[`upstream-windows-evidence` artifact](https://github.com/Rajinder798/ps4-runtime/actions/runs/39042281651)
from the existing independent build: 54 submodules, 55 inventory entries including
the root. Downloaded notice bytes sometimes have LF endings while the Windows
artifact hashes CRLF checkout bytes. The manifest records both hashes and which
comparison matched; source hashes always refer to Git blob bytes.

## Why a standalone loader extraction is premature

| Observed path at the pin | Consequence for G2 |
| --- | --- |
| [`CMakeLists.txt`, executable and link lists](https://github.com/shadps4-emu/shadPS4/blob/e6c79a5fe0ea2f3d03fcb9c5c50cf61af063f3f5/CMakeLists.txt#L1318) | The normal build creates one executable containing core, graphics, audio, input and frontend code. It exports no standalone loader target. |
| [`Module::LoadModuleToMemory`](https://github.com/shadps4-emu/shadPS4/blob/e6c79a5fe0ea2f3d03fcb9c5c50cf61af063f3f5/src/core/module.cpp#L108) | Mapping uses the shared memory manager, CPU patch/trampoline machinery and TLS metadata; it is not the existing independent segment mapper. |
| [`Linker::Execute`](https://github.com/shadps4-emu/shadPS4/blob/e6c79a5fe0ea2f3d03fcb9c5c50cf61af063f3f5/src/core/linker.cpp#L71) | Relocation, memory regions, guest thread startup, system-module preload, custom modules and entry parameters are part of a shared lifecycle. Firmware modules are optional paths, not inputs to add to this fixture. |
| [`RunMainEntry`](https://github.com/shadps4-emu/shadPS4/blob/e6c79a5fe0ea2f3d03fcb9c5c50cf61af063f3f5/src/core/linker.cpp#L41), [`PS4_SYSV_ABI`](https://github.com/shadps4-emu/shadPS4/blob/e6c79a5fe0ea2f3d03fcb9c5c50cf61af063f3f5/src/common/types.h#L28) and `core/tls.cpp` | Entry prepares a stack and jumps into the module; service calls use the PS4/System V ABI. Windows TCB storage and guest instruction patching must remain coherent. Calling an ELF entry as an ordinary Windows function is insufficient. |
| [`Emulator::Run`](https://github.com/shadps4-emu/shadPS4/blob/e6c79a5fe0ea2f3d03fcb9c5c50cf61af063f3f5/src/emulator.cpp#L559), [`InitHLELibs`](https://github.com/shadps4-emu/shadPS4/blob/e6c79a5fe0ea2f3d03fcb9c5c50cf61af063f3f5/src/core/libraries/libs.cpp#L112) and [`GnmDriver::RegisterLib`](https://github.com/shadps4-emu/shadPS4/blob/e6c79a5fe0ea2f3d03fcb9c5c50cf61af063f3f5/src/core/libraries/gnmdriver/gnmdriver.cpp#L3036) | Startup creates standard handles and an SDL window, registers broad HLE services and constructs a Vulkan presenter before guest entry. A console-only sample does not make this path headless. |
| [`core/memory.cpp`](https://github.com/shadps4-emu/shadPS4/blob/e6c79a5fe0ea2f3d03fcb9c5c50cf61af063f3f5/src/core/memory.cpp#L131) | Memory operations call the rasterizer. Omitting graphics registration alone does not establish a working headless memory subsystem. |
| [`Linker::Resolve`](https://github.com/shadps4-emu/shadPS4/blob/e6c79a5fe0ea2f3d03fcb9c5c50cf61af063f3f5/src/core/linker.cpp#L391) and [`AeroLib::CommonStub`](https://github.com/shadps4-emu/shadPS4/blob/e6c79a5fe0ea2f3d03fcb9c5c50cf61af063f3f5/src/core/aerolib/stubs.cpp#L31) | Missing imports can become generated functions returning zero. Some fallback warnings are suppressed for libc/Fios2. Process survival or exit code zero cannot prove correct startup. |

Observed direct support dependencies include fmt/spdlog for logging, Boost for
memory intervals and kernel Asio, Zydis/Zycore and Xbyak for instruction work,
zstd/embedded resources in CPU patches, and shared settings/filesystem/devtools
facilities. These observations do not reduce the full executable's link graph
to that list. Inspect the actual configured build graph before extracting or
shipping a smaller engine.

The pinned root CMake also sets `-march=x86-64-v3` for x86-64 builds. Qualify the
test host against that CPU feature baseline as well as Vulkan requirements;
Windows x86-64 alone does not establish that this engine binary can run there.

## Focused licensing findings

The exact notice sources and hashes are in the manifest. A reviewed root notice
is evidence of that notice's terms, not approval of every file in its component.

| Reviewed components | Observed terms | Disposition |
| --- | --- | --- |
| fmt, spdlog, toml11, robin-map, Zydis and nested Zycore | MIT | Retain copyright, permission text and disclaimer; inspect bundled exceptions and actual source selection. |
| Boost | Boost Software License 1.0 | Preserve the applicable notices; check the selected headers and bundled code. |
| Xbyak, protobuf; xxHash | BSD 3-clause; BSD 2-clause for xxHash library | Preserve the respective source/binary notices and restrictions. |
| zstd | BSD 3-clause in LICENSE; COPYING also contains GPL v2 text | Use the BSD grant for selected code and check file-level exceptions. |
| SDL3 | zlib license | Preserve origin/change notices; required by the current windowed startup. |
| Abseil | Apache 2.0 | A combined GPL distribution needs compatible version selection. GPLv3 compatibility is available through GPL-2.0-or-later; GPL-2.0-only is insufficient. |
| OpenAL Soft; libusb | Representative source grants LGPL 2-or-later and LGPL 2.1-or-later respectively | Audit static-link compliance, corresponding source and relinking requirements before release. OpenAL also has a separate PFFFT notice. |
| FFmpeg prebuilt wrapper | Root copyright contains LGPL 2.1 text | Release hold: that text does not establish the license or complete corresponding source of the linked static binary. |
| FDK AAC | Custom Fraunhofer license | Release hold: resolve GPL compatibility before distributing an engine containing it. |

The [Apache compatibility guidance](https://www.apache.org/licenses/GPL-compatibility)
supports the GPL version distinction above. It does not relicense third-party
files or clear other dependencies.

**FDK AAC is a concrete issue in this build**, rather than a hypothetical future
dependency: the upstream executable links `fdk-aac`, and
[`externals/aacdec/CMakeLists.txt`](https://github.com/shadps4-emu/shadPS4/blob/e6c79a5fe0ea2f3d03fcb9c5c50cf61af063f3f5/externals/aacdec/CMakeLists.txt)
builds the pinned AAC source. Its
[NOTICE](https://android.googlesource.com/platform/external/aac/+/ee76460efbdb147e26d804c798949c23f174460b/NOTICE)
contains additional fee, modification and patent conditions. FFmpeg's
[licensing documentation](https://ffmpeg.org/doxygen/4.3/md_LICENSE.html)
identifies FDK AAC as incompatible with GPLv2 and GPLv3. Treat distributing the
default combined engine as blocked pending omission/replacement of that code or
a documented valid licensing resolution. Disabling audio at runtime or changing
our root license to GPLv3 does not establish that the linked code is absent.
This is separate from whether FFmpeg itself was built with FDK support.

The pinned FFmpeg wrapper's
[build workflow](https://github.com/shadps4-emu/ext-ffmpeg-core/blob/94dde08c8a9e4271a93a2a7e4159e9fb05d30c0a/.github/workflows/build.yml)
selects vcpkg revision `df8bfe519564ae001903e5cdd32af0999531ef71`, applies
`ffmpeg.patch` and requests specific features. Its
[CMake wrapper](https://github.com/shadps4-emu/ext-ffmpeg-core/blob/94dde08c8a9e4271a93a2a7e4159e9fb05d30c0a/CMakeLists.txt)
downloads static libraries. Next review must resolve the exact FFmpeg source and
ports/patch/configure inputs against the locked archive, not infer binary
licensing from the wrapper's root file. FFmpeg's
[distribution guidance](https://ffmpeg.org/legal.html) explains why build options
and corresponding source matter.

Remaining release review includes the rest of the Windows link graph, nested
dependencies, fonts/embedded resources, toolchain runtime redistribution and
complete attribution/source bundles. The Mesa child with no root notice remains
an open inventory issue; the pinned external CMake adds that driver branch under
`APPLE AND NOT ENABLE_SYSTEM_VULKAN AND NOT ENABLE_TESTS`, so it is outside the
proposed Windows target. It has not been declared license-free or fully audited.

## Next implementation: bounded startup harness

This is the concrete next change after this audit PR:

1. Verify the pinned engine build/evidence and the selected `.oelf` hash
   `c5329274bc6cc356f2926d9ec89403e35907ec5f540ecd2e7b7d41ae552be670`.
   Keep the engine and sample as local research inputs; do not add binaries to
   Git or publish an engine bundle while the release holds remain open.
2. Launch the engine directly with an argument array using its existing
   `--game` option, an absolute fixture path and `--ignore-game-patch`. Use a
   fresh working directory with a precreated `user/` directory before process
   start. The pinned `common/path_util.cpp` selects that portable directory;
   `--override-root` controls the guest application mount, not the user directory.
   Do not inherit custom modules, sysmodules, patches or personal runtime state.
3. Own the Windows child process tree with a Job Object and a finite wall-clock
   budget (initially 30 seconds). Capture stdout, stderr and fresh engine/guest
   logs, then terminate and wait for the tree after both expected markers or a
   failure/timeout. This controls lifetime; it does not sandbox native guest code.
4. Require the guest messages in order: `main: Hello world! Waiting 2 seconds!`
   and `main: Done. Infinitely looping...`. They come from the sample's logging
   helper through `printf`, not a renderer. The fixture has an intentional
   infinite loop, so successful evidence includes controlled termination rather
   than natural process exit. Do not inject expected messages in the harness.
5. Record engine/source/fixture hashes, host CPU/GPU/driver/Vulkan availability,
   command arguments, timestamps and termination reason. A graphics prerequisite
   failure, missing import, crash or timeout is a failed/unsupported attempt,
   never a skipped pass. The 45 imported names in the current build report come
   from the **pre-conversion ELF**; audit the converted SCE import identities and
   actual resolver results before asserting HLE coverage.
6. Add a small upstream strict-resolution patch if needed: collect unresolved
   relocations with their NID/library/module identities and fail before guest
   entry instead of accepting fallback stubs. Add a negative missing-import
   test. The unmodified CLI has no such strict option; scraping its exit code
   alone is insufficient for the qualifying G2 result.

G2 acceptance still requires actual guest startup with both markers, correct
sleep/service behavior, strict import results, bounded cleanup, reproducible
logs and the original inspector/probe regression tests. No execution result,
commercial-game support, installer or settings UI is established by this PR.

## Reproducing this review

Download the named baseline artifact from the linked run (`gh run download
39042281651 --name upstream-windows-evidence --dir build/g2-audit/baseline`).
Verify its `source-inventory.json` against the SHA-256 in the manifest. Compare
every selected component revision to that inventory. At the upstream pin, use
`git show REV:PATH` to hash canonical source bytes and `git rev-parse REV:PATH`
to compare blob IDs; do not hash Windows checkout line endings as Git bytes.

Fetch each manifest notice URL, decode base64 for the Gitiles `format=TEXT`
entry, and compare its SHA-256. For the baseline worktree hash, compare the raw
notice bytes or their LF-to-CRLF checkout representation as recorded. Read the
notice and the linked source/build call sites; hash equality is provenance
validation, not a substitute for reviewing terms or behavior. The supplementary
FFmpeg build and representative LGPL grant sources also have pinned hashes.
