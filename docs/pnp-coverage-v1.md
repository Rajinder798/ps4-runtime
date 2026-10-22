# Property-based Windows PnP coverage, version 1

This is a G4 diagnostic prerequisite for Issue #37. The latest `live-av-v2`
physical recovery remains **FAIL, 6/9 phases**. Filtering limitations justify
better coverage; they do not establish the reconnect cause or a repair.
Issues #33, #37 and #39 remain open. No hardware observation or guest execution
is authorized by implementing this component.

The new `pnp-coverage-v1` executable, portable collector and offline validator
are independent of `arrival-v1`, the strict SDL observer and physical runner.
They link only the C++ runtime, SetupAPI and CfgMgr32. Engine, SDL, SDK, fixtures,
Pad/graphics/audio behavior, clocks, nine-phase qualification and timeouts are
unchanged. No existing launch path starts this executable. Its only live entry
point requires `--observe-pnp-coverage-v1 EVIDENCE STOP READY DURATION_MS
--pnp-coverage-authorized`; the permitted duration is 1–360 seconds and all three
paths must be fresh and distinct. That interface documents a future explicit
opt-in; it has not been run for this implementation.

## Metadata and correlation

Microsoft explicitly says to avoid parsing interface symbolic names.
[SetupDiGetDeviceInterfaceDetailW](https://learn.microsoft.com/en-us/windows/win32/api/setupapi/nf-setupapi-setupdigetdeviceinterfacedetailw)
supports retrieving only `SP_DEVINFO_DATA`, with the documented
`ERROR_INSUFFICIENT_BUFFER` result. We use that form without allocating an
interface-path output buffer. Notification links pass unchanged to
[SetupDiOpenDeviceInterfaceW](https://learn.microsoft.com/en-us/windows/win32/api/setupapi/nf-setupapi-setupdiopendeviceinterfacew),
which opens an element in a device information set. It opens no controller
input/output handle. Deleting that information-set element and destroying the
set release query resources; neither operation removes or disables hardware.

`CM_Get_DevNode_PropertyW` reads
[hardware IDs](https://learn.microsoft.com/en-us/windows-hardware/drivers/install/devpkey-device-hardwareids),
[enumerator name](https://learn.microsoft.com/en-us/windows-hardware/drivers/install/devpkey-device-enumeratorname),
compatible IDs and, only for relevant nodes, the instance ID used for local
tokens. Property types, lengths and MULTI_SZ termination are checked. Original
CONFIGRET values remain separate from format-valid flags; missing, oversized or
malformed properties cannot become a match. Compatible IDs provide optional
composite context, never sole controller identity.

The hardware-ID grammar follows documented
[USB vendor/product and composite-interface identifiers](https://learn.microsoft.com/en-us/windows-hardware/drivers/install/standard-usb-identifiers).
The USB enumerator plus exact VID 054C/PID 0CE6 identifies a candidate physical
parent; an MI suffix identifies a function rather than its parent. Mixed or
unsupported identity formats remain indeterminate. This is a property-backed
diagnostic candidate, not authentication of a physical controller.

HID candidates require a bounded `CM_Get_Parent` chain ending in that USB parent.
A generic HID descendant with that ancestry is labelled `related_hid`, separately
from a child with its own matching VID/PID. A generic HID/USB class alone is
insufficient. Missing ancestors, cycles, a chain limit, unavailable identity or
multiple distinct roots leave incomplete/unresolved or ambiguous coverage. Every
observed candidate is reported; none is selected for gameplay. Root tokens refer
to logical Windows instances within this file; token reuse is not proof of the
same physical unit or identity across sessions.

## Separate observations

| Observation | Source and meaning |
| --- | --- |
| Raw callback | USB/HID class, action, receipt QPC and local ordinal before classification |
| Classification | Lookup attempt, original return codes, normalized interface-detail outcome, property validity and intended/unmatched/indeterminate result |
| Present devnode | Independent `SetupDiGetClassDevsW(ALLCLASSES | PRESENT)` / `SetupDiEnumDeviceInfo` scan |
| Parent / HID child | Property identity and parent-chain proof, separate relevant roles/tokens |
| Enabled interface | Per-class `SetupDiEnumDeviceInterfaces` and `SPINT_ACTIVE`, separate from present-devnode membership |
| Installed inactive interface | Interface enumeration intentionally omits PRESENT; inactive and removed flags are retained |
| Started / problem | `CM_Get_DevNode_Status`, DN_STARTED and documented problem code when DN_HAS_PROBLEM is set |
| Incomplete coverage | Query failure, malformed identity, unresolved ancestry, ambiguity, exhausted limits or overhead |

Each notification gets a receipt and classification row, including unmatched
interfaces and lookup failure after removal. Unmatched rows carry only class,
action, public outcome/API metadata and zero identity tokens/status. Invalid
payloads are counted and classified indeterminate. Queue loss is explicit in
bounded class/action counters, dropped/malformed counts and first failure;
overflow cannot silently disappear. The callback only timestamps and copies a
bounded opaque lookup input; queries and file writes happen outside it.

Snapshots bracket the enumeration, property queries and detail publication with
QPC. They contain bounded classification counts, original enumeration/cleanup
codes (including the original terminal enumeration result), limit flags, fixed
classification-failure histograms and explicit enumeration completion. `no_qualifying_node`
is permitted only for a complete scoped snapshot with no qualifying present
node. Failed/partial enumeration instead reports `unknown`. Enabled interfaces
without a present devnode and arrivals followed by an empty complete snapshot
are reported as observation disagreements. Enumeration is not atomic; these can
reflect races and are not root-cause diagnoses. Polling cannot exclude brief
between-sample changes or devices outside the documented identity scope.

## Limits, timing and privacy

| Resource | Limit |
| --- | --- |
| Evidence | CREATE_NEW, append writes, 8 MiB / 20,000 rows; 2 KiB and three rows reserved for first failure, cleanup and summary |
| Callback queue | 256 entries, at most 1,023 wide characters per transient opaque link; lock contention/overflow counted |
| Present devnodes | 2,048 enumerated entries per snapshot |
| USB / HID interfaces | 2,048 entries per class, including inactive installed interfaces |
| Related details | 64 node/interface rows per snapshot |
| Parent walk | 8 ancestors, cycle detection |
| Property buffer | 16 KiB; no resize/retry; at most 64 hardware/compatible strings, each at most 1,023 characters |
| Property cache | 6,152 sanitized node summaries per scan/notification lookup |
| Relevant tokens | 128 instance keys, each at most 4,095 wide characters, kept only in memory |
| Error histogram | 32 distinct fixed API/code pairs per snapshot |
| Sampling | Initial scan, then at least 2 seconds after each completed scan; no catch-up burst |
| Overhead | A scan or notification drain over 250 ms, scan-start gap over 2.35 seconds, or total duration overrun over 250 ms fails collection completeness |

The observer is a separate process and does not occupy the SDL/guest observation
loop or extend its deadlines. Scheduling and Windows query calls can still affect
the host. API calls have no hard cancellation deadline; their elapsed time and
late cadence must be reviewed, and future orchestration needs independent process
containment. The caps bound application-owned entries, not SetupAPI's internal
allocations, OS buffers, allocator overhead or total working set. Two queue copies
can coexist while draining (about 1 MiB on Windows); the maximum token character
storage is about 1 MiB, plus bounded node maps, query buffers and enumeration
vectors. Real-device latency/working-set measurements remain unverified.

No raw symbolic link, device-instance string, serial, MAC, private path, raw
hardware/compatible ID, unrelated node token or arbitrary Windows error text is
written. Original private instance keys are transient and relevant-only. The
writer uses typed outcomes/fixed field names; the independent validator enforces
exact schemas, bounded values and privacy enums. File I/O/flush failure cannot
guarantee a durable failure row: failed exit/stderr and incomplete evidence remain
failures. Files are never rotated, replaced or repaired. Initial incomplete
coverage prevents readiness; a later diagnostic failure stops the live loop and
retains the first failure through unregister/drain cleanup.

The header records source PID, clock kind and frequency. QPC values are host
observation times, not USB bus-event timestamps. SDL and
guest clocks are not read, rewritten or synchronized by this component. No SDL
event, reopen, Pad operation, guest sample, timeout extension or physical verdict
can be produced. `recovery_accepted` and `physical_absence_proven` in offline
reports are always false, including complete diagnostic collections. First
failure is latched before cleanup; unregister/query cleanup codes and final
cleanup failure remain separate.

## Host verification and preservation

Build with the existing CMake host toolchain. `pnp-coverage-policy-v1` checks the
actual portable policy and, on Windows, the actual callback adapter using inert
buffers. `pnp-coverage-evidence-v1` drives the actual collector/writer with labelled
synthetic providers, then independently validates the files. These tests never
construct the Windows query provider, register notifications or execute the live
entry point. Cases include parent/child proof, unrelated devices, malformed or
missing metadata, multiple roots, absent/inactive interfaces, failed removal
lookup, contradictory observations, partial/failed enumeration, limits, clocks,
overhead/cadence, privacy, first-error/cleanup separation and corrupt evidence.
The default validator rejects `host-test` streams. Synthetic evidence is not
physical USB proof.

All earlier host suites and recorded guest/image replays still run. The local
implementation report in `build/live-av-v2/pnp-coverage-001` inventories historical
source/binary/evidence attestations and records exact new source/binary hashes,
commands, local outcomes, preservation checks and final-head hosted status.
`arrival-v1`, its build attestation, strict native JSONL and physical acceptance
remain byte-compatible because their sources and original evidence are unchanged.
No engine/dependency binaries are distributed. Original code is GPL-2.0-or-later;
engine redistribution/source/relink holds remain separate and open.

## Proposed future physical verification — approval required

After review, authorize one no-guest Windows-plus-SDL diagnostic cycle, at most
two minutes, with one human unplug and one reconnect. Keep Windows muted and
preserve cable/port, endpoint volume, device settings and all pinned inputs.
Preflight source/build attestations and bounded collector overhead; use independent
process containment. Use a 30-second reconnect window starting at the explicit
instruction without resetting it. Collect this component beside the separately
approved SDL diagnostic, preserving both clocks/streams and the original first
failure. Stop on failure and retain incomplete boundaries; no automatic repeat,
buttons, screenshots, guest, reset, rescan or settings changes are needed.

Compare devnode parent/child presence, start/problem status, active interfaces,
callbacks and actual SDL inventories. Review observation disagreements and overhead
before any later guest acceptance proposal. Such a cycle would diagnose exposure
boundaries only. It would not qualify nine-phase recovery or resolve Issues #33,
#37 or #39. No such cycle has been performed or authorized here.
