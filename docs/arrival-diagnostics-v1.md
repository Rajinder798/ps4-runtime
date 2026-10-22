# G4: opt-in Windows/SDL arrival diagnostics v1

This is a diagnostic prerequisite for Issue #37, based on
`03ab66738395264e6f3f45d10e0960b646b42a2e`. It is not a reconnect fix.
`physical-recovery-002` remains **FAIL (6/9 images)**. The human reported reconnect;
no returning `hotplug_opened` or guest connected state was recorded before the
unchanged 30-second deadline. Requested forced containment, not a demonstrated
engine crash or normal close, ended that attempt. Issues #33/#37/#39 remain open.

This gate authorizes builds and host tests only. **No live Windows notification,
SDL/controller watch, guest, USB action or audio/device-setting change is part of
this verification.** Compile success cannot establish notification delivery on
the owner's machine. The original live-av and v2 Pad policies, pinned engine/SDK/
SDL, registrations, preferences and shortcuts are unchanged. Licensing/source and
redistribution holds remain separate; no executable is committed or distributed.

## Separate binary and unmodified acceptance

`arrival-probe-v1.exe` includes `tests/dualsense_sdl_probe.cpp` unchanged, with
small wrappers around real SDL Init, PollEvent, GetGamepads and OpenGamepad calls.
It does not replace API return values or generate events. The wrappers record raw
device events **before** the historical handler runs, independent joystick/gamepad
inventories, candidate assessments, actual open results and wired checks. The
original one-device, physical PS5 identity, wired, fresh-instance, one-removal/
reconnect checks still run. Initial queued announcements are distinguished from
new arrivals; an open is not inferred from an ADDED event. The historical strict
native JSONL schema is unchanged; diagnostics go to a separate file.

Old binaries/build metadata remain valid for their old sources. Protected
observers include the PR #36 probe, PR #38 extended probe, PR #41 hotplug probe and
PR #42 disconnect-only probe. The current shared source LF hash remains
`1c9463f8987cee4a3310b8f5268979d772f7e9e2c64be46612dded8746daaa30`.
The older PR #41 source snapshot has its own `bbafa08d...` attestation; it is not
replaced with current source. Windows endpoint observers, ownership diagnostics,
their historical source snapshots, and PR #41/#42 validators are also unchanged.
The local build/evidence report inventories the exact protected binary hashes.

The new `arrival-build-v1.json` independently attests all wrapper/Windows/header
sources, included historical source, new binary, builder, engine/report and
existing SDL static library. The builder verifies the clean SDL header checkout
against the engine's pinned submodule revision; no dependency is fetched/rebuilt.
It builds tooling only and never executes the new observer.

Future v2 recovery collection requires the additional explicit
`--arrival-diagnostics-v1` flag and the separately attested new observer. It is
rejected for automated guest cases and disconnected-close mode. Existing runs
without the flag retain the historical observer contract. The guide, reconnect
timer, nine captures and six-minute budget are unchanged.

## Passive Windows boundary

The Windows component uses documented
[CM_Register_Notification](https://learn.microsoft.com/en-us/windows/win32/api/cfgmgr32/nf-cfgmgr32-cm_register_notification)
with DEVICEINTERFACE filters for the public USB-device and HID interface classes.
It needs Windows 8+; the existing build targets Windows 10/11. No notification
window, administrator/device handle, driver installation, rescan, reset, logging
change or power-setting change is used. Callbacks always return ERROR_SUCCESS
and cannot veto removal. They copy only bounded relevant notifications into a
256-entry queue; no callback file I/O or device enumeration occurs.

After registration, and about once a second, a single bounded
[CM_Get_Device_Interface_ListW](https://learn.microsoft.com/en-us/windows/win32/api/cfgmgr32/nf-cfgmgr32-cm_get_device_interface_listw)
PRESENT query records matching Sony interface presence. Registration precedes
enumeration, as Microsoft recommends. Arrival and presence may overlap and are
kept separate. A buffer-size race fails explicitly; there is no automatic retry.
Classified interface arrival means Windows enabled an interface, not that a USB
cable action, physical identity, SDL open or guest recovery has been proved.
Interface counts do not equal controller counts; one controller has several HID
interfaces. HID/USB paths may not provide a durable cross-interface identity.

Only matching VID_054C/PID_0CE6 path classifications enter the queue. Full paths
exist transiently in memory for token assignment; only session-local integer
tokens/class labels are written. No serial, MAC, private path, unrelated Windows
device identity or arbitrary SDL error string is emitted to the diagnostic file.
SDL diagnostics retain numeric instance/type/virtual fields; unrelated VID/PID
values are redacted. Historical stdout/stderr remain private originals and must
be reviewed/redacted separately before any publication.

Malformed callback data, unsupported class/action, queue/token exhaustion,
registration/query failure and failed unregistration are explicit failures.
[CM_Unregister_Notification](https://learn.microsoft.com/en-us/windows/win32/api/cfgmgr32/nf-cfgmgr32-cm_unregister_notification)
runs outside the callback and waits for pending callbacks. Close is idempotent,
with no retry. If unregistration fails, callback context is retained until process
exit instead of being freed while callbacks could still use it. This is an
explicit cleanup failure, never complete diagnostic coverage.

## Three separate evidence surfaces

| Surface | Evidence | Does not establish |
| --- | --- | --- |
| Windows | callback arrival/removal, interface tokens, presence query, API errors | SDL recognition or physical/guest recovery |
| SDL diagnostic | raw joystick/gamepad events, numeric ID, SDL timestamp, inventory, rejection reason, open/wired result, heartbeat | a strict `hotplug_opened` or successful guest phase |
| Guest witness | original actual audit sample plus host read-observation bracket | a new Pad read, exact Pad-event host time or image/exit qualification |

`arrival-native-v1.jsonl` uses schema `arrival-v1`, at most 8 MiB/20,000 records;
the callback queue holds 256 records, at most 64 intended interface tokens, and
each SDL inventory holds at most 16 devices. The stream reserves room for its
first-failure, cleanup and final summary. Windows writes use exclusive CREATE_NEW
and append access; no replacement/truncation. Exhaustion, partial writes and I/O
errors fail. An unavailable filesystem cannot guarantee a durable failure record;
stderr, failed exit and incomplete evidence remain failures.

`arrival-guest-v1.jsonl` is bounded at 1 MiB/8,192 records, including failure and
cleanup reserve. It records control/connection transitions and periodic witnesses
from the existing append-only audit, without altering guest records/timestamps.
The audit and binary journal remain the complete original guest evidence. The
first monitor error is latched before containment; later cleanup errors are kept
separately. Diagnostic failure cannot turn a failed guest run into a pass.

The independent validator rejects unknown/duplicate fields, corrupt/truncated
files, wrong identity, stale/extra opens, unsupported ordering and clock reversal.
It cross-checks diagnostic opens against strict native opens and witnesses against
actual audit samples. Missing Windows arrival, raw SDL discovery or guest recovery
remains explicitly missing. `recovery_accepted` is always false in diagnostic
reports. Opt-in collection requires both original physical acceptance and complete
diagnostic boundary evidence; one can never substitute for the other.

## Clock contract

Native headers record observer PID and QueryPerformanceFrequency. All native
publication, Windows callback observation and query brackets use integer host QPC
ticks. Divide by that frequency to compare with the human guide/runner's Python
perf_counter seconds on Windows. Preserve received-callback time separately from
the later publication time. These are callback observations, not OS bus timestamps.

Raw SDL event timestamps remain nanoseconds in SDL's own clock. A sampled
GetTicksNS value is bracketed by two QPC reads after initialization. A local
conversion can only be an estimate with that sampling uncertainty and unmeasured
drift; the standard boundary report uses **host receipt QPC**, not a silently
converted SDL timestamp. No exact SDL occurrence-time/Windows callback ordering
is claimed from those separate clocks.

Guest observed_us, Pad timestamp and audit elapsed_us remain their original
relative clocks. The host witness records audit-read begin/end QPC, sequence and
unchanged sample. Read completion gives an upper observation bound: the guest
record already existed by then. Read start is not a lower bound on guest event
generation. A batch may contain several older transitions. No process-creation,
file-time or guest-entry offset is invented. A bracketed QPC/Unix pair supports
approximate human-readable UTC only; wall-clock changes do not determine ordering.

## Non-physical verification

New portable policy tests cover intended-interface matching, raw SDL classification
and strict candidate rejection. Windows-only controlled callback injection calls
the actual parser with labelled host payloads, including truncated/unterminated
data, class conflict and queue overflow. It never registers/enumerates hardware.
Python tests use explicitly `host-test` streams; the default evidence validator
rejects them as hardware proof. Tests cover missing boundaries, malformed files,
clock/identity conflicts, bounded storage, actual cleanup callback/first-failure
behavior, short writes and independent build attestation. All original 31 host
suites and historical PR #41/#42 evidence replay must also pass.

The Python diagnostic suite contains 24 tests. The Windows-only parser/writer
suite includes controlled callback arrival/removal, malformed payload/class and
queue-overflow checks; no API registration is used in those tests. Diagnostics
add bounded query/file I/O and can affect timing; future hardware execution must
verify that overhead within the unchanged acceptance budgets.

The expected suite totals are 34 on Windows and 33 on Linux (Windows callback
injection has no Linux equivalent). Actual local/build/hosted results, hashes and
warnings belong in the gate's final evidence report, not inferred from this plan.
Fixture and engine workflow inputs are unchanged; an untriggered rebuild is not
a fresh successful build. The new SDL-linked observer is built locally against
the pinned library; baseline hosted jobs compile the policy/Windows callback
components but do not fetch/link SDL or run a watcher.

## Proposed future physical gate — separate approval required

Use one freshly preflighted USB-C DualSense, one guest, at most six minutes, one
manual unplug while Cross is held and one manual reconnect. Keep all available
observed endpoints muted at unchanged per-device volume, with no settings changes.
Use the existing nine-phase guide, readiness gates, exact screenshots and normal
human X close. Keep the 30-second reconnect budget starting at its explicit
instruction; do not reset/extend it. Collect Windows callbacks/presence, raw SDL
events, actual opens, strict native records and guest witnesses together.

Report each boundary independently: missing Windows interface arrival, Windows
presence without SDL enumeration, joystick without gamepad recognition, raw ADDED
followed by rejected identity/open, or validated native open without engine/guest
recovery. Missing notifications remain unobservable evidence, not proof of no
physical arrival. Stop at the first failure, preserve it before containment and
never retry automatically. All journal/audit/image/same-handle/fresh-timestamp/
normal-close requirements remain unchanged. No new session is authorized here.
