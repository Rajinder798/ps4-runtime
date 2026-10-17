# Bounded homebrew startup research

This implements the harness and strict diagnostics selected by
[decision 0002](decisions/0002-g2-engine-boundary.md). The normal inspector and
fixed-probe execution path are unchanged. G2 is complete only after a qualifying
real guest run; process-fixture tests or an engine compile do not establish it.

## Components

- `ps4-startup-supervisor.exe` creates the Windows child suspended with an
  explicit inherited-stream handle list and an atomic Job Object assignment.
  The job uses kill-on-close, has no breakaway permission, and owns descendants.
  The helper resumes the child after creation succeeds, enforces a timeout,
  terminates the job and confirms zero active processes. Parent/helper failure
  does not intentionally leave the engine running. A Job Object is not a guest
  security sandbox.
- `tools/run_homebrew_startup.py` verifies the engine against its strict build
  report and locked patch/header hashes, verifies the selected fixture hash,
  records Vulkan diagnostics and starts with a fresh portable `user/` directory.
  Output must be a new directory; previous logs or personal modules cannot
  satisfy the test. It captures stdout/stderr, engine logs and structured audit
  events, enforces output limits, requests termination and records the result.
- `research/shadps4/strict-startup.patch` changes three pinned upstream files:
  the CLI, linker and guest TTY logger. Original upstream SPDX/copyright notices
  are retained and dated changes are marked. The original `startup_audit.h` is
  installed in the research checkout. None is linked into the inspector/probe.

Strict mode is opt-in through `--startup-audit ABSOLUTE_NEW_FILE`. It records
unresolved imports with symbol/NID, library and module information when
available, rejects malformed identities and unsupported relocations, and avoids
generating fallback success stubs. Checks run after initial relocation and
again immediately before main guest entry; failure exits 86. Non-audit upstream
behavior is preserved. The TTY logger emits timestamped guest lines separately
from host log text.

The runner requires configured strict mode, a zero-unresolved entry check,
one guest-entry event and the two exact guest messages in order. Their engine
timestamps must be at least 1.9 seconds apart, allowing a small tolerance around
the sample's two-second sleep. Host stdout containing matching words alone
cannot pass. Later unresolved events, invalid/truncated traces, crashes, early
exits, timeouts, excessive output or unconfirmed cleanup fail. The fixture's
final infinite loop is stopped deliberately after observation.

## Converted fixture import review

Static inspection of the selected `.oelf` (SHA-256
`c5329274bc6cc356f2926d9ec89403e35907ec5f540ecd2e7b7d41ae552be670`)
found 45 undefined global function symbols in its SCE symbol table. They use
`#B#B` identities, library `libkernel` version 1 and module `libkernel` version
1.1. This checks the converted metadata, rather than assuming its SCE identities
from the original ELF's human-readable names.

A literal `LIB_FUNCTION` source search at the pinned engine revision found
registration candidates for 42 of those identities. The following three had no
literal match; names were cross-referenced with the pinned AeroLib table:

| Import identity | Name |
| --- | --- |
| `ku7D4q1Y9PI#B#B` | `poll` |
| `t0fXUzq61Z4#B#B` | `_fcntl` |
| `Jahsnh4KKkg#B#B` | `madvise` |

These are static diagnostic leads, not results from the compiled registry or
proof of behavior for the other 42 functions. Macro-generated/conditional
registrations and actual call semantics still require runtime validation. The
first strict run must report its real resolver results; do not add success
stubs merely to make these references disappear.

## Build and run

Research builds require Python 3.12+. Normal runtime tests support Python 3.9+.
Use Windows x86-64, a CPU meeting the pinned engine's x86-64-v3 baseline and a
compatible Vulkan GPU/driver. `vulkaninfo --summary` must be available to capture
the graphics host. The current engine opens SDL/Vulkan even for this sample.

```powershell
cmake -S . -B build/native -DCMAKE_BUILD_TYPE=Release
cmake --build build/native --config Release
ctest --test-dir build/native -C Release --output-on-failure
```

From the x64 Visual Studio environment with clang-cl, Ninja and CMake available:

```powershell
python tools/build_strict_upstream.py --jobs 4
```

This creates separate `build/upstream/shadps4-strict` source and
`build/upstream/windows-x64-strict` build directories. It refuses to reset a
dirty/existing patched checkout; use a fresh research checkout for a new build
attempt. The original reference checkout is untouched. Input hashes and source
pins are verified, the patch is applied with Git index checks, the audit header
is staged and the resulting tree is recorded and checked after compilation.
`build/upstream/strict-evidence/strict-build.json` records the engine hash, tools
and CLI-help result. No engine binary is uploaded by the strict build CI job.

Build the selected homebrew using the existing
[verified recipe](upstream-baseline.md#selected-homebrew-openorbis-hello_world),
then run (Visual Studio output paths shown):

```powershell
python tools/run_homebrew_startup.py --engine build/upstream/windows-x64-strict/shadPS4.exe --engine-report build/upstream/strict-evidence/strict-build.json --fixture build/homebrew/hello-world/hello_world.oelf --supervisor build/native/Release/ps4-startup-supervisor.exe --output build/startup/run-001 --timeout 30
```

For a single-configuration MinGW build, the supervisor is directly under
`build/native/`. Use a new `--output` path for every attempt. Engine CLI handling
of non-ASCII application paths remains unvalidated; supervisor argument
transport is tested separately.

Read `startup-result.json` and session logs. Exit 0 requires `g2_passed: true`,
actual guest-entry/marker evidence and requested termination with confirmed
tree cleanup. Failure exits 1; invalid arguments exit 2. A prerequisite failure
records no guest execution. `engine_launch_attempted` and
`guest_entry_observed` distinguish an attempt from evidence of reaching guest
code. Missing imports are failures to resolve, not permission to loosen the
probe guard or inject expected messages.

## Validation and limits

The startup contract suite tests the actual C++ audit writer's JSON escaping,
missing-import entry rejection and duplicate-entry rejection. Python tests
reject reordered/too-fast/forged/truncated evidence, unpatched build reports and
missing prerequisites. Windows tests launch ordinary process fixtures to verify
timeout/explicit-stop/root-exit/crash behavior, descendant cleanup, Unicode
paths and argument quoting. Linux runs the portable audit/evidence checks;
Windows Job Object tests are explicitly skipped there. These are transport and
policy tests, never PS4 execution evidence.

Local Windows validation passed all four CTest suites. Vulkan diagnostics found
Intel UHD and NVIDIA RTX 3050 Laptop devices. A compatible engine build and MSVC
development environment were not available locally during implementation, so no
real homebrew startup result is claimed. The strict CI job checks the patched
engine's full compile and CLI help; it does not launch a guest.

The [licensing audit](decisions/0002-g2-engine-boundary.md#focused-licensing-findings)
release holds remain open, including FDK AAC and FFmpeg/source compliance. The
research checkout/build is not a distributable engine bundle. No firmware,
proprietary SDK, game, sample binary or upstream engine binary is committed.
