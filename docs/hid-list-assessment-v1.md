# G4 offline HID list assessment and deterministic budget tests, version 1

Issue #37 prerequisite, approved baseline
`17a4b954fc2a4911e5118a21206cecee01dfac0f`. This is a candidate parser policy
and host-only investigation. No live entry point selects it. The connected
snapshot remains FAILED, exit 1; guest recovery remains FAIL 6/9. Issues #33,
#37 and #39 stay open. Parser success does not repair reconnect or complete G4.

## Evidence, deductions and synthetic examples

The sealed connected report under
`build/live-av-v2/pnp-snapshot-connected-001-review/` establishes one qualified
PRESENT USB parent, two USB functions, zero original qualified HID children and
zero qualified active HID interfaces. Companion token 23 appeared as a PRESENT
devnode and active HID interface, with independently proved chain [23, 24, 1].
These are two attempts on one node. Its six decoded hardware-ID entries included
a complete target pair and consistent vendor/usage context; frozen v2 first
rejected contextual entry index 2. Its own started/problem-free status was not
established by those rejected-property records. Original global coverage failed.
The retained shape categories cannot re-run this new policy on the physical
property: its exact six strings and every usage/component value are unavailable.
In particular, the old companion's vendor-context consistency category does not
independently establish all stricter usage-consistency checks in the candidate.
Whether that original property would pass this new assessor remains unverified.

The public example below is **HOST TEST**, assembled from documented grammar.
It demonstrates those safe shape characteristics; it is **not the unrecorded
physical six-string list**. Neither its revision/interface/usage values nor its
duplicate final generic entry are inferred from the physical evidence.

```text
HID\VID_054C&PID_0CE6&REV_0100&MI_03
HID\VID_054C&PID_0CE6&MI_03
HID\VID_054C&UP:0001_U:0005
HID_DEVICE_UP:0001_U:0005
HID_DEVICE
HID_DEVICE
```

The host fixture encodes all six as one bounded UTF-16 MULTI_SZ property. Frozen
`AssessProperty` rejects it with `invalid_hardware_syntax`; frozen `AssessIds`
succeeds on entries 0–1 and fails when index 2 is added. New `hid_list_v1::Assess`
returns `complete_with_consistent_context`, `target_hid`, first_context=2 and
first_issue=-1. This is an own-property syntax assessment only.

## Candidate policy and supported grammar

`tests/hid_list_assessment_v1/assessment_v1.*` is a separate namespace/API. It does
not edit frozen v2, rejection-v1, the snapshot harness, their configs or bundles.
Its input has API code, property type, declared byte length and a span of explicit
`char16_t` units, so Linux's different `wchar_t` width cannot change decoding.
It requires successful API status and DEVPROP_TYPE_STRING_LIST (0x2012), bounded
even length and valid UTF-16. It consumes the entire declared MULTI_SZ: one-NUL
and two-NUL empty properties are distinguished from malformed termination;
interior empty entries, hidden nonzero tails and excessive trailing terminators
are rejected. Unpaired surrogates fail encoding; valid non-ASCII text remains
outside the supported identifier grammar. ASCII matching ignores case.

The supported subset follows Microsoft's
[HIDClass collection IDs](https://learn.microsoft.com/en-us/windows-hardware/drivers/hid/hidclass-hardware-ids-for-top-level-collections)
and [standard USB identifiers](https://learn.microsoft.com/en-us/windows-hardware/drivers/install/standard-usb-identifiers).
HID full entries contain VID/PID, optional REV, optional MI, optional COL, in that
order, with fixed hexadecimal widths 4/4/4/2/2. USB full entries have VID/PID,
optionally parent REV or function MI; combined USB REV+MI is outside this narrow
policy. Revision-free and matching revision-specific variants may coexist.
Across full entries, bus, VID/PID and the presence/value of MI/COL must agree;
two supplied revisions must agree. This does not assume missing MI/COL values
are wildcards or infer one interface from another.

Microsoft's [CFU sample](https://learn.microsoft.com/en-us/windows-hardware/drivers/cfu/cfu-firmware-update-simulation)
documents the partial form `HID\VID_hhhh&UP:hhhh_U:hhhh`. It supplies vendor/usage
context, **no product identity**. This assessor permits it alongside full HID
identity only when vendor and every supplied usage pair agree within the same
property. Supported generic contexts are HID_DEVICE and
HID_DEVICE_UP:hhhh_U:hhhh; explicit usage context must agree. HID context mixed
with USB identity is conflicting. The documentation establishes the syntax; the
whole-list consistency rule is this versioned, conservative candidate policy,
not a claim that every Windows hardware-ID list has this exact structure.

Documented but unimplemented special-system/USB class/composite context is
`unsupported`, not silently ignored. Other transport families, unknown prefixes,
arbitrary suffixes, reordered or duplicated components are not accepted by
assuming that an earlier complete pair wins. No full identity survives a list
veto. Output contains fixed categories and counts, not raw vendor/product values,
serials, paths, arbitrary text or hashes of device identities.

| Whole property | Candidate result | Own target HID identity |
| --- | --- | --- |
| Complete consistent target HID pairs | complete | yes, syntax only |
| Same with consistent documented context | complete_with_consistent_context | yes, syntax only |
| Vendor/usage context without PID | partial_context_without_product | no |
| HID_DEVICE alone | generic_only | no |
| Complete pair plus unknown/special unsupported entry | unsupported | no |
| Conflicting VID/PID, revision, MI/COL, vendor context or usage | conflicting | no |
| Known prefix with invalid component grammar | malformed | no |
| Unknown entry without a complete identity | unrecognized | no |
| Empty successful property | empty | no |
| API/type/length/UTF-16/termination error | distinct property error | no |
| Over byte/string/entry limit | property_limit | no |

Bounds are 16,384 property bytes, 64 strings and 1,023 UTF-16 units per string.
Scanning/allocation is bounded by that declared property; full-list comparison
has at most 64 entries. Buffer capacity beyond declared bytes is not property
content. API/type errors are classified before buffer access. Invalid length,
encoding and termination are separate failures. A rejected list's usable identity
is always `none`, including when another entry contains the target pair.

## Qualification remains independent

`OwnTargetHid()` can only indicate a complete consistent own hardware-ID list.
It has no status, PRESENT, ancestry, interface or global coverage inputs and
cannot grant readiness. JSON exports always say HOST TEST, readiness_granted=false
and recovery_accepted=false. No Windows property adapter or device query exists
in the candidate library or test drivers.

A hypothetical HOST TEST provider passes the new assessment into the unchanged
frozen Resolver/Collector. Separate cases remove startup status, DN_STARTED,
problem-free status, proven ancestry, own product identity, PRESENT state,
active USB/HID interfaces or global coverage. Each prevents initial readiness.
A synthetic complete-proof control passes only with independently supplied
evidence for all requirements. This bridge is confined to test code and is not
a live policy migration. A related HID or partial context alone cannot qualify.

## Deterministic accounting of the frozen companion

The connected native QPC trace records original scan 26.6125 ms, companion scope
26.7343 ms, snapshot-begin publication after 20.0275 ms, and companion first
failure at 25.0096 ms after its own begin. Original Coverage=1 follows 0.9140 ms
later. Forty of fifty attempts were retained; ten properties were omitted.
Aggregate subtraction is not reconstruction of omitted entries.

Frozen `Companion::Devnodes` starts its deadline before initial enumeration,
independent system-root lookup and cached property/root discovery. Those stages
precede snapshot-begin publication. The physical trace bounds their combined
scope but does not measure individual enumeration, OS property/status calls,
cache allocation, anchor preparation or scheduler/storage costs. The retained
rejection timestamps do not isolate serialization, traversal and cache costs.
The exact Windows cause of the preparation cost remains unknown.

The new standalone CMake project generates a **test-only copy** of frozen
`pnp_coverage_v2.cpp`, renaming exactly the Ticks/Frequency definitions to unused
names. Every Collector/Trace call site and the entire compiled rejection-v1
source stay unchanged. The new fake-clock definitions provide the originals'
symbols. No historical file is rewritten; this copy is never linked into a live
target or an attested worker. The fake Source has no Windows acquisition code.

The clock uses 10,000,000 ticks/second, fixed start, and one 100 ns tick per read.
Only explicit scheduled provider costs advance additional time. Negative
advances/reset steps and overflow are rejected. Filesystem/scheduler execution
does not advance the fake clock. This is controlled accounting, not measured
Windows performance. Two identical schedules produce identical complete native
streams and schedule ledgers within one process. Old independent readers inspect
all complete streams, preserving native host-test origins and readiness rules.

Fourteen schedules exercise initial enumeration, system-root lookup, qualified
root discovery, raw-property acquisition, parent traversal, deadline before any
detail, deadline midway through details, original 250 ms overrun, both first-failure
orders, cleanup errors, late writer errors and exact repeated QPC behavior.
One count fixture generates 27 node + 23 interface failures with 22/7/21 reasons,
retains 40, omits 10 and keeps original aggregate counts intact. These synthetic
records do not fill any physical evidence gaps. They include a six-string target
HID encountered as a devnode and active interface with independently supplied
chain [23,24,1] in the separate qualification fixture.

The tests also expose an accounting limitation: after the final diagnostic
attempt, an interface-enumeration delay can take the scope past 25 ms while
remaining below 250 ms, without `diagnostic_time_limit`. Frozen EndSnapshot checks
250 ms, not the separate 25 ms deadline. A 251 ms tail instead yields original
Overhead=9 before companion scan_budget_exceeded. The forty-of-fifty fixture
yields companion diagnostic_time_limit before original Coverage=1. Later cleanup
or writer failures cannot replace either retained first failure; a missing writer
footer makes the companion invalid even if a first-failure row survives.

## Proposed timing design, not implemented or connected to live work

A separately versioned diagnostic design should retain one **total 25 ms scope**
including preparation, record explicit stage boundaries, and check the deadline
before/after each diagnostic acquisition and at scope end. It should not reset
the clock after preparation or raise the limit. Once exhausted, stop extra
diagnostic ancestry/property work, retain original aggregate counting, explicitly
count omitted details/unknown attribution and keep the original 250 ms scan
independent. A final scope check must expose overrun after the last attempt.

Work stays bounded by existing enumeration caps (2,048 PRESENT nodes and two
2,048-interface lists), bounded acquisition cache, 64 details, 128 relationship
tokens and eight parent edges per walk. A failed/expired walk cannot establish
another-branch proof. Cached facts are sequential observations, not atomic
topology. The original shared 32,768 Source-call cap, five-second worker and
two-second cleanup supervision must remain. A synchronous call can overrun a
deadline before returning; these are detection/containment budgets, not hard
real-time guarantees. Unknown preparation substage costs require future approved
instrumentation, not invented per-API timings. No alternative design is installed
by this task; live budgets and first-failure/cleanup behavior remain unchanged.

## Reproduction and historical preservation

```powershell
cmake -S tests/hid_list_assessment_v1 -B build/hid-host -DCMAKE_BUILD_TYPE=Release
cmake --build build/hid-host --config Release
ctest --test-dir build/hid-host -C Release --output-on-failure
```

This includes all existing v2, rejection, snapshot and no-guest host suites.
Windows-only tests use inert jobs and fake providers; they perform no real device
or audio query. The unchanged root project separately supplies the full original
baseline suites. The new workflow runs Windows/Linux and uploads synthetic logs,
ledgers and failures only, with no executable or device identities.

Optional `HID_V1_EVIDENCE` points to a **fresh** parent for retained synthetic
evidence. Never reuse it for another test run. New native raw-property transport
has bounded stdin so cap tests do not exceed Windows command-line limits. All
failed development results must remain in the local implementation report.

`tools/replay_hid_assessment_v1.py` verifies the captured preservation baseline
and all 3,293 bundle references, reads both connected no-guest attempts and both
one-shots, rechecks the original six guest images/journal/witnesses and asserts
the strict guest failure. It writes exclusively to a fresh output file. It does
not call a runner, execute a historical helper or acquire device/audio state.
The disconnected snapshot retains its FAILED verdict and separate operator
supplement; zero PRESENT roots while disconnected cannot prove hardware failure.
The connected confirmations, original native hashes, job cleanup records and
ten missing details remain unchanged. All 975 inputs and sealed historical sets
are protected, including current v2/rejection regression evidence.

Final source commit, changed paths, local/hosted results, development failures,
binary/source hashes, exact preservation and CI logs are recorded separately in
the fresh `build/live-av-v2/hid-list-assessment-v1-001/` implementation report.
No final-head CI result is implied by this documentation or workflow definition.

The smallest next gate is independent review of this candidate grammar and
bounded stage-accounting proposal against the retained metadata and negative
fixtures. Any live policy migration, property instrumentation or connected test
requires separate review and authorization. No PR, merge, guest/engine/SDL
execution, physical action or settings change is part of this task. Windows mute
is left untouched, without a fresh audio query. Original GPL-2.0-or-later applies;
no new third-party dependency or engine distribution is introduced. Existing
release/source/relinking holds remain open.
