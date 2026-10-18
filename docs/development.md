# Development baseline

## Build and run

Requirements: a C++20 compiler, CMake 3.24+, Python 3.9+ for tests. Windows x86-64
is the first target; CI also builds the inspector and mapper on Linux x86-64.
Visual Studio 2022 with its C++ workload or LLVM-MinGW can build this milestone.

```powershell
cmake -S . -B build/native -DCMAKE_BUILD_TYPE=Release
cmake --build build/native --config Release
ctest --test-dir build/native -C Release --output-on-failure
python tools/make_probe.py build/probe.elf
```

Single-configuration generators put the tool in `build/native/ps4-runtime.exe`;
Visual Studio puts it in `build/native/Release/ps4-runtime.exe`.

```powershell
.\build\native\ps4-runtime.exe inspect build/probe.elf
.\build\native\ps4-runtime.exe inspect build/probe.elf --json
.\build\native\ps4-runtime.exe probe build/probe.elf
.\build\native\ps4-runtime.exe probe build/probe.elf --json
```

The MinGW CLI links its runtime statically. For other builds using runtime DLLs,
the compiler's `bin` directory must be on PATH. Portable
tools used locally live under ignored `build/tools`; they are not part of the
repository or a required installation method. Tests use only generated data.

## Inspection contract

- Accepted: ELF64, little endian, x86-64; ET_EXEC, ET_DYN, ET_SCE_EXEC,
  ET_SCE_DYNEXEC and ET_SCE_DYNAMIC. Acceptance does not identify a file as a PS4
  title. OS ABI and ABI version are reported as metadata.
- Validated: version fields, ELF header size, program table size/count/range,
  file-backed segment ranges, memory size/address overflow and alignment for
  PT_LOAD, PT_TLS and PT_SCE_RELRO. At least one PT_LOAD is required.
- PT_NULL fields are ignored. Unknown program-header types are reported with
  their numeric IDs; their file ranges are checked but their semantics are not.
- `entry_in_executable_segment` describes address containment in an executable
  PT_LOAD or PT_SCE_RELRO memory range, including any zero-fill tail. It does not
  prove valid entry instructions or execution readiness. Shared objects may
  legitimately have no entry. JSON includes `execution_supported: false`.
- Unsupported: SELF unpacking, extended program counts, section-table validation,
  segment overlap policy, dynamic metadata, relocations, imports, TLS setup,
  general executable loading, Vulkan and PS4 process execution. The separate
  `probe` operation implements a restricted mapping/call experiment.
- Headers are read using bounded seeks; the complete executable is not allocated
  in memory. Invalid additions are checked using subtraction before arithmetic.

Exit codes: `0` successful inspection/help/version; `1` input or inspection error;
`2` invalid CLI usage. Errors always use stderr, including with `--json`:
`error[code]: message`. Successful JSON goes to stdout with `schema_version: 1`.
All address and size fields are unsigned integer byte values; consumers must
preserve 64-bit precision (JavaScript consumers should use a lossless parser).

The C++ tests exercise truncation, integer overflow, alignment, format/type
validation, TLS/RELRO constraints and entry boundary cases. Python tests run the
actual CLI, parse JSON, verify the probe hash, exercise Unicode/space paths and
check exit/error behavior.

## Probe mapping contract

`probe` maps a file through `MappedImage`, then calls it only if it matches the
generated fixture's type, OS ABI, entry, file size, two segment descriptions,
six instruction bytes and eight-byte data marker. The 4088-byte zero-fill tail
is checked before the call. Unloaded file padding is not compared to the fixture
hash. Code modifications (including a trap instruction) are rejected.

The mapper itself accepts ET_DYN/ET_SCE_DYNEXEC with PT_LOAD/PT_NULL only, at most
128 program headers, nonempty load segments, R/RX/RW permissions, alignment no
larger than the host page size and a total page-rounded span no larger than
64 MiB. Segment pages must not overlap or share a host page. TLS, dynamic and
other metadata are rejected rather than silently skipped. No relocations or
imports are processed. These are limits of this experiment.

The address range is reserved at a host-selected base and guest address spacing
is preserved. Each segment is writable while being copied/zeroed, then becomes
R, RX or RW; no RWX mapping is requested. Gaps remain inaccessible. Cache flush
and protection failures are reported; the RAII owner releases the entire
allocation on success or partial failure. The loaded image does not use the
guest's requested absolute host address.

Windows uses [VirtualAlloc](https://learn.microsoft.com/en-us/windows/win32/api/memoryapi/nf-memoryapi-virtualalloc),
[VirtualProtect](https://learn.microsoft.com/en-us/windows/win32/api/memoryapi/nf-memoryapi-virtualprotect)
and FlushInstructionCache. Linux uses
[mmap](https://man7.org/linux/man-pages/man2/mmap.2.html) and
[mprotect](https://man7.org/linux/man-pages/man2/mprotect.2.html).
The mapper requires an x86-64 Windows or Linux host. The current fixture and CI
exercise 4096-byte host pages.

The call is a host `int (*)()` call into `mov eax, 42; ret`. It establishes no
argument passing, System V ABI bridge, PS4 startup stack, TLS, services or fault
recovery. General PS4 process execution remains unsupported. A successful probe
returns CLI exit code `0`, with `return_value: 42` in JSON; it does not exit 42.
JSON reports the 14 verified copied bytes, 4088 verified zero-fill bytes, mapping
span, host page size and `general_execution_supported: false`. The inspect
operation continues to report `execution_supported: false`.

Mapping tests read host permissions through VirtualQuery or `/proc/self/maps`,
verify RX/RW/R pages and inaccessible gaps, write the RW segment, reject altered
code and unsupported layouts, exercise a payload read failure, and verify
release/repeated mapping. CLI tests also check native return values and rejection
before a modified trap instruction can execute.

## Validation record: 17 October 2026

Built and tested locally on Windows x86-64 using portable LLVM-MinGW
`20261006` (Clang 23.1.3), CMake 4.4.4, MinGW Makefiles and Python 3.12.14.
Warnings are errors. The inspection baseline passed its two suites locally and
on hosted Windows/MSVC and Linux CI. The mapping follow-up passes all three
suites locally: 167 ELF validation checks, 58 loader checks and the expanded CLI
contract tests. Both text and JSON probe commands returned 42. Hosted results
for each revision are recorded in [GitHub Actions](https://github.com/Rajinder798/ps4-runtime/actions).

The portable archives' SHA-256 hashes matched their GitHub release asset
digests before extraction:

| Archive | SHA-256 |
| --- | --- |
| `llvm-mingw-20261006-ucrt-x86_64.zip` | `317492c456aa27ee607a5919f1d2d38dcdc1112516a24d0bf4b00d078f52d17a` |
| `cmake-4.4.4-windows-x86_64.zip` | `bace36e94b31c68ab6fa295f26dfa11219e0701cf7c94b0284a7d1cb13dac536` |

## Contributions

The [startup research harness](startup-research.md) adds a fourth CTest suite.
It tests strict audit records and, on Windows, real child/descendant lifetime
control with ordinary test processes. These tests preserve the existing three
regression suites and do not constitute PS4 homebrew execution. The strict
engine build has a separate workflow and retains all release licensing holds.

The fifth suite, `research-kernel-services`, exercises the same bounded
`poll`/`fcntl`/`madvise` implementation used by the research patch, including
argument errors, unsupported operations, descriptor flags, actual timer expiry
and a nondestructive host memory-prefetch call. This suite also runs on Linux;
only a separately recorded strict guest run establishes homebrew startup.

The sixth suite, `ffmpeg-audit-policy`, checks the portable metadata validation
and report filtering used by the [release audit](release-audit.md). It does not
download/link FFmpeg or execute a guest. The separate Windows audit workflow
queries the locked static libraries and verifies the pinned source recipe.

For the isolated shadPS4 build and the selected OpenOrbis homebrew recipe, see
[upstream baseline](upstream-baseline.md). Research scripts use Python 3.12+;
they are separate from the normal runtime build and its Python 3.9+ tests.

Use a working branch and pull request for every change, including administrator
changes. Do not push directly to `main` or merge without owner authorization.
Do not commit game data, firmware, keys or proprietary SDK material. Original
contributions use GPL-2.0-or-later; retain the copyright and SPDX notices and
include the root LICENSE when distributing source. Only submit material you
have the right to license. See [licensing](licensing.md) for third-party review
and binary distribution requirements. No upstream engine is linked into the
original inspector/probe targets.
