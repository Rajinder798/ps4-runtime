# G4 PnP readiness and cleanup diagnostics, version 2

This is an offline diagnostic prerequisite for Issue #37. The original no-guest
attempt remains **INITIAL READINESS FAILED**; the previous guest recovery remains
**FAILED, 6/9**. Issues #33, #37 and #39 remain open. No guest, notification
registration, live PnP/SDL observer, USB action or audio setter is used in these
tests. This work establishes no new physical recovery or game compatibility.

The attested v1 files are frozen. The replacement lives in
`tests/pnp_readiness_v2/`, with a standalone CMake project and two new Python
modules. Its versioned collector/backend/observer/validator derive from v1 but
use a distinct `pnp-coverage-v2` schema and executable. This deliberate version
boundary preserves all 700 original source/build/evidence files, the old binary
attestations and the 773 older manifest entries. The root CMake file, original
workflow, engine/SDK/SDL pins, guest fixtures, arrival-v1/native JSONL, Pad policy,
Vulkan/audio behavior, nine-phase acceptance and 30-second reconnect deadline
are unchanged. Do not mix the two schema versions.

## What failed in the retained attempt

The initial scan visited 285 present devnodes: three intended observations,
258 unmatched and 24 indeterminate. Interface scans added 20 indeterminate
observations. The histogram collapsed those 44 attempts to `hardware_malformed`;
they can overlap the same devnodes and are not 44 controllers. No property types,
byte counts, original strings or finer decoder reasons were retained. Their
specific distribution cannot be reconstructed offline. The old code conflates
list decoding, syntax, unsupported forms and identity conflicts. It would be
incorrect to claim that Windows supplied 44 malformed IDs or that this version
has established the historical HID rejection's precise cause. One independently
confirmed decoder defect is that v1 rejects the documented single-NUL empty
MULTI_SZ as malformed. V2 reports that form as missing hardware identity. Whether
it occurred among the historical 44 attempts is unknown.

There is one directly demonstrated accounting defect. The trace contains one
present started target USB parent, two present functions beneath it, and an
installed inactive interface with another root token, `present=0`,
`root_present=0`, flags 0 and status `CR_NO_SUCH_DEVNODE=13`. V1 adds every
resolved root to one set and marks two roots ambiguous, while also treating the
inactive node's expected status failure as a live coverage failure. Two connected
physical controllers were never established. The separate unknown classifications
still prevent complete coverage even after correcting this defect.

## Property and identity contract

`CM_Get_DevNode_PropertyW` results retain the original API code, public property
type and byte length. The UTF-16 MULTI_SZ decoder checks its type, bounded byte
length/alignment, terminal NULs, interior termination, 64-string limit and
1023-character string limit. No strings are serialized. See Microsoft's
[STRING_LIST contract](https://learn.microsoft.com/en-us/windows-hardware/drivers/install/devprop-type-string-list).
A nonempty sequence requires the final string NUL and sequence NUL; the
[documented empty sequence](https://learn.microsoft.com/en-us/windows/win32/sysinfo/registry-value-types)
is a single NUL and reports `missing_hardware_id`, never target identity.

Case-insensitive vendor forms use exactly four hex digits for VID/PID/REV and
two for MI/COL, in the documented order:

| Bus | Accepted vendor grammar |
| --- | --- |
| USB parent | `USB\VID_vvvv&PID_pppp`, optionally followed by `&REV_rrrr` |
| USB function | `USB\VID_vvvv&PID_pppp&MI_mm`, or with `&REV_rrrr` before MI |
| HID | `HID\VID_vvvv&PID_pppp`, optional REV, optional MI, optional COL, in that order |

All eight HIDClass single/multiple function and collection combinations are
tested against the
[documented HID forms](https://learn.microsoft.com/en-us/windows-hardware/drivers/hid/hidclass-hardware-ids-for-top-level-collections).
USB forms follow the
[standard identifiers](https://learn.microsoft.com/en-us/windows-hardware/drivers/install/standard-usb-identifiers)
and the
[composite-interface forms](https://learn.microsoft.com/en-us/windows-hardware/drivers/install/identifiers-for-usb-devices).
Different VID/PID, role, MI, COL or conflicting nonempty REV values in one list
are conflicts. Revision-specific and revision-free versions may coexist.
Known other vendors are unmatched and cannot become target HID descendants.

Only VID 054C/PID 0CE6 is a target candidate. The documented nonidentity forms
`USB\CLASS_cc[&SUBCLASS_ss[&PROT_pp]]`, `USB\COMPOSITE`,
`HID_DEVICE_UP:pppp_U:uuuu`, `HID_DEVICE`, and the documented
`HID_DEVICE_SYSTEM_{MOUSE,GAME,KEYBOARD,CONTROL,CONSUMER}` values are recognized
as `unsupported_documented_form` when they supply no vendor identity. They are
not syntax errors or standalone target proof. A generic HID descendant with
proven target USB ancestry remains `related_hid`; it does not satisfy initial
readiness's own-VID/PID HID requirement. Unrecognized forms remain indeterminate;
the decoder does not pronounce arbitrary vendor-specific strings invalid.

The closed reason vocabulary is:

```
none, property_api_failure, unexpected_property_type, invalid_property_length,
invalid_multisz_termination, property_limit, unsupported_documented_form,
unrecognized_form, invalid_hardware_syntax, missing_hardware_id,
conflicting_identities, enumerator_unavailable, enumerator_malformed,
identity_bus_conflict, parent_unresolved, parent_cycle, parent_limit,
resource_limit, interface_lookup_failed
```

Each classification has `subreason`, `hardware_subreason` and
`ancestry_property_subreason`; snapshot failures use the same fixed vocabulary.
An ancestor property failure is labelled as a failed relationship, with its
property subreason and original ancestry return code, rather than misattributed
to the child's own hardware property. Bounded counts expose gaps without raw
IDs, symbolic links, instance IDs, serials or private paths.

## Present roots and initial readiness

`roots` counts distinct resolved roots in the independently enumerated PRESENT
set. `present_qualified_roots` additionally requires a successful root status,
DN_STARTED and no reported problem. `installed_inactive_roots` counts separately
proven nonpresent roots represented by inactive installed interfaces. Their
detail rows retain flags, status 13 and `installed_inactive=true`. That one
expected historical status does not contaminate live errors. Other failures,
active/nonpresent disagreement, failed/partial PRESENT enumeration and unknown
status remain incomplete.

`unresolved_roots` counts distinct internal node/root keys whose relationship or
current root qualification cannot be established; it is not an inferred number
of physical devices. `multiple_present_candidates` is the present root count
when it exceeds one, otherwise zero. `incomplete_identity_coverage` exposes
identity/relationship gaps. No indeterminate node becomes confirmed absence.

`initial_ready` requires complete coverage, exactly one qualified present root,
a present started target HID child with bounded successful USB ancestry, active
USB and HID interfaces, and no identity gap. Complete enumeration with no HID is
not initial readiness. The executable writes its marker only for `Ready()`.
Collection completeness remains a separate diagnostic measure and never grants
physical recovery acceptance. The validator rejects forged counters/readiness.

Arrival-v1's scoped HID interface and SDL's genuine wired DualSense opening are
independent retained observations. They neither identify which of the property
queries failed nor prove the missing CM parent relationship. No live re-query
has been performed. Historical HID correlation remains unresolved; v2 records
the missing property/ancestry evidence on a future separately authorized run.

## Process cleanup and endpoint coverage

The frozen coordinator waited three known roots, queried active=1, then closed
its KILL_ON_JOB_CLOSE job. Its 48-byte accounting structure and ActiveProcesses
offset 40 agree with the documented ABI; active is not TotalProcesses. However,
no member list was captured. A remaining child, delayed exit/reference release,
or another membership gap cannot be distinguished retrospectively.
`forced_termination=false` only excludes its explicit TerminateJobObject call;
it does not exclude implicit termination on last-handle close.

`boundary_cleanup_v2.WindowsJob` uses supported
[accounting](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_basic_accounting_information)
and [full job PID lists](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_basic_process_id_list),
bracketed by accounting queries, with bounded resizing/retries. Inconsistent,
failed or capped membership remains unknown. Root process handles are released
only after recorded exit. The tested cleanup policy stops observers before the
guard, waits descendants, records close-with-members/possible force separately,
and preserves the original first failure. It cannot certify an unknown job.
No automatic live launcher uses this module yet.

Owned inert Windows tests reproduce three exited roots plus one enumerated
living child. A file gate lets the child exit normally in one test; a second
test holds it until last job-handle close and independently observes its process
handle signal. These prove the warning can represent a real remaining child,
not that this was the historical member. Development also observed an actual
`conhost.exe` member accompanying an inert console worker on this machine.
Unknown console hosts must not be ignored. The final controlled fixtures use
the GUI subsystem and inherited stdin/stdout pipes to avoid unrelated console
lifetime. Future guard containment should use a separate owned job if its own
descendants would otherwise prevent attribution; uncertainty fails certification.
See [job inheritance and close behavior](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects).

The original endpoint trace has eight muted samples spanning 231 ms between
elapsed 2 and 233 ms, one endpoint token, no identity change and volume
0.320209712 unchanged. It establishes sampled state, not continuous mute.
Its relative clock has no exact QPC-origin anchor. The coordinator requests
endpoint stop first, alongside observer stops; exit ordering is not recorded
per helper. Thus startup/shutdown gaps and possible guard-before-observer exit
cannot be certified away, even though all known roots eventually exit.

`endpoint_coverage` requires correlated monotonic sample times and an explicit
scope. It reports sample-supported muted intervals, their unobserved/unverified
complement, endpoint-identity changes, independent per-token volume comparisons,
and known/unknown guard shutdown ordering. It never interpolates across a long
gap, switch, volume change, unavailable endpoint or unmuted sample, and never
claims continuous mute. It calls no audio/device APIs and changes no settings.
Future evidence must retain a real clock anchor and guard shutdown/observer
exit times; the old relative timestamps must not be promoted to exact QPC.

## Reproduction and next separately authorized experiment

Use Python 3.10 or later (3.12 tested). Build the existing root project in a fresh directory and run its full CTest
suite. Separately:

```powershell
cmake -S tests/pnp_readiness_v2 -B build/pnp-v2-host -DCMAKE_BUILD_TYPE=Release
cmake --build build/pnp-v2-host --config Release
ctest --test-dir build/pnp-v2-host -C Release --output-on-failure
```

The three new CTest suites exercise the native fake-provider collector and
closed-schema negative cases, portable cleanup/endpoint policies and Windows
owned-process job regressions. Linux skips only the three native Windows job
tests. The new workflow runs both platforms; the unchanged baseline workflow
runs the full existing host suites. These are host tests, not guest execution
or live notification/device tests. Local artifacts and final-head CI evidence
are under `build/live-av-v2/pnp-readiness-v2-001/`.

A future proposal is one bounded no-guest PnP-v2 plus unchanged SDL observation,
with separately contained read-only endpoint guard, exact guard clock/exit
anchors and full job membership captured before close. Require initial PnP,
SDL and mute readiness before giving any human USB instruction. If a legitimate
identity gap remains, stop and preserve it. Any proposed USB cycle retains a
30-second reconnect deadline and requires separate owner authorization. No
retry, guest, input injection or settings change is part of this implementation.

Original GPL-2.0-or-later licensing applies. No upstream engine or third-party
binary is imported or distributed. Existing source/relink/dependency release
holds remain open. Owner review is requested through the source/report; no PR
or merge is created for this task.
