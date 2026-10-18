# Bounded homebrew startup research

This implements the harness and strict diagnostics selected by
[decision 0002](decisions/0002-g2-engine-boundary.md). The normal inspector and
fixed-probe execution path are unchanged. G2 is complete only after a qualifying
real guest run; process-fixture tests or an engine compile do not establish it.

## Components

The default `hello-world` profile retains the contract described below. The
explicit `--profile service-roundtrip` adds an independent second fixture with
file/thread operations and host-verified output; see
[its acceptance tests and reproduction](homebrew-services.md). Each profile has
its own fixed fixture hashes and expected guest messages. The two-second timing
requirement applies to hello_world, whose source requests that delay.

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
  It creates empty default user homes (1000–1003, each with `savedata`, `trophy`
  and `inputs` directories). At the pinned revision, creating the first home
  otherwise opens a modal migration dialog even without old saves. The engine
  still creates its normal `users.json`; no personal profile or data is copied.
  Output must be a new directory; previous logs or personal modules cannot
  satisfy the test. It captures stdout/stderr, engine logs and structured audit
  events, enforces output limits, requests termination and records the result.
- `research/shadps4/strict-startup.patch` changes the pinned CLI, linker, guest
  TTY logger, descriptor table, kernel filesystem/memory adapters and AAC/build
  integration. The [native AAC replacement](aac-replacement.md) removes the
  separate FDK target from this patched research engine. Original
  upstream SPDX/copyright notices are retained and dated changes are marked.
  The original `startup_audit.h`, `kernel_services.h` and `aac_decoder.h` are installed in the
    research checkout. None is linked into the inspector/probe.

Strict mode is opt-in through `--startup-audit ABSOLUTE_NEW_FILE`. It records
unresolved imports with symbol/NID, library and module information when
available, rejects malformed identities and unsupported relocations, and avoids
generating fallback success stubs. Checks run after initial relocation and
again immediately before main guest entry; failure exits 86. Existing permissive
linker behavior remains available outside audit mode; the new kernel exports
apply to the patched research engine in both modes. The TTY logger emits timestamped guest lines separately
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

The [initial 18 October 2026 local attempt](../research/results/2026-10-18-openorbis-startup.json)
confirmed those three missing exports in the compiled engine and stopped before
guest entry. Its structured trace recorded initial unresolved count 3, and
process-tree cleanup was confirmed. This established the service work below;
the passing result after these changes is recorded under validation.

## Bounded kernel services

The next G2 increment registers those three identities with real, limited
implementations. This is research coverage for the selected fixture, not full
POSIX or PS4 service compatibility. The common implementation is compiled in
the isolated engine and in native policy/host-operation tests.

| Export | Implemented behavior | Explicit limits |
| --- | --- | --- |
| `poll` | Guest 8-byte records and 64-bit count; negative fds ignored; closed/invalid fds report `POLLNVAL` even with no requested events; regular files/directories report normal readiness; known standard loggers report write readiness; count ready entries, reset `revents`, honor zero/finite/negative timeouts. | At most 1024 array entries. Sockets, other devices/equeues, logger reads and priority/band requests return guest `EOPNOTSUPP`. No host descriptor guessing or manufactured socket hangups. |
| `_fcntl` | Validate descriptor under the table lock; `F_GETFD`/`F_SETFD` store per-descriptor `FD_CLOEXEC`; `F_GETFL` reports recorded supported open/std-logger modes. The SysV register bridge consumes an optional integer only for `F_SETFD`. | Engine has no exec operation. Duplication, locks, ownership and `F_SETFL` return `EOPNOTSUPP`; unknown commands/invalid flags return `EINVAL`; unknown effective status modes return `EOPNOTSUPP`; invalid fd returns `EBADF`. |
| `madvise` | Validate 16 KiB alignment, rounding/overflow and every committed CPU-readable guest mapping before host access. `MADV_WILLNEED` calls Windows `PrefetchVirtualMemory` (POSIX host `madvise` on the portable branch), propagating failure. Empty valid ranges require no operation. | Other nonempty advice returns `EOPNOTSUPP`; invalid arguments return `EINVAL`, unmapped/inaccessible ranges `ENOMEM`. No discard/reset operation is substituted for BSD `MADV_DONTNEED`. |

`poll` and `_fcntl` inspect state while holding the descriptor table lock, so
their callbacks cannot retain a pointer across descriptor deletion. They do
not repair all existing upstream descriptor/I/O concurrency behavior. Memory
query and host prefetch are not atomic against another guest thread unmapping
the range; prefetch is nondestructive and host failures remain failures. Raw
guest pointers retain the upstream process trust model and may crash the
research child; Job Object containment is not a memory security boundary.

The selected SDK headers define these ABI values, including its generic
`F_DUPFD_CLOEXEC=1030` alongside FreeBSD's 17. OpenOrbis's
[C library startup](https://github.com/OpenOrbis/musl/blob/master/src/env/__libc_start_main.c)
and [fcntl wrapper](https://github.com/OpenOrbis/musl/blob/master/src/fcntl/fcntl.c)
explain the import surface. The
[FreeBSD madvise contract](https://man.freebsd.org/cgi/man.cgi?query=madvise&sektion=2&manpath=FreeBSD+9.0-RELEASE)
preserves contents for `DONTNEED`, unlike destructive host discard behavior;
the supported prefetch uses the documented
[Windows operation](https://learn.microsoft.com/en-us/windows/win32/api/memoryapi/nf-memoryapi-prefetchvirtualmemory).
These are implementation references, not claims of console hardware validation.

Binding the other 42 imports still does not establish complete service behavior.
Loader warnings for PT_INTERP and SCE attribute tags remain unreviewed beyond
this fixture's successful execution. No expected message is injected by these
services or the harness.

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
pins are verified, the patch is applied with Git index checks, all three original
headers are hashed/staged and the resulting tree must match the manifest before
and after compilation. Native AAC/adapter tests and active-graph/link-map checks
are required; old FDK builds or missing AAC success evidence are rejected.
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

Failed launches also retain the supervisor's exit/cleanup report and a hashed
audit summary with every recorded unresolved identity. A later failure can
still record that guest entry occurred, but only if the trace prefix through
entry passes the strict configuration/import checks. This observation never
changes a failed attempt into a G2 pass. Malformed or truncated postmortem
evidence is reported separately from the original launch failure.

## Validation and limits

The startup contract suite tests the actual C++ audit writer's JSON escaping,
missing-import entry rejection and duplicate-entry rejection. Python tests
reject reordered/too-fast/forged/truncated evidence, unpatched build reports and
missing prerequisites. Windows tests launch ordinary process fixtures to verify
timeout/explicit-stop/root-exit/crash behavior, descendant cleanup, Unicode
paths and argument quoting. Linux runs the portable audit/evidence checks;
Windows Job Object tests are explicitly skipped there. These are transport and
policy tests, never PS4 execution evidence.

Local Windows validation passed all five CTest suites, including 15 startup
tests and 72 kernel-service checks. The service suite covers negative/invalid
fds, duplicate entries and event counting, resets, zero/finite/negative timeout
branches, actual timer expiry, independent descriptor flags, unsupported
operations, memory holes/alignment/rounding/overflow and nondestructive host
prefetch. Input tests reject a missing/stale/tampered service header hash.
These tests do not establish full PS4 ABI or syscall conformance. The 72 service
checks also pass with the local MSVC ABI compiler mode.
The strict engine also built locally and passed CLI help, with the exact
reviewed source tree and 54 recursive pins checked before and after compilation.
Full build reports, raw traces, toolchain details and host diagnostics remain
local. The public result contains only input identifiers and test outcomes.

The initial 30-second run timed out at fresh-profile initialization and cleaned
up successfully. Source inspection identified the unconditional migration
dialog; the empty-home setup above allowed the next run to reach module loading
and import resolution. Host graphics initialization succeeded; this is not
guest rendering. The confirmed missing imports stopped the attempt before guest
entry. After the bounded service implementation, strict execution reached guest
entry with zero unresolved imports and emitted both expected messages. Two
fresh-profile runs of the final exact research tree passed, with intervals
2,000,773 and 2,000,202 microseconds and confirmed requested process-tree
cleanup. The [public result](../research/results/2026-10-18-openorbis-services.json)
records only source/fixture identifiers and test outcomes. This is a passing
**G2 result for the selected fixture**.
It does not establish that every newly bound service or every supported branch
was exercised by the homebrew itself; those have separate host/policy tests.
The strict CI job checks compilation and CLI help;
it does not launch a guest.

The [licensing audit](decisions/0002-g2-engine-boundary.md#focused-licensing-findings)
release holds remain open for complete source/notice/dependency compliance.
The [AAC follow-up](aac-replacement.md) removes separate FDK linkage only from
the new verified patched engine; the unmodified baseline/older builds retain it. The
research checkout/build is not a distributable engine bundle. No firmware,
proprietary SDK, game, sample binary or upstream engine binary is committed.
