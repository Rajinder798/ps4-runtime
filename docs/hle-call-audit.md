# HLE call audit (runtime import entry)

[Static import coverage](roadmap.md#3-bring-up-executable-loading) predicts which
declared imports the research engine can resolve. It cannot say which of them a
program actually calls. This diagnostic answers that for a real strict guest run:
which declared imports were entered through their HLE wrapper, and when.

This is Track B step 2 ("record imports and service calls needed by selected
permitted tests"). It is a diagnostic prerequisite. It is not new G2/G4 progress,
and it does not test whether any implementation is correct.

## Components

- `research/shadps4/hle-call-audit.patch` and `hle_call_audit.h` are layered on
  the unchanged strict research patch. `HostCallWrapperImpl<func>::wrap`, which
  every `LIB_FUNCTION` registration already goes through, gains a per-wrapper
  atomic flag. Its first entry calls `HleCallAuditFirstCall`. `LinkSymbolImpl`
  records each function registration's wrapper address and identity (NID,
  library, module). After `InitHLELibs`, one `hle_call_audit` event in the
  existing strict audit records how many addresses and identities were
  registered.
- On first entry, one `hle_first_call` event lists every identity registered at
  that wrapper, sorted and unique. The wrapper cannot tell which alias the guest
  imported, so aliases are listed together. An empty list is a host-call wrapper
  that no registration names, such as the pthread start wrapper. Locks are never
  nested. A write failure terminates the process instead of unwinding into guest
  frames.
- `config/hle-call-audit.json` pins the strict inputs it builds on, the patch
  and header hashes, and the resulting source tree. It also lists the
  independent oracles for each fixture.
- `tools/build_hle_call_audit.py` builds the variant in its own checkout, build
  and evidence directories under `build/upstream/*-hle-call-audit*`. The strict
  engine and its evidence are never touched. The variant does not rerun the
  strict build's AAC and host-exception tests, and its report says so.
- `tools/run_hle_call_audit.py` runs `hello-world` or `service-roundtrip` with the
  existing supervisor, fresh session and strict-audit rules. It then requires
  each oracle: a guest observation established independently must have gone
  through the HLE import it depends on. For example, greeting output must enter
  `_write` or `_writev` before the guest-output event, and the host-verified
  `service-roundtrip` result file must enter `sceKernelWrite` before `PASS`.
  "Before" is the audit's event order, not its timestamps. A first call and the
  output it produces can share one microsecond, and each marker counts from its
  first occurrence.
- `tools/hle_call_audit.py report` maps an audit to the fixture's declared
  imports (`ps4-runtime imports --json`).

The strict runner rejects the variant's extra events as unknown, and the variant
runner rejects an audit with no readiness event. So neither engine can be
substituted for the other, and a strict audit can never be read as "nothing was
entered".

## Host-only tests

The `hle-call-audit-contract` CTest suite compiles the real header into
`tests/hle_call_audit_driver.cpp`. It checks:

- the event output, including aliases, duplicates, an unregistered wrapper and
  JSON escaping;
- that an unconfigured audit writes nothing;
- that the strict evaluator rejects variant audits;
- report classification: entered, not entered, object, undeclared and
  unattributed;
- oracle ordering;
- malformed and misplaced events;
- that the committed contract matches the committed patch and header, and that
  build evidence is verified.

It runs without an engine or guest.

## Result (local Windows, 1 November 2026)

Host: Windows 11 (10.0.26220), Intel family 6 model 141, NVIDIA GeForce RTX 3050
Laptop GPU (driver 617.42) and Intel UHD Graphics. Variant tree `b453535a…`,
executable `c20f1d30…`. Full data, including hashes, is in
[the result record](../research/results/2026-11-01-hle-call-audit.json).

| Run | Outcome | Imports entered | Oracles |
|---|---|---:|---|
| hello-world-001 | **Failed**: timeout. Only the `configured` event, empty engine logs, forced cleanup verified | — | — |
| hello-world-002 (debug log) | Passed | 7 of 45 | 2/2 |
| hello-world-003, 004 | Passed | 7 of 45 | 2/2 |
| service-roundtrip-001, 002 | Passed, guest result file host-verified | 9 of 18 | 7/7 |

- The first attempt was the first launch of the newly built executable. It did
  not reproduce in three later runs, one with debug logging and two with default
  settings. Its cause is unknown, and it is retained as a failed attempt.
- Entered sets were identical by NID across every passing repeat.
- hello-world entered `__error`, `mmap`, `_write`, `sceKernelUsleep`,
  `pthread_mutex_lock`, `pthread_mutex_unlock` and `pthread_cond_broadcast`. It
  waits through `sceKernelUsleep`, not `nanosleep`.
- hello-world never entered `poll`, `_fcntl` or `madvise`. These are the three
  imports the strict research patch registers so that strict resolution passes.
  They are required for startup to be accepted, not reached in these runs.
- service-roundtrip entered `_write`, `sceKernelOpen`, `sceKernelRead`,
  `sceKernelWrite`, `sceKernelLseek`, `sceKernelClose`, `sceKernelUsleep`,
  `scePthreadCreate` and `scePthreadJoin`. Its libc-level `_open`, `close`,
  `lseek`, `poll`, `_fcntl`, `_ioctl`, `_writev`, `__error` and `_exit` were not
  entered.
- No identity outside the declared imports was entered. Every run entered one
  unregistered host-call wrapper before guest entry.

## Limits

- Granularity is one wrapper. An import counts as entered if any alias sharing
  its wrapper was entered.
- One bounded run per fixture. "Not entered" means not reached in that run, not
  "never needed".
- `LIB_OBJ` imports are data and cannot be observed. Symbols an engine provides
  outside `LIB_FUNCTION` are not recorded.
- Entering a function does not show that it is implemented, correct or
  complete.
- The variant engine is local research only. No engine binary is distributed.

## Reproduce (Windows x86-64)

```powershell
. .\build\tools\enter-research-tools.ps1   # or a Visual Studio x64 developer shell
python tools/build_hle_call_audit.py --jobs 8
.\build\native\ps4-runtime.exe imports build/homebrew/hello-world/hello_world.oelf --json > build/hw-imports.json
python tools/run_hle_call_audit.py --engine build/upstream/windows-x64-hle-call-audit/shadPS4.exe `
  --engine-report build/upstream/hle-call-audit-evidence/hle-call-audit-build.json `
  --fixture build/homebrew/hello-world/hello_world.oelf --imports build/hw-imports.json `
  --supervisor build/native/ps4-startup-supervisor.exe --output build/hle-call-audit/hello-world-001 `
  --source build/upstream/shadps4-hle-call-audit
```

Use `--profile service-roundtrip` with `service_roundtrip.oelf` and its imports
for the second fixture.

With the repository's portable toolchain (`build/tools`), whose `clang-cl` has no
resource directory of its own, the build matches the local strict build in three
ways. `CFLAGS`/`CXXFLAGS` set `-resource-dir` to the llvm-mingw clang 23 headers.
`LIB` includes `build/tools/llvm-rt-build/lib/windows` for
`clang_rt.builtins-x86_64.lib`. And `--define HAVE_ENDIAN_H=OFF` stops libressl
using clang 23's builtin `endian.h`, which lacks `be32toh` and related functions.
The build report records all three. A Visual Studio clang-cl installation should
not need them.
