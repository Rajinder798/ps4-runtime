# G4 versioned no-guest diagnostic coordinator

This is a G4 diagnostic prerequisite, based on commit
`25fc5f5b86f253a8ceb17166ea6214707855b80f`. It is separate from ordinary launch,
registered shortcuts and gameplay. No guest, real PnP/SDL watcher, physical USB
action or audio setting change is part of its implementation or verification.
The historical no-guest attempt remains FAILED; guest recovery remains FAILED,
6/9. Issues #33, #37 and #39 remain open. No PR or merge is requested here.

## Components and compatible contracts

The portable `no_guest_coordinator_v1` module supplies the closed-schema readers,
joint-readiness policy, explicit confirmation state machine, bounded journal,
bundle verification and opt-in CLI. `no_guest_session_v1` connects that policy
to separately owned processes. `coordinator_windows_v1` supplies atomic Windows
job ownership and integrates the unchanged v2 job-membership implementation.
The new clocked read-only endpoint guard has its own executable/schema and never
initializes COM in its fake-provider mode.

| Role | Exact selected interface |
| --- | --- |
| PnP | Frozen MSVC `pnp-coverage-v2.exe`, SHA-256 `8569bbf9022c259e9740a710121631d709c3aeb0061b2ab6e843386925968709` |
| PnP arguments | `--observe-pnp-coverage-v2 LOG STOP READY 110000 --pnp-coverage-authorized` |
| PnP evidence | `pnp-coverage-v2`, fresh empty readiness marker after native `Ready()` |
| SDL | Frozen `arrival-probe-v1.exe`, SHA-256 `4cd0d7e15a1ae9b54b9de20176d25bf9ddcb468c937cd6909da7eaf3447e6552` |
| SDL arguments | `--watch-arrival-v1 STRICT STOP READY 110000 ARRIVAL --disconnect-authorized --reconnect-authorized --arrival-diagnostics-authorized` |
| SDL evidence | Separate `arrival-v1` diagnostics and unchanged strict native JSONL; marker `wired DualSense ready` with native newline |
| Endpoint | New `endpoint-clock-v1.exe`; exact binary/source/compiler/build metadata in the independently hashed bundle |
| Endpoint arguments | `--observe-endpoint-clock-v1 LOG STOP READY 120000 --endpoint-monitoring-authorized` |
| Endpoint evidence | Separate `endpoint-clock-v1`, native QPC query brackets and fresh empty marker after sampled mute/volume validation |

`config/no-guest-coordinator-v1.json` locks the original PnP/SDL sources, binaries,
build attestations, Python executable, engine/report and existing SDL archive.
The builder reads and hashes those inputs; it does not execute the engine or
SDL observer. It compiles only the new guard against the existing Windows SDK.
Its exact source/binary/build metadata and all coordinator sources enter a bundle
whose SHA-256 must be supplied explicitly to the future CLI. There is no v1 PnP
fallback. Copies of v2 built for host regression tests are not selected for live
use. Metadata, binaries and current source content must all agree.

## Authorization, freshness and readiness

`--run-no-guest-v1` requires all three explicit flags:
`--physical-usb-authorized`, `--monitoring-authorized` and
`--read-only-audio-authorized`. Missing authorization is rejected before importing
the live adapter, opening jobs or initializing any observer. `--verify-bundle`
only verifies files and never initializes monitoring. Neither importing these
modules nor running help starts processes or COM.

A future live run additionally requires the operator to type `START_NO_GUEST`.
The output must be a new, nonaliased directory under repository `build/`, outside
all attested input files. Its component directories and report/stop/ready paths
are separate and fresh. Ready markers alone are insufficient: they must have
the expected bytes and a write time no older than their process launch, and
must agree with owned PID, native schema, origin, frequency and actual evidence.
Pending partial records cannot confer readiness. Final independent file hashes
detect rewritten prefixes as well as malformed/truncated data.

The endpoint guard starts first. Only after a valid muted observation and its
marker do PnP and SDL start. No USB instruction is issued until BOTH observers
qualify, their markers are fresh, and the guard remains healthy. The coordinator
honors v2's complete coverage, exactly one qualified present root and a present
started HID child with its own target VID/PID and successful USB ancestry.
An inactive installed root is retained separately. `related_hid`, an unknown
property, missing HID, incomplete coverage or native failure cannot satisfy this
gate. The original v2 policy and all original acceptance contracts are unchanged.
Snapshot/heartbeat staleness is a failure, not a substitute for current proof.

Each observer's original first failure is retained separately from the overall
first failure and cleanup errors. A PnP failure before SDL readiness prevents
instructions even if SDL opens during cleanup. Failures are flushed before
containment; reserved journal capacity protects first-failure/close records.
An inaccessible/full filesystem can still prevent durable evidence; that is
failure/unknown, never a successful collection.

## Protocol prepared for later authorization

1. Close other test tools, leave USB connected, keep all buttons untouched, and
   review the exact approved bundle digest and fresh output location.
2. Provide the three explicit CLI authorizations and type `START_NO_GUEST` only
   under a separate owner-approved physical session.
3. Wait for guard/PnP/SDL joint readiness. Any legitimate unresolved metadata,
   identity, coverage or clock issue stops before USB instruction.
4. Type `CONFIRM_UNPLUG` before receiving the single manual unplug instruction.
   Do not act on the confirmation prompt itself. The coordinator never unplugs.
5. Wait for independent PnP absence, strict SDL removal/disconnection and Windows
   removal observation. No reconnect instruction follows from a human claim alone.
6. The reconnect confirmation prompt starts the original 30-second window. Type
   `CONFIRM_RECONNECT`, then perform one manual reconnect when instructed. The
   timer is not restarted by confirmation or an early returning candidate.
7. Observe the entire 30-second window. Early return remains a candidate until
   the window ends and final independent validation/cleanup pass. Extra opens,
   buttons, failures, stale coverage or confirmation-order errors fail.
8. Stop observers, establish their whole job empty, then stop the guard and
   establish its job empty. Preserve originals, validations, coverage and hashes.

There are zero automatic USB actions or retries. Initial readiness has an
8-second bound, unplug confirmation 25 seconds, and removal observation 20
seconds. Collection stops by 110 seconds from session start. Cleanup normally
has an 8-second bound; a 118-second watchdog requests forced containment if
ordinary coordination stalls. Native observers have their own bounded durations,
at most 120 seconds. Scheduling/OS/filesystem stalls cannot be represented as
verified timing; actual durations, late/forced/unknown outcomes remain evidence.
`STOP`, EOF, invalid commands or panel/console interruption fail and contain.
No buttons, screenshots, guest, engine, driver/power setting or audio setter is
part of this protocol. Diagnostic `recovery_accepted` remains false even when all
requested no-guest boundaries are observed.

## Ownership and cleanup

PnP/SDL share one owned job; the endpoint guard has a separate job. The Windows
adapter uses the documented
[JOB_LIST and HANDLE_LIST startup attributes](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute)
with [CreateProcessW](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-createprocessw).
Job membership is assigned atomically at creation. The primary thread is also
suspended, ownership is checked, and only then is it resumed. No ordinary Popen
fallback or uncontrolled pre-assignment child execution is permitted. Only the
three duplicated standard handles inherit; job/process handles do not. Windows
creation uses CREATE_NO_WINDOW. A named coordinator lock prevents another instance
from taking a concurrent session. External independently launched tools cannot
be ruled out by that lock and must be closed before future approval.

Cleanup uses the existing supported full-member/active-accounting queries.
Recorded member PID lists, query brackets, root exit codes, stop requests and
empty-job proof remain distinct. Exited root handles are released after recording
their status; exit 0 never substitutes for job-wide emptiness. Unattributed console
hosts or descendants are not ignored. Unknown membership or a surviving child
leads to explicit bounded containment and prevents normal-cleanup certification.
Last-handle close is labelled as possibly forcing remaining members unless the
job is proven empty. Exceptions also produce unknown/forced-containment outcomes.

The guard is retained while observer shutdown is established. If membership
cannot be certified, bounded containment is attempted before releasing the guard;
this remains uncertified. Early guard exit is a failure even if every known root
later exits 0. Evidence distinguishes the order actually observed by queries from
an exact OS termination instant, which may lie between polls. First failures
survive all cleanup paths.

## Clocked endpoint evidence

The historical guard is unchanged. The new guard reads default endpoint identity,
availability, mute and scalar volume through COM getters only, retaining at most
four local endpoint tokens. There are no audio streams or setters. It logs native
QueryPerformanceFrequency, PID and QPC query begin/end/publication ticks. The
coordinator records an actual QPC/perf_counter bracket and requires matching QPC
frequencies. Existing SDL clock anchors remain separate; SDL timestamps are not
silently converted into Windows event times.

Coverage reports list the muted observations and their query brackets,
sample-supported intervals, unobserved/unverified gaps, endpoint switches and
independent per-token volume changes. Guard stop/root-exit/member observations
give the observed shutdown order. All continuous time between sparse observations
remains unknown: neither a sample nor its query bracket proves continuous mute.
Unavailable endpoints are recorded honestly; their volume/state is not invented.
The original elapsed_ms-only trace is never promoted to exact QPC coverage.

## Host verification and reproduction

Use Python 3.10+ (3.12 tested), C++20 and a Windows 10/11 x86-64 toolchain for the
native adapters. The standalone project includes all existing v2 tests:

```powershell
cmake -S tests/no_guest_coordinator_v1 -B build/coordinator-host -DCMAKE_BUILD_TYPE=Release
cmake --build build/coordinator-host --config Release
ctest --test-dir build/coordinator-host -C Release --output-on-failure
```

The portable suite uses the actual C++ v2 fake provider and labelled synthetic
arrival/endpoint events. It covers joint readiness, early PnP failure/late SDL
open, missing HID, installed inactive roots, identities/schemas, markers, partial
and rewritten data, confirmations, unchanged reconnect deadline, endpoint gaps,
first-failure reserve and full Session cleanup integration. Inert Windows workers
test atomic ownership before worker entry, resume failure, normal empty jobs,
unexpected descendants, guard early exit and pinned-file protection. The clocked
guard is executed only with its synthetic provider; no COM/audio API is initialized
in that mode. Host origins cannot be accepted as live evidence. Linux skips only
the native Windows cases; it runs portable policy/readers/cleanup tests.

The separate builder command compiles the guard and verifies an exact input
bundle; it does not run it:

```powershell
python -B tools/build_no_guest_coordinator_v1.py --output build/coordinator-bundle
python -B tools/no_guest_coordinator_v1.py --verify-bundle --bundle build/coordinator-bundle/coordinator-build-v1.json --bundle-sha256 <reviewed-sha256>
```

Run full root host suites separately in a fresh build directory. Local evidence,
historical replay, independent original-file checks and final-head CI are retained
under `build/live-av-v2/no-guest-coordinator-v1-001/`. All 700 originals, 37 boundary
artifacts, 773 older entries and the previous v2 artifact set remain preserved.
No existing source, binary, pinned dependency or failed evidence is modified.

Known limits remain: historical HID rejection/44 classifications and the original
active-job member are not retrospectively attributable. The new coordinator has
not run against real hardware. Its physical notification, mute-clock integration,
console interaction and two-minute containment behavior remain live-unverified.
GPL-2.0-or-later and existing dependency/source/relink release holds are unchanged.
Stop after offline reporting; the prepared procedure needs separate authorization.
