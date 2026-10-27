# Issue #39: Option A sampled fixed-inventory acceptance contract

This is a HOST-validated software policy for a future separately authorized
automated Windows live-v2 acceptance. It is not permission to launch an engine,
observe live endpoints, change settings or run a physical test. G4/Windows live
integration remain NO-GO and G5 remains frozen.

The automated `tests/live_av_v2_guest_tests.py` entrypoint requires
`--endpoint-inventory <file>` before creating outputs or an observer. A future
independent machine preflight must verify every active render identity and the
Console, Multimedia and Communications default identities, then supply that
explicit expectation. The file is a test acceptance input, not a Windows setting
and not an authorization credential. No real device inventory was acquired here.

An inert example (these are fake endpoint identities):

```json
{
  "schema_version": 1,
  "scope": "all-active-render",
  "inventory_policy": "fixed",
  "endpoint_identities": ["FAKE-A", "FAKE-B"],
  "default_role_identities": {
    "console": "FAKE-A",
    "multimedia": "FAKE-B",
    "communications": "FAKE-A"
  }
}
```

The bounded manifest admits 1–32 unique identities, each at most 1024 UTF-8 bytes,
with exactly all three roles referring to members. Duplicate/missing/unknown
metadata is rejected. Accepted expectations are copied into immutable internal
identity/role sets and a canonical digest; later caller mutation cannot change
them. A separate qualified preflight must establish authenticity/completeness of
the expected inventory and pin the exact rebuilt observer/source identities.

`FixedMutedEndpoint` explicitly selects `--watch-all-render-fixed`. The native
all-active-render provider uses the existing read-only enumeration and volume/
mute/default queries. Its fixed guard pins the first complete observation, rejects
any addition/removal or role change and retains the original guard failure without
retry. Before allowing any worker, the Python reader independently matches that
complete first observation against the explicit expected identities/roles and
requires every endpoint active, muted and at its invariant observed volume.

This mode extends schema-2 sample/summary records with an explicit
`inventory_policy="fixed"` marker. Samples also include acquisition start/end
Unix timestamps and a measured acquisition span. Old default-only schema-1 and
old dynamic schema-2 reports lack this contract and cannot prove Option A.
Identity tokens, every endpoint field, all role memberships, timestamps, counts,
footer and JSON member uniqueness are checked. Partial/malformed UTF-8/JSON,
unknown endpoints, unmute, missing data, volume drift, replacement/truncation,
failed native events and incomplete/premature completion fail closed.

The fixed-only acquisition, inter-sample gap and latest-observation bounds are
200ms. This is a finite software evidence bound (eight requested 25ms polling
intervals), not a measured Windows scheduling guarantee. Timestamp checks apply
to the whole acquisition start, not merely a fresh footer. The runtime reader
is incremental with bounded state; final evidence is fully re-read after verified
observer exit. The report cap remains 32MiB; fixed samples also have a 32768-record
cap. At least two complete samples and a matching passed fixed footer are needed
for terminal acceptance. Slow/blocked queries or scheduling may fail the policy;
no threshold or existing timeout was loosened to pass tests.

The automated driver requires the fixed contract again before each worker,
checks during supervision, then requires confirmed observer cleanup and final
fixed evidence before publishing a successful overall summary. Individual case
results are not complete Option A acceptance without that final summary. Guard
failure is sticky even if a caller catches it. Containment still attempts stop,
wait, kill and final exit confirmation when an earlier stop write/query fails.
The original FIRST exception/cause is retained; later cleanup diagnostics are
bounded. The driver reuses the reviewed D1 capture/projection/result/fallback
adapters, including explicit persistence-loss handling. File existence or a
passed native footer alone does not establish process cleanup or durable storage.
Both caller layers use the D1 canonical `supervision_diagnostics` and persistence
fields so the real fallback journal carries bounded cleanup SECOND records too.
An additional bounded A1 FIRST descriptor retains available observer-exit codes
in that marker. `included` describes the projected payload, not fsync durability;
if both destinations fail, the original exception reports unsuccessful persistence.

Historical `muted_endpoint.py`, its schema-1 default observation and schema-2
dynamic observation remain unchanged. `hotplug_endpoint.py` also remains
unchanged: it is a separate, explicitly permitted per-seen-default protocol and
does not establish Option A. The physical driver's permission/transport/reader
semantics are preserved; added result labels explicitly deny Option A acceptance.
No deliberate live-audio hotplug is permitted under the fixed policy.

Sequential COM reads are not an atomic OS snapshot. Polling, wall-clock/steady
timestamp checks, failure detection and process termination do not prevent
Windows from routing audio to an endpoint before the next observation. A 200ms
check does not interrupt an indefinitely blocked COM or filesystem operation.
No instantaneous/acoustic silence, real-time scheduling, routing exclusion or
safe hotplug guarantee is claimed. Actual observer/query latency, completeness,
identity/source attestation, fresh machine mute inventory, routing/quiescence and
process cleanup need separate qualification and explicit owner authorization.
No observer instance, audio device, controller, USB or guest was acquired here.

HOST regressions include pure native providers, strict reader negatives, actual
driver/wrapper coordination with inert process boundaries, FIRST/SECOND and
publication-failure tests, legacy-scope controls, and unchanged D1 regressions.
Passing these tests does not complete the independent source review, hosted CI,
live Windows integration, physical readiness or license/release gates.
