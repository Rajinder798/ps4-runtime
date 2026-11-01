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

## Import inventory contract

`ps4-runtime imports <file> [--json]` first applies the full inspection contract,
then reads the file's declared SCE import metadata. It requires exactly one
`PT_DYNAMIC` and one `PT_SCE_DYNLIBDATA` segment and reads `DT_NEEDED`,
`DT_SCE_NEEDED_MODULE`, `DT_SCE_IMPORT_LIB` and the SCE string/symbol tables,
whose offsets are relative to `PT_SCE_DYNLIBDATA`. Tag values and bit layouts
follow the pinned shadPS4 revision `e6c79a5f` (`src/core/loader/elf.h`,
`src/core/module.h`); the parser is original code, and no upstream source is
copied or linked.

- Reported: needed files, modules (ID, encoded ID, major/minor version),
  libraries (ID, encoded ID, version) and each undefined global/weak symbol
  named `NID#library#module`, with its type and binding, in symbol-table order.
  Undefined global/weak names without that form are listed separately as
  `other_undefined`. Defined (exported) and local symbols are counted only.
- Rejected: missing or duplicate dynamic segments, a missing `DT_NULL`, duplicate
  singular table tags, missing or out-of-range string/symbol tables, symbol
  entries other than 24 bytes, out-of-range or unterminated names, names that
  are not printable ASCII, malformed NIDs, duplicate module/library IDs and
  imports naming an undeclared library or module ID.
- Limits of the inspector, not PS4 limits: `PT_DYNAMIC` at most 1 MiB and each
  table at most 16 MiB. Tables are read with bounded seeks.
- Not performed: symbol resolution, relocation processing, export inventory,
  NID-to-name lookup, TLS, mapping or execution. JSON always contains
  `resolution_performed: false` and `execution_supported: false`. A listed
  import says what the file asks for, not that any runtime implements it.

The `inspect` JSON is unchanged. The `sce-import-inventory` CTest suite checks
the CLI against an original generated fixture (`tools/make_sce_imports.py`),
including 1-3 character ID encoding and 22 rejection cases (two
exercise the size limits). The NID derivation
used by the fixture and the cross-check below is anchored to the widely
published NIDs of `printf` and `sceKernelUsleep`. The hosted homebrew workflow
additionally runs `imports` on each real converted OpenOrbis `.oelf`, uploads
`sce-imports.json`, and fails unless the declared NIDs exactly match, in content and count,
those derived from the pre-conversion ELF's undefined dynamic symbols. That is an
independent check of converted metadata, not guest execution.

## Relocation inventory contract

`ps4-runtime relocations <file> [--json]` reads the same validated dynamic
metadata as `imports` (the same segment, tag, string and symbol-table checks
apply), then lists every entry of the SCE `DT_SCE_RELA` and `DT_SCE_JMPREL`
tables in table order: target offset, type, symbol index and name, signed
addend, and the containing segment.

- Either table may be absent, but each must declare both its offset and size.
  Entries must be 24 bytes (`DT_SCE_RELAENT`, if present, must be 24), and
  `DT_SCE_PLTREL`, if present, must name `DT_RELA` (7).
- Symbol indices must lie inside the SCE symbol table. Each target, as a guest
  address relative to the module base, must fit entirely inside one `PT_LOAD`
  or `PT_SCE_RELRO` memory range: 8 bytes for 64-bit types, 4 for
  `R_X86_64_PC32`/`32`/`32S`. `R_X86_64_NONE` has no target, and an unrecognised
  type is reported as `unknown` and only needs to start inside a segment.
  Writable segments are not required, because PS4 modules may use text
  relocations.
- Not performed: applying relocations, resolving symbols, TLS module IDs, or
  mapping/execution. JSON always contains `relocation_performed: false` and
  `execution_supported: false`.

The `sce-relocation-inventory` CTest suite covers the generated fixture's
`RELATIVE`, `GLOB_DAT`, `R_X86_64_64`, `DTPMOD64` and `JUMP_SLOT` entries, four
accepted edge cases and 13 rejection cases. The hosted homebrew workflow uploads
`sce-relocations.json` for each converted `.oelf` and fails unless the entries
match, as a multiset of table, offset, type, symbol NID and addend, the
pre-conversion ELF's `.rela.dyn`/`.rela.plt` sections. Those are read by
`tools/elf_relocations.py`, an independent standard-ELF reader that was checked
to agree exactly with GNU `readelf -rW` on a locally built shared object.

## Startup metadata contract

`ps4-runtime startup <file> [--json]` reports the module metadata a loader reads
before entry, after the full inspection contract:

- **TLS template** (`PT_TLS`, at most one): address, initialization-image size
  (`p_filesz`), total size, alignment, and the aligned size rounded as the pinned
  shadPS4 `GetAlignedSize` does. A nonempty initialization image must be
  file-backed by one `PT_LOAD`/`PT_SCE_RELRO` segment. Overflow while rounding is
  rejected.
- **TLS relocations:** counts of `DTPMOD64`, `DTPOFF64` and `TPOFF64`, reported
  only when SCE dynamic tables are present, using the full relocation contract.
  TLS relocations without a `PT_TLS` segment are rejected.
- **Process parameters** (`PT_SCE_PROCPARAM`, at most one): the 24-byte header
  (size, `ORBI` magic, entry count, SDK version) and address. The segment's bytes
  must be exactly those a loadable segment maps at the same address, and the size
  field must be at least 24 and at most the segment size. Pointer fields are not
  interpreted, because they become valid only after relocation.
- Not performed: TLS block allocation, module-ID or offset assignment, applying
  relocations, or execution (`tls_allocated: false`, `execution_supported: false`).

The `sce-startup-metadata` CTest suite checks the generated fixture, four
accepted edge cases (file-backed image, zero and larger alignment, minimum
parameter size) and 12 rejection cases. For each converted homebrew `.oelf`, the
hosted homebrew workflow uploads `sce-startup.json`. It fails unless:

- the TLS address, initialization size, total size and TLS relocation counts
  equal those in the pre-conversion ELF;
- the TLS alignment is the same or stricter (a power of two that is a multiple of
  the original). The pinned `create-fself` raises it from 8 to 32 in every
  current fixture, and the evidence records `tls_alignment_raised`;
- valid process parameters are present.

The pre-conversion fixtures declare no `PT_SCE_PROCPARAM`, so the process
parameters' address and contents have no independent oracle there; they are
checked only by the inspector's own consistency rules. `tools/elf_relocations.py` reads those program
headers. It agreed exactly with GNU `readelf -lW` on all 12 headers of a locally
built library with thread-local variables.

## Static engine import coverage

`tools/engine_coverage.py` predicts which of a program's declared imports the
research engine has no HLE registration for, before anything is run:

```
python tools/engine_coverage.py prepare --destination build/engine-coverage/patched
python tools/engine_coverage.py prepare --destination build/engine-coverage/unpatched --unpatched
ps4-runtime imports program.oelf --json > imports.json
python tools/engine_coverage.py report --source build/engine-coverage/patched --imports imports.json
```

- `prepare` fetches the pinned shadPS4 revision with git. Without `--unpatched`
  it applies the reviewed research patch and headers and requires the exact
  `expected_patched_tree` from `config/startup-research.json`, through the same
  `research_contract.verify` used by the strict build. It refuses a non-empty
  destination. Nothing is built.
- `report` reads every `LIB_FUNCTION`/`LIB_OBJ` registration under `src/` and
  fails if any macro use cannot be parsed. An import counts as registered only
  when its NID, library name and module name all match, which is the pinned
  linker's own rule: `SymbolResolver::operator==` ignores versions and symbol
  type. Missing NIDs are named from the pinned AeroLib table where it knows them.
- **Limits:** this is a source-text prediction, not a resolver run.
  Registrations behind conditional compilation or runtime settings count
  wherever they appear, firmware (LLE) modules are not modelled, and a
  registered function may still be a stub or incomplete. Exported symbols of
  other loaded guest modules are not considered.

The `engine-import-coverage` CTest suite uses an original miniature source tree
and the generated fixture. The hosted homebrew workflow prepares both trees for
every fixture, uploads `engine-coverage.json`, and fails unless:

- the patched engine covers every import. Every guest runner uses the strict
  startup audit, which stops before entry on any unresolved import, and those
  runs reached entry;
- for hello-world, the unpatched prediction equals the three unresolved
  identities (`poll`, `_fcntl`, `madvise`) recorded by the real 18 October 2026
  strict run in `research/results/2026-10-18-openorbis-startup.json`.

A fixture listed in `FIXTURES_WITHOUT_GUEST_RUNS` (currently `save-roundtrip`) has
no guest oracle yet. Its prediction is uploaded but not asserted.

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

The seventh/eighth suites add portable AAC framing/range checks and link-evidence
rejection tests. Actual AAC decoding and patched AJM adapter tests run separately
in the Windows strict build; see [AAC replacement](aac-replacement.md). They
exercise original synthetic tones, not guest audio or commercial-game media.

The ninth suite, `ffmpeg-source-kit-policy`, exercises archive safety, real
ordered Git patch application, locked-input verification, forged-manifest
rejection and deterministic packing using original tiny fixtures. The separate
[source-kit workflow](ffmpeg-source-kit.md) reconstructs the real pinned source
on Windows/Linux; neither operation compiles FFmpeg or runs a guest.

The expanded startup suite contains 18 tests, including independent
[second-fixture](homebrew-services.md) profile/hash checks, isolated staging,
guest evidence ordering and missing/corrupt output rejection. Its opt-in real
guest acceptance script exercises two random-input successes and two guest
input failures outside CTest. Hosted homebrew CI builds both fixtures and checks
the second fixture's locked source/converted ELF hashes without executing it.

For the isolated shadPS4 build and the selected OpenOrbis homebrew recipe, see
[upstream baseline](upstream-baseline.md). Research scripts use Python 3.12+;
they are separate from the normal runtime build and its Python 3.9+ tests.

The tenth suite, `launch-contract`, checks the versioned
[local launch interface](launch-contract.md), including configuration persistence,
failed update preservation, unchanged-input enforcement, session collisions and
real CLI JSON/text/usage behavior. Its execution callback tests are host policy
tests; `tests/launch_guest_tests.py` separately runs both real homebrew fixtures
twice through the registered CLI and retains actual guest evidence.

The eleventh suite, `shortcut-contract`, adds portable shortcut publication/error
policy and real Windows COM metadata tests. `ps4-shortcut-helper` builds only on
Windows. The separate [shortcut acceptance script](shortcuts.md) invokes actual
generated links through Windows Shell and checks real guest results; the native
COM tests alone establish only stored metadata and transport behavior.

The twelfth suite, `settings-contract`, covers the
[versioned preference store](settings.md), scope inheritance/reset, atomic updates,
real OS writer locks and launch snapshot/rejection behavior. Its separate real
guest acceptance script verifies that saved log levels change actual engine
session diagnostics while strict guest behavior and existing shortcuts continue
to work. The engine patch/fixture hashes and fixed-probe restrictions are unchanged.

The thirteenth suite, `settings-ui-contract`, tests the separate optional
[Settings window](settings.md#optional-windows-settings-window). Windows executes
five real Tk control/backend tests plus a portable help test. A Windows Python
installation with working Tcl/Tk is required; missing Tk/display fails those
Windows tests. Linux explicitly skips the five Windows window tests and runs the
help test without importing Tk. The opt-in settings guest script accepts
`--settings-ui` to make preference changes through actual window controls before
verifying six real guest sessions. Hosted UI tests establish host UI/persistence
behavior, not guest execution or manual accessibility/usability certification.

The fourteenth suite, `videoout-evidence-contract`, now contains ten portable tests
for the [VideoOut research evidence](videoout-research.md) oracle, PNG filters and
bounds, corruption/stale-image rejection, strict phase ordering and prerequisite
failure. The startup suite now contains 19 tests, adding a real Windows supervisor
ownership-callback/foreign-window rejection check and fixed VideoOut source/ELF
binding. These host tests do not establish rendering. The opt-in
`tests/videoout_guest_tests.py` separately checks four actual VideoOut guest cases
(two graphics successes/two palette failures) and both earlier guest regressions.
The homebrew workflow builds reviewed applications; its build evidence
does not establish guest execution. The pinned engine/patch remain unchanged.

The [pad increment](pad-research.md) adds observation-file/connected-state,
press/release ordering, reviewed-key and input-option rejection tests to that
suite. The startup suite also binds its fourth fixture to reviewed source/ELF
hashes. `tests/pad_guest_tests.py` separately runs two real keyboard-to-ScePad
successes, absent/wrong-button failures and all three earlier guest regressions.
The homebrew workflow now builds all four fixtures. This does not test physical
controllers or remove the pinned initialization-stub diagnostics.

The fifteenth suite, `audio-evidence-contract`, adds six portable signal/format,
channel/order/silence rejection and prerequisite tests for the
[AudioOut disk-sink increment](audio-research.md). The startup suite now has 20
tests, adding Windows child-environment isolation and the fifth fixed-fixture
binding. The opt-in `tests/audio_guest_tests.py` separately runs two actual guest
sink successes, actual silent/swapped output rejections and all four earlier
guest regressions. Hosted homebrew CI builds all five fixtures. These sink tests
do not establish hardware playback or guest codec/AJM decoding.

The [window-close increment](window-shutdown.md) expands the startup suite to 25
tests, including actual owned Win32 window close, ignored-close fallback and
orphan cleanup. The additive supervisor report distinguishes normal zero/empty
exit from forced termination. The opt-in `tests/shutdown_guest_tests.py` checks
two real pad/graphics closes, two AudioOut disk-sink closes and two absent host
request negatives. These remain separate fixtures, not combined interactive G4
or natural guest exit. Existing runner termination defaults are preserved.

The [combined fixture](interactive-research.md) extends the existing 15 suites:
seven audio tests cover the distinct one-pair interaction signal without loosening
the earlier two-pair oracle; 12 video tests include combined trace/option rejection;
the 25 startup tests also bind the sixth fixed source/ELF contract. Its opt-in
`tests/interactive_guest_tests.py` runs six real combined positive/negative cases
and all five earlier fixtures. The homebrew workflow builds all six fixtures;
it uploads build/symbol metadata, not fixture or audio binaries.

The sixteenth suite, `windows-render-capture-contract`, has three portable
[Windows render capture](windows-audio-research.md) policy/environment/CLI tests
and two actual Windows native helper argument/ownership rejection tests. Linux
explicitly skips the two native tests. CI opens no audio device. The opt-in
`tests/windows_audio_guest_tests.py` separately checks real Windows-rendered
guest PCM twice, silent/swapped rejection, capture cleanup on input abort and
the earlier 11-case six-fixture disk matrix. It does not establish acoustic
speaker/headphone output or Windows 10 render support.

The seventeenth suite, `audio-volume-contract`, adds four portable generated-PCM
and CLI rejection tests. The opt-in `tests/audio_volume_guest_tests.py` checks
[actual gain/mute](audio-volume-research.md) on both backends plus all earlier
Windows/disk guest cases. Hosted tests do not open an audio device or run guests.

The [registered AV self-test](av-self-test-launch.md) extends the same 17 suites:
`launch-contract` has 13 portable tests including four new AV contract tests;
`settings-ui-contract` has seven tests including the new Windows scope check.
The opt-in `tests/av_launch_guest_tests.py` checks nine actual registered launches,
three real Shell activations, UI-backed diagnostic settings and tamper rejection.
The startup suite has 26 tests, including real background no-console/pipe checks.

The [small-buffer Windows audio follow-up](small-buffer-audio.md) adds a bounded
native wait diagnostic and opt-in old/new engine acceptance matrices, including
an owned-window minimized comparison. The
audio evidence suite has eight host tests, including preservation of inherited
environment and the child-local SDL timer hint. Actual guest PCM, Windows render
and registered launch results remain separate from these host checks; the
original 256-frame fixture and signal thresholds are unchanged.

The [persistent AV volume increment](av-volume-settings.md) extends the same 17
suites: 13 settings policy/CLI tests and eight Settings UI tests (including help),
plus required volume evidence in AV dispatch. Its new opt-in guest matrix checks
nine actual volume-aware registered launches. Prior AV launches, legacy Settings
UI and the full audio matrix are separate regressions; generated host PCM is
never substituted for captured guest output.

The [Windows host exception boundary](host-exception-boundary.md) adds native
real-throw/catch, uncaught-termination and access-violation tests to the separate
strict-engine build. The opt-in minimized comparison keeps both engines' PCM
oracles and guest/normal-close requirements unchanged, while checking the exact
host-thread diagnostic path. These native tests do not execute a PS4 fault.

The eighteenth suite, `live-av-evidence-contract`, adds portable rejection of
out-of-order live samples, corrupt guest records, stale sequence-bound images,
insufficient/reversed-channel PCM and invalid CLI output/budget requests. The
opt-in [live AV matrix](live-av-research.md) separately runs the actual continuously
active guest with external owned-window input and normal close, including close
during a tone. Host-generated data never establishes guest execution. Existing
finite-fixture completion and registered-launch semantics remain unchanged.

The nineteenth suite, `live-session-contract`, covers ordinary session CLI guards
and truthful failed-session evidence. The expanded Windows startup suite checks
user-closed supervision, invalid owner handles and launcher-death cleanup of a
child/grandchild tree. The separate [live-session guest matrix](live-session.md)
tests normal no-input close, guest responsiveness after the old two-minute limit,
launcher death and explicit stop. External qualification remains separate from
the ordinary runner's `closed` status.

The registered live increment extends the same 19 host suites: 15 launch policy,
14 settings, nine Settings UI and six live evidence tests. It keeps old schema
contracts, uses schema 3 explicitly for live registration/overrides, tests snapshot
and downgrade protection, and independently rejects wrong saved volume/cycle
signals. The opt-in [live launch matrix](registered-live-launch.md) separately
checks actual CLI/Shell launches and engine output. Future-format negative
fixtures now use schema 4 because schema 3 is intentionally supported.

Use a working branch and pull request for every change, including administrator
changes. Do not push directly to `main` or merge without owner authorization.
Do not commit game data, firmware, keys or proprietary SDK material. Original
contributions use GPL-2.0-or-later; retain the copyright and SPDX notices and
include the root LICENSE when distributing source. Only submit material you
have the right to license. See [licensing](licensing.md) for third-party review
and binary distribution requirements. No upstream engine is linked into the
original inspector/probe targets.

The twentieth suite, `muted-endpoint-contract`, rejects incomplete or changed
endpoint observations and checks Windows observer argument guards without
accessing an audio device. The opt-in [muted live-launch matrix](muted-live-launch.md)
separately verifies actual ordinary CLI/Shell launches with Windows remaining
muted and application preferences independent. It provides no PCM qualification.

The same 20 suites add [live Cross letter](live-cross-key.md) preference coverage:
explicit schema-4 upgrades, non-downgrade/reset, capability filtering, failed
upgrades, per-launch snapshots, real Tk controls and a pinned input template
whose other bindings are preserved. Settings future-schema rejection uses
version 5; registration schema 4 remains unsupported. The opt-in N/G guest
matrix is separate from these host tests and requires muted endpoint observation.

The bounded `tests/input_focus_guest_tests.py` comparison separately investigates
held N/G keys versus minimizing only the owned SDL window. Its host oracle
rejects unsolicited control release and missing focus-loss ordering. Read-only
window state polling in both guest drivers records sampling limits and never
changes focus, logs global keys or controls Windows audio. See the
[focus investigation](live-cross-key.md#bounded-focus-loss-investigation) for
the retained failed control, controlled results and unresolved older failures.

The twenty-first suite, `physical-controller-evidence-contract`, rejects
incomplete, virtual/wireless, short-held, mismatched or disconnected physical
test records and distinguishes reported guest disconnect failure from graceful
support. Its generated data is host-only. The opt-in
[USB DualSense workflow](dualsense-verification.md) separately uses actual human
Cross input, guest Pad records and Vulkan readbacks, with an explicit disconnect
permission gate. The local instruction panel starts no guest until Ready is
clicked and sends no gameplay/diagnostic keyboard or controller events.

The twenty-second suite, `pad-axes-evidence-contract`, rejects incorrect raw Pad
schemas/records, stale or mismatched Vulkan images, swapped/incorrect stick
directions, missing SDL axis-motion events, short center/direction holds and
incomplete phase sequences. The window-identity diagnostic still fails ownership
loss; it never rebinds or restores focus. Generated host data is not hardware
acceptance. The separate [button/stick workflow](dualsense-controls.md) records
actual user-assisted USB input. Its new isolated fixture leaves all earlier
fixture hashes and engine/dependency pins unchanged. The existing physical suite
also covers waiting for the original PNG write to complete before consuming it.

The twenty-third suite, `window-identity-contract`, checks the scoped read-only
[window diagnostics](window-identity-investigation.md). Portable cases preserve
identity failures and reject global scope; the Windows-only case distinguishes
real hidden host-window destruction/replacement from process exit without
rebinding. Linux skips that native case explicitly. No guest, controller or
audio device is accessed, and the original two window losses remain unresolved.

Two additional host suites, `pad-hotplug-policy` and
`pad-hotplug-evidence-contract`, bring the total to 25. They compile the actual
pure policy from the isolated [hotplug fixture](dualsense-hotplug.md) and reject
invalid generated evidence, respectively. Optional local SDL-helper checks use
only invalid arguments rejected before SDL initialization; hosted CI skips that
helper case explicitly. Fixture builds, host tests and generated records do not
establish actual guest execution or physical disconnect/reconnect support. The
original live fixture and all earlier engine/fixture/dependency pins are preserved.

Two final hotplug suites bring the count to 27. `pad-hotplug-support-contract`
checks the real UTF-8 instruction/confirmation paths, reconnect timer origin,
separate protocol permission and read-only per-endpoint mute/volume validation.
Its Windows helper argument checks run before COM initialization; Linux skips
that case explicitly. `pad-hotplug-recorded-evidence` replays immutable original
physical-004 Pad records, native events, endpoint transitions, confirmations and
seven exact PNGs on both platforms. It checks tested-versus-integrated policy
source equivalence without starting a controller or guest session. See the
[hotplug report](dualsense-hotplug.md) for the separate real hardware result,
failed attempts, revised endpoint protocol and current limits.

The twenty-eighth suite, `pad-disconnected-close-contract`, tests the separate
[disconnected-close workflow](dualsense-disconnected-close.md). Generated
records/images, inert instruction widgets and mocked process/window boundaries
exercise its three-capture contract, real runner coordination, authorization,
continuity and normal-versus-forced cleanup rejection. Optional local native
argument checks stop before SDL initialization; hosted CI skips that case.
No guest or controller is accessed by this suite. The existing seven-stage
hotplug workflow and original fixture/pins remain unchanged. One separately
approved physical disconnected-close session now passed with actual guest/SDL
observations, three exact images and normal zero/empty process exit.

The twenty-ninth suite, `pad-disconnected-close-recorded-evidence`, replays the
original 607 guest records/journal, native removal, human confirmations, three
full PNGs, endpoint and cleanup observations. It preserves the failed/unmuted
preflight as failed and compares 17 tested source snapshots to the current
implementation. Five replay/negative tests access no hardware and establish no
additional physical run. See the [disconnected-close report](dualsense-disconnected-close.md)
for the real session, source equivalence, publication/privacy choices and limits.
