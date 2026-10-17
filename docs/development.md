# Development baseline

## Build and run

Requirements: a C++20 compiler, CMake 3.24+, Python 3.9+ for tests. Windows x86-64
is the first target; CI also builds the platform-independent inspector on Linux.
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
  executable mapping, Vulkan and guest execution.
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

## Validation record: 17 October 2026

Built and tested locally on Windows x86-64 using portable LLVM-MinGW
`20261006` (Clang 23.1.3), CMake 4.4.4, MinGW Makefiles and Python 3.12.14.
Warnings are errors. CTest passed both suites: 167 C++ validation checks plus
the CLI contract tests. The generated probe was also inspected in text mode.
Hosted CI also passed the Release build and both suites on Windows with MSVC
and on Linux. Local MinGW and hosted results are separate checks.

The portable archives' SHA-256 hashes matched their GitHub release asset
digests before extraction:

| Archive | SHA-256 |
| --- | --- |
| `llvm-mingw-20261006-ucrt-x86_64.zip` | `317492c456aa27ee607a5919f1d2d38dcdc1112516a24d0bf4b00d078f52d17a` |
| `cmake-4.4.4-windows-x86_64.zip` | `bace36e94b31c68ab6fa295f26dfa11219e0701cf7c94b0284a7d1cb13dac536` |

## Contributions

Use a working branch and pull request for every change, including administrator
changes. Do not push directly to `main` or merge without owner authorization.
Do not commit game data, firmware, keys or proprietary SDK material. The project
license is still pending; no upstream implementation has been imported.
