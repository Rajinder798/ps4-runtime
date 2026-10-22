# G4 one-shot PnP rejection snapshot harness v1

Issue #37 prerequisite, based on `c449a26c288750eaf40c49a41a3a4ef1e635b752`.
This standalone diagnostic does not fix reconnect, grant physical acceptance or
complete G4. Both historical no-guest sessions remain INITIAL READINESS FAILED;
guest recovery remains FAIL (6/9). No live query is authorized by implementation
or host-test completion.

## Source and evidence boundaries

`tools/pnp_snapshot_v1.py` is the supported supervisor entry point. It verifies
an externally reviewed SHA-256 build bundle, pins every listed file against
write/delete during execution, creates fresh output and atomically assigns the
selected worker to a KILL_ON_JOB_CLOSE Job Object before its first thread runs.
It reuses the unchanged `coordinator_windows_v1.ProcessAPI` and
`boundary_cleanup_v2.WindowsJob`; no endpoint/SDL/guest process exists.

`tests/pnp_snapshot_v1/snapshot_v1.cpp` calls exactly one unchanged
`pnp_v2::Collector::Snapshot`, through the existing companion's `Acquisition`
and `Companion` Provider. `BoundedSource` wraps the versioned read-only Source.
The host worker links no Windows acquisition library. The Windows worker links
the existing versioned `rejection_v1::WindowsSource`, whose construction is inert.
Its real Source methods remain unverified by this offline task.

Each worker owns two separate exclusive, append-only files:

- `pnp-v2.jsonl`: unchanged `pnp-coverage-v2` fields, classification and snapshot
  readiness, original first failure and provider cleanup.
- `rejection-v1.jsonl`: unchanged `pnp-rejection-v1` metadata, correlated to sample
  1, original reason conservation, own/ancestor ownership and bounded topology.

The supervisor separately owns `session-v1.jsonl`, `result-v1.json`, stdout and
stderr. Its job/tree cleanup is independent of the native provider-cleanup code.
An original native cleanup code zero does not prove process-tree emptiness.
An unavailable/corrupt companion cannot rewrite a flushed original failure.

No notifications are registered or processed. Frozen v2 observer completeness
requires successful registration/unregistration; therefore the native final
observer coverage/collection summary is deliberately false. Original snapshot
`coverage_complete` and `initial_ready` remain intact. A ready one-shot snapshot
does not become a complete observer collection. No fake registration rows are
emitted, including in host tests. Readers use original `require_complete=False`
only to inspect evidence; `recovery_accepted` remains false everywhere.

The original one-parent, genuine own-VID/PID HID, PRESENT/started/problem-free,
active USB/HID and global identity requirements remain authoritative. The
independent one-shot reader cross-checks the native snapshot's readiness against
those same requirements. Generic HID, documented partial vendor/usage forms,
unknown ancestry and SDL opening cannot supply own-ID qualification. No SDL is
linked or initialized. Old validators, sources, binaries, bundle and coordinator
selection remain unchanged.

## Explicit future query gate

The default supervisor has no execution mode. `--verify-bundle` and `--inspect`
read files only. `--host-test SCENARIO` selects the separate synthetic worker and
cannot be combined with live authorization. HOST TEST bundles cannot enter the
production path. Real execution would require BOTH `--run-initial-snapshot` and
`--authorize-one-initial-snapshot`, an approved production bundle hash and a fresh
output directory. It is Windows-only and has no fallback to unowned Popen.

Only after successful source/binary/preservation verification and read pinning
does the supervisor mint a fixed, single-use permit in the fresh directory.
The internal Windows worker requires its explicit authorized worker mode and
consumes the permit by same-directory rename before calling any Source method.
It then creates both exclusive streams before the first query. A second worker
cannot reuse the consumed permit. Calling the internal worker directly is not
the supported attested workflow; this operator opt-in gate is not a security
boundary against a caller who deliberately creates authorization files or edits
the program. No live invocation or valid live permit is part of host tests.

`--identity-only` emits the compiled source commit without constructing a Source.
`--inert-link-check` constructs/destroys WindowsSource without calling any query
method. The bundle builder uses the former; CTest uses the latter. Compilation,
identity output and inert linkage do not verify real adapter operation.

## Lifetime, first failures and limits

The logical Source call cap is 32768, checked before each call; a 250 ms deadline
is checked before and after each synchronous Source call. Existing per-enumeration,
property, ancestry, cache, token and detail limits remain unchanged. This counts
Source calls, not every underlying SetupAPI/CM operation. Those existing bounded
enumerations retain their own caps. The companion retains its 25 ms deadline and
the unchanged collector measures a 250 ms scan.

The supervisor allows five seconds of worker/job execution, followed by at most
two seconds of cleanup polling/containment. Normal root exit is insufficient:
it releases waited root handles and requires exact accounting plus the full PID
list to prove the entire job empty before closing it. Short-lived owned children
(including Windows console hosts) remain accounted for until exit. A child that
outlives the execution budget, an unknown membership query, spawn/ownership error
or timeout yields a failure and bounded job containment. Forced/unknown/abnormal
outcomes are explicit and never certified normal cleanup. There is no retry.

Native first-failure rows are flushed by the original writer before native
cleanup. The supervisor retains bounded, fully terminated native failure rows
even if a later writer/footer fails; such a row is marked unvalidated until both
independent readers pass. It cannot establish readiness. Original and companion
first reasons, stream validation errors and job cleanup errors remain separate.
The first failure's domain/reason is never replaced by a subsequent cleanup
failure. First-failure evidence precedes `cleanup_begin` when the sink permits.

The session journal is capped at 128 rows/64 KiB, including complete bounded job
member lists. Overflow/write failure marks evidence invalid. Companion and v2
writers retain 1 MiB/4096 and 8 MiB/20000 caps; readers reject missing, partial or
corrupt streams. A sink failure cannot guarantee an on-disk footer or failure
record. The result reports journal failure independently. Fresh/exclusive output
prevents overwriting stale evidence. All partial outputs are retained.

Synchronous Windows APIs, hashing, process creation, storage operations and kernel
cleanup calls can stall. The five-second execution scope begins after preflight
and spawn; cleanup polling is bounded separately. These are detection and
containment budgets, not a hard real-time OS guarantee. The native query deadline
does not cancel an already-blocked API; the owned supervisor bounds that worker.
Preflight is byte/count bounded rather than guaranteed to finish in fixed time.

Device privacy remains the companion's fixed categories and local tokens. No raw
IDs, private device paths, serials, DEVINSTs or identity fingerprints are added.
Source/binary hashes are provenance, not hashes of device identity. Job PIDs are
process ownership evidence and never used to infer a controller identity.

## Immutable bundle

`tools/build_pnp_snapshot_v1.py` performs offline assembly only. A clean committed
source tree is required. Both new binaries must report that exact compiled commit
with `--identity-only`; stale binaries fail assembly. Sources, executable copies,
toolchain metadata and compiler/SDK dependency inputs are hashed. The externally
reviewed bundle hash identifies immutable contents; copies and manifests use
fresh exclusive paths. Historical executables are referenced, never replaced.

The config pins 39 baseline sources and 21 preserved manifests. Bundle assembly
checks the exact 975-input baseline and expands preserved manifests into an
independently verified file union, retaining exact mtimes wherever originally
recorded. Read-only verification checks every file hash/size, preserved mtimes,
path containment, closed schema, exact policy and input references. A production
bundle also pins the Python executable identity. Bounds are 8 MiB per bundle,
8192 file references, 1 GiB per file and 4 GiB total declared input bytes. Host
bundle overrides are accepted only in explicit host verification/execution.

An externally reviewed hash is the trust anchor. This is reproducibility and
tamper detection for the supported workflow, not an OS security sandbox or a
claim of a reproducible byte-identical rebuild. The binary embeds the Git commit;
the retained build/dependency logs supply additional build provenance.

## Host-only reproduction and verification

```powershell
cmake -S tests/pnp_snapshot_v1 -B build/snapshot-host -DCMAKE_BUILD_TYPE=Release
cmake --build build/snapshot-host --config Release
ctest --test-dir build/snapshot-host -C Release --output-on-failure
```

Use a fresh build/output directory. Visual Studio executables are under Release;
Ninja executables are directly under the build directory. Direct HOST TEST
workers require a precreated fresh empty directory. CTest includes the old v2,
companion and no-guest suites, new raw-property tests, portable fake job tests,
Windows inert-owned tree tests, query-budget checks and Windows inert linkage.
The dedicated workflow runs Windows/Linux. Hosted root baseline workflows remain
separate; no actual engine/guest or device test is implied.

All generated evidence is HOST TEST. Scenarios cover qualified and missing HID,
inactive history, target/other/unknown rejection topology, partial/full context,
encoding/missing/unsupported forms, synthetic 27+23 attempts with 22/7/21 reasons,
limits, stale paths, corrupted streams, hash mismatches, writer errors and job
lifetime/cleanup. Synthetic counts do not reconstruct the fifty missing physical
rejection attempts. Historical replay reads only retained files.

No new dependency is imported; original GPL-2.0-or-later applies. No engine,
SDK, SDL, fixture, registry, driver, power or audio setting changes are included.
Release/source/relinking holds and Issues #33/#37/#39 remain open. No PR/merge is
authorized. Existing launchers do not select this standalone harness.

The next proposal, requiring separate user authorization, is ONE initial snapshot
through the reviewed production bundle, with the two native streams and complete
owned-job cleanup. No unplug/reconnect, input, notification monitoring, SDL,
guest or endpoint query is needed. Preserve a failed snapshot without retry and
analyze its rejection shapes and ancestry offline. Live timing, Windows adapter
behavior and the reconnect cause remain unknown until separately verified.
