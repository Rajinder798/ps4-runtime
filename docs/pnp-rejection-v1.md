# G4 PnP rejection attribution companion, version 1

This is an Issue #37 diagnostic prerequisite based on
`75112d25d1b6a2f3163378f2ad760a3c55150aeb`. Both preserved no-guest attempts remain
INITIAL READINESS FAILED; guest recovery remains FAIL 6/9. No physical recovery,
reconnect repair or completed G4 is claimed.

## Architecture and acceptance

The separate `tests/pnp_rejection_v1` project compiles the unchanged v2 core and
existing coordinator host project. `Acquisition` converts bounded raw properties
into the original Node using the original AssessProperty and compatible-list
decoder. `Companion` decorates the provider inside the original Collector snapshot,
writing separate `pnp-rejection-v1` JSONL. No new metadata supplies readiness.

`tools/pnp_rejection_v1.py` independently validates the closed companion schema
against the original v2 trace. Every histogram/count/readiness value and original
first failure/cleanup is cross-checked. Incomplete originals may be inspected,
never promoted to success. Host origins require an explicit reader option.

Frozen v1/v2 sources, validators, live coordinator, 975-input bundle, engine,
SDL, SDK, fixtures and physical entry point are unchanged. The new baseline file
pins 27 frozen v2/coordinator sources after LF normalization. No root CMake target,
registered launch, shortcut or setting selects this component. There is no live
executable or live CLI.

## Raw acquisition and shapes

Source supplies enumerations, raw typed properties, parent/status results, an
independent system-root lookup and the private keys needed only by the original
token policy. Tests feed raw MULTI_SZ through this path; they use no live source.

The optional Windows library reuses the original enumeration/key association.
It reads USB/HID properties with CM_Get_DevNode_PropertyW, edges with CM_Get_Parent
and startup/problem state with CM_Get_DevNode_Status. Other enumerators do not
trigger hardware/compatible/status queries; parent edges may still be needed.
Independent system-root proof uses
[CM_Locate_DevNodeW with a null ID](https://learn.microsoft.com/en-us/windows/win32/api/cfgmgr32/nf-cfgmgr32-cm_locate_devnodew).
Construction performs no queries. A separate Windows link test constructs and
destroys the inert adapter without calling any Source method. Query methods are
live-unverified and require separately approved integration.

Canonical HID VID/PID REV/MI/COL forms continue through v2 unchanged. The diagnostic
also recognizes the documented
[HID vendor/usage form](https://learn.microsoft.com/en-us/windows-hardware/drivers/cfu/cfu-firmware-update-simulation),
including public example `HID\VID_045E&UP:FA00_U:00F5`. It records
`documented_vendor_usage` / `vid_usage`; v2 still rejects it as
`invalid_hardware_syntax`. A partial entry alone never proves target VID/PID.

The inspector examines the entire bounded list: consistent complete pair,
partial-only context, full pair plus matching vendor context, contradictory
pairs/roles/revisions/partial vendors, unknown forms and invalid encoding remain
distinct. It can report a complete pair after the first rejected entry. Temporary
comparison values never enter the stream. API failure, unexpected type, bad byte
length, termination/entry limits and empty successful lists remain distinct.
The zero-based first rejected index is -1 when no decoded entry is attributable.

For ancestor property errors, the original resolver depth and ancestry reason
select the failed property. The independent longer topology walk cannot assign
a later bad property's failure to the original resolution.

## Topology and global scope

PRESENT USB target anchors require original own-ID/enumerator assessment,
successful status, DN_STARTED and no problem bit. A separate walk follows up to
eight edges despite a failed starting-node hardware property.

- `target`: the actual edge chain reaches a qualified target anchor.
- `other_branch`: a complete chain reaches the independently located system root
  without a target anchor, with a complete PRESENT set and at least one target anchor.
- `unknown`: unavailable/stale edge, cycle, depth/resource/time limit, absent target
  anchor or unavailable root proof. It stays potentially target-related.

These describe the known qualified target anchors in this snapshot, not every
unknown controller identity. Code 13 alone is not successful root termination.
A different own VID/PID does not prove a different physical parent.
Target-related HID with missing own metadata means a proved HID-enumerated
descendant with a qualification failure, not an automatically proved target pair.
Generic HID context is also emitted when v2 treats it as unmatched.

Snapshot-local counters replace internal handles and reset each snapshot.
Edges are sequential cached observations within the measured scan, not an atomic
topology snapshot. Future live integration must preserve that race uncertainty;
the diagnostic cannot certify a simultaneous topology or a physical cause.
Anchor records and bounded chains support independent consistency checks.
No raw DEVINST is serialized. Counters separately expose original indeterminate
attempts, target/other/unknown partition, generic-context unknown ancestry,
candidate inactive/nonpresent interfaces and target-related own-HID failures.
Original v2 installed-root accounting remains authoritative.

## Closed stream contract

Every row has exactly schema, contiguous sequence, monotonic native QPC, event
and the event's closed fields. Exhaustive field sets/vocabularies live in
`tools/pnp_rejection_v1.py`. Unknown keys/values, booleans used as integers,
duplicate JSON keys, nonfinite constants and truncated streams are rejected.

| Event | Fields/evidence |
| --- | --- |
| header | Origin, native frequency and exact budgets |
| snapshot_begin | Sample, begin, PRESENT completeness, target-root count |
| target_anchor | Local token, original target USB identity/status/presence proof |
| tree_anchor | Local token, successful independent root lookup |
| rejection | Original indeterminate attempt, source/enumerator, failed-property metadata and bounded topology |
| context | Generic HID metadata; original classification stays non-indeterminate |
| snapshot | Count/reason conservation, scope/context/omission/token totals, completeness, measured overhead, original readiness |
| first_failure | First companion-only resource/time/storage/unsupported-notification failure |
| cleanup | Original first-failure reason and cleanup result, independently cross-checked |
| summary | Writer/diagnostic status, recovery_accepted=false |

Property metadata: fixed API/key and CONFIGRET domain/code (0xffffffff is not
queried), DEVPROPTYPE, coarse byte-length class, list entry count/availability,
structural decode result, first rejected index, shape/order, list relationship
and complete-pair category. Original property, ancestry-property and resolution
reasons remain separate. Owner is own/ancestor/relationship; edge/boundary failure
does not invent an own-property error. Presence is 1/0/-1, distinct from interface
active/inactive flags. Detail completeness and ancestry completeness are separate.

## Privacy and limits

No raw IDs, serials, arbitrary substrings, private links, instance IDs, unrelated
vendor/product values, hashes or fingerprints enter the stream. Fixed categories
and coarse lengths reduce identifying combinations. Property buffers are
transient; cached facts hold fixed metadata/edges. The frozen original token
policy's private instance keys retain only its existing bounded lifetime.

| Surface | Bound |
| --- | --- |
| Devnodes / each interface enumeration | Existing 2048 / 2048 |
| Property/list | 16384 UTF-16 bytes, 64 entries, 1023 characters per string |
| Fact cache | 6152 entries; exhaustion becomes explicit resource limitation |
| Walk | Eight edges and cycle detection |
| Relationship tokens / detail rows | 128 / 64 per snapshot |
| Diagnostic deadline | 25 ms from snapshot start; subsequent walks omitted/unknown |
| Whole scan | Original 250 ms measures decorated acquisition/detail work; companion end also reports overhead |
| New raw notifications | Zero supported: no registration/callback intake; lookup explicitly fails |
| Writer | Exclusive create, at most 1 MiB / 4096 rows; 2048 bytes/four rows reserved |
| Reader | Bounded bytes/rows/line length and original-trace cross-check |

Limits preserve original aggregate attempts and explicit omitted counts.
Detail exhaustion makes diagnostic completeness false. Existing v2 queue/path
limits remain unchanged in its own tests. Synchronous API/scheduler/filesystem
stalls cannot be cancelled or represented as on time; end publication/flush may
also stall, so this is not a hard real-time guarantee.

Original cleanup remains caller-owned even if the companion writer fails.
An unwritable sink cannot guarantee a footer; writer status fails and the reader
rejects partial data. A host-only fault seam tests this and cannot be enabled with
live origin. Original first failure and cleanup remain in the separate v2 stream.

## Host build and verification

```powershell
cmake -S tests/pnp_rejection_v1 -B build/rejection-host -DCMAKE_BUILD_TYPE=Release
cmake --build build/rejection-host --config Release
ctest --test-dir build/rejection-host -C Release --output-on-failure
```

The project includes original v2/coordinator suites, raw-input fixtures,
source pins, schema/anchor/aggregate negatives, privacy and resource regressions.
The dedicated workflow runs Windows/Linux; Windows adds the inert link check.
Existing endpoint tests use fake providers; no audio device is opened.

The only executable mode is explicitly HOST TEST:

```powershell
pnp-rejection-host-v1 --host-test <fresh-synthetic-directory>
python -B tools/pnp_rejection_v1.py <companion> --original-v2 <original> --allow-host-test
```

The validator CLI reads files only. No live mode/coordinator upgrade/new physical
protocol is provided. Local builds, representative synthetic evidence, historical
replay, preservation and final-head CI records are retained under
`build/live-av-v2/pnp-rejection-attribution-v1-001/`.

Original GPL-2.0-or-later applies; no engine/third-party binary is imported or
distributed. Existing source/relink/dependency release holds remain open.
Issues #33/#37/#39 stay open; no PR/merge is created.

Target-scoped readiness is a separate future policy requiring proof that every
excluded unknown cannot belong to the target. It is not implemented here.
The smallest future verification proposal is exact source/binary attestation and
review before separately authorizing any bounded live collection. This task
authorizes no such integration or session.
