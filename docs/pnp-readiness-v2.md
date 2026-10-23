# PnP Readiness v2 foundation

This standalone diagnostic foundation is a G4 prerequisite for Issue #37. It adds
bounded Windows PnP classification and an independent file-only validator. It is
not connected to a game, SDL observer, one-shot snapshot harness or launcher.
Building and passing host tests does not establish real-device readiness,
controller reconnect recovery or G4 completion. Issues #33, #37 and #39 stay open.

## Isolated scope and provenance

The foundation was initially extracted from approved G4 source
`418692a41bb11df5d81058880b4cad6549e0c81f` onto main
`b3b30bde5f46263a9e03ba559b87c421edc94a57`. The collector, independent validator and host regressions now correct the reviewed
active-interface false-positive; parser policy and Windows backend/observer remain
unchanged. The standalone CMake scope and documentation are adapted. No existing main file is changed, including its
root CMake, workflows, launchers, settings, engine/SDK/SDL or guest fixtures.

The standalone build depends on C++20, CMake 3.20+, Python 3.10+ and the standard
library; Windows targets additionally use Windows 10 SDK SetupAPI/ConfigMgr and
normal system libraries. There is no dependency on the older PnP v1 sources or
other unpublished G4 modules. Process-tree cleanup/endpoint analysis, rejection
attribution, the candidate HID-list assessor and diagnostic stage ledger are
excluded. The independent audit's NO-GO for new Windows diagnostic integration
remains in force; this extraction does not integrate those components.

## Classification and readiness

The policy keeps API errors, property type/length/termination/caps, unsupported
forms, malformed grammar, conflicting identities and unresolved ancestry as
separate closed reasons. Hardware lists are bounded to 16,384 bytes, 64 strings
and 1,023 code units per string. Empty lists supply no identity. A single-NUL
empty MULTI_SZ is classified as missing identity. Vendor forms use ASCII case
normalization, four hexadecimal VID/PID/REV digits and two MI/COL digits in
supported order. A complete list must have consistent bus, VID/PID and role;
conflicting nonempty revisions are rejected.

Only VID 054C/PID 0CE6 can be a target candidate. Generic/class/usage context
alone never supplies a missing product identity. Other-vendor HID identity
cannot become target identity solely through target USB ancestry. A generic
related HID is distinct from a qualifying HID child.

PRESENT devnodes are enumerated independently from installed USB/HID interfaces.
An inactive interface with independently proved nonpresent node/root is counted
as installed history, not a second present controller. Unknown or incomplete
presence remains a coverage gap. The expected historical status code 13 is
retained without treating that proved inactive history as a live status failure.

`initial_ready` requires complete global coverage, exactly one qualified PRESENT
USB parent, a PRESENT own-target HID child with successful bounded USB ancestry,
started/problem-free own and root state, and active USB and HID interfaces.
Generic descendants, partial IDs, installed history and unresolved observations
cannot fill missing proof. Collection completeness is separate from initial
readiness; neither grants physical recovery acceptance. The active USB/HID totals
remain observational counts, including generic RelatedHid interfaces. Readiness
additionally requires an active interface whose node/root pair matches a
qualifying PRESENT devnode of the appropriate own-target role, with current own
and root startup/ancestry proof. An inactive qualifying child plus a different
active generic HID, or an active interface on a non-PRESENT node, cannot pass.
A different/unresolved target root still fails global coverage.

Snapshot work retains its 250 ms budget, two-second cadence and fixed resource
limits: 2,048 nodes/each interface list, 64 relevant rows, 128 local tokens,
eight ancestry edges and 256 queued notifications. Synchronous API/storage calls
can return after a deadline; these limits are detection bounds, not hard
real-time cancellation. Original first failure is write-once; cleanup is recorded
separately. The stream schema is `pnp-coverage-v2`; never mix versions.

## Host verification and safe use

From the repository root, in a fresh build directory:

```powershell
cmake -S tests/pnp_readiness_v2 -B build/pnp-v2-host -DCMAKE_BUILD_TYPE=Release
cmake --build build/pnp-v2-host --config Release
ctest --test-dir build/pnp-v2-host -C Release --output-on-failure
```

The two suites are `pnp-policy-v2` and `pnp-evidence-v2`. They use fake properties,
synthetic streams, malformed/counter/clock/cap/privacy negative cases and an
in-memory Windows callback test. They never construct WindowsProvider, register
notifications or query devices. On Windows the observer/backend compile; the
observer is not invoked by CTest. The existing main baseline suites run separately.
The new CI workflow runs both Windows and Linux. Linux cannot establish Windows
API behavior. Local/hosted results and exact head are recorded in the Draft PR.

The Windows-only observer is an explicit research executable. It rejects invalid
arguments before registration/enumeration and requires its authorization flag,
fresh distinct evidence/stop/ready paths and a bounded duration. That flag is an
operator guard, not a security sandbox or present authorization. No automatic
launch path is added. Any future real observation requires separate human
approval and separately reviewed process ownership/cleanup; this foundation does
not contain a production session supervisor. No live invocation is needed or
authorized for reviewing this PR.

`tools/pnp_coverage_v2.py` reads saved JSONL only. Its strict schema checks order,
closed fields/types, counters, readiness, failure and cleanup consistency, size
limits and privacy categories. HOST TEST evidence is explicitly marked and
requires opt-in inspection. `recovery_accepted` remains false.

## Known limitations and historical failures

The frozen whole-list parser still rejects documented HID vendor/usage context
such as `HID\VID_vvvv&UP:pppp_U:uuuu`, including when another entry contains a
complete VID/PID. This PR does not import the newer assessor or relax that policy.
Unsupported/unknown properties and ancestry keep global coverage incomplete.
Windows properties, state and topology are observed sequentially, not atomically;
cache reuse and later notification lookups are not physical continuity proof.

The retained connected initial snapshot remains FAILED (exit 1, readiness false).
It recorded one qualified PRESENT USB parent but no qualified HID child/active
HID interface, with 27 node and 23 interface classification rejections. The
separate guest reconnect outcome remains FAIL 6/9. Those historical sessions used
later infrastructure absent from this PR; they are limitations/provenance, not
runs of this extracted branch. The earlier disconnected snapshot had an unmet
initial precondition and does not establish Windows enumeration/hardware failure.
No failure or historical artifact is rewritten by this extraction.

Original raw HID strings, rejected-node startup state, omitted properties and
reconnect cause remain unresolved. Passing fake-provider readiness cases cannot
promote those historical outcomes. The later rejection companion's shared-cache
behavior and the stage reader's incomplete-stage acceptance are not included.
No new production bundle is created and no Python identity is repinned. The old
production bundle's Python identity mismatch remains an independent live-use hold.

## Privacy, licensing and review boundary

Output contains fixed categories, public error/type/length metadata and
capture-local tokens, never raw hardware IDs, serials, instance paths or device
fingerprints. Transient opaque notification paths are only lookup input; relevant
instance keys remain internal. Nothing accesses audio or modifies Windows state.

Original GPL-2.0-or-later notices and the root LICENSE apply. No external engine,
third-party implementation, binary, game/firmware/keys or new dependency is
imported. Existing redistribution, source/relink and security holds remain open.
Owner review and relevant final-head host CI are required before any merge;
Draft status is intentional. Proposed PR #2 is the separately reviewable bounded
process-membership/cleanup and file-only endpoint-coverage module with inert host
tests, without launching a real observer or migrating parser policy.
