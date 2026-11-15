# Per-title save store (isolated title profile)

Status: **steps 1–3 done. The step 3 guest run passed on its first attempt (15
November 2026).** The store is not yet used by the registered launch contract. This is the "isolated title profile" part of the roadmap's G4 item
("Add input, audio, save storage, and an isolated title profile"). It is not save
support, G4 progress or a compatibility claim.

## Problem

The [save-roundtrip run](save-roundtrip.md#guest-run-result-15-november-2026)
showed that a guest can create, write, remount and read back save data within
one session. But every research and [launch](launch-contract.md) session starts
from a fresh `user/home` tree (`prepare_session`), so nothing a title saves
survives to its next launch. A title launched from a shortcut must find its own
saves again. It must also never see another title's saves.

## Design

`tools/title_save_store.py` keeps one persistent folder per title and copies it
into and out of the existing fresh session:

```
<state>/titles/<TITLE_ID>/<user id>/<save directory>/...   persistent store
<session>/user/home/<user id>/savedata/<TITLE_ID>/...       what the engine sees
```

- **`stage`** runs after `prepare_session` and before engine launch. It copies
  only `<TITLE_ID>`'s stored saves into the fresh session. Other titles' folders
  are never copied, so the engine cannot see them.
- **`commit`** runs only after the caller has verified a qualifying end of the
  session. It copies the session's `savedata/<TITLE_ID>` folders back and
  replaces the stored copy for that title. It refuses, and leaves the store
  unchanged, if the session contains:
  - save data for any other title, or files directly under `savedata`;
  - links or other reparse points;
  - more than the size or file limits.
- Replacement first builds a complete new copy, then swaps folders. A failed
  swap restores the previous copy.

Why copies rather than pointing the engine at the store with a link: the engine
then never writes to the store directly. A crash, forced cleanup or failed
verification leaves the last committed saves untouched. Each session stays as
isolated as today. There is no engine, patch or fixture change.

Title IDs must be four capital letters and five digits, as in the fixtures'
`param.sfo` (`PRTS00001`). User IDs are the engine's default homes, 1000–1003.

## Acceptance

**Step 1 (this change, host only).** The `title-save-store-contract` CTest suite
covers:

- stage then commit round trips;
- two titles staying isolated in both directions;
- an empty store staging nothing;
- refusal of other-title folders, stray files, links, invalid title or user IDs
  and over-limit data, with the previous store unchanged in every refused case;
- recovery of the previous copy when the swap fails.

**Step 2 (next, build only).** An original fixture mode or fixture that mounts
an existing save read-only and checks it against the host's challenge, built
and hash-pinned in hosted CI.

**Step 3 (Windows research machine, owner-approved guest run).**

1. Launch A writes a save, and the caller commits it.
2. Launch B of the same title, in a fresh session staged from the store, reads
   it back. The host oracle verifies both.
3. A different title ID, staged from its own empty store, does not find that
   save.
4. Existing fresh-session runners and their 40 suites stay unchanged.

Wiring the store into the registered launch contract follows only after step 3
passes.

## Step 3 runner (host-tested)

`tools/run_save_persist.py` runs the three launches of step 3 against one fresh
store under its output folder (`store/`). That store is never the user's launch
state. Every launch:

- uses a fresh session (`prepare_session`);
- gets a new `param.sfo`, the verified fixture and the shared random challenge;
- follows the save runner's strict-audit rules;
- must reach guest entry and end with a requested stop and confirmed tree
  cleanup.

| Launch | Fixture and title | Required |
| --- | --- | --- |
| `a-write` | `save_roundtrip`, `PRTS00001` | Nothing staged; guest PASS; `verify_save`; then `commit` keeps exactly that user's save |
| `b-same-title` | `save_readback`, `PRTS00001` | The committed save is staged; guest PASS; `verify_save` again; the store is unchanged |
| `c-other-title` | `save_readback`, `PRTS00002` | Nothing staged; guest `FAIL mount existing`; no `PRTS00001` or `PS4RTSAVE01` folder anywhere in the session |

A failed write commits nothing and stops. `persist-result.json` records every
launch: staging, transport, trace hash, guest outcome, host checks and the final
store.

The only change to `run_save_roundtrip.py` is that `evaluate` now takes the
markers and failure prefix as optional arguments. Its defaults are unchanged, so
the save-roundtrip runner and its guest script behave exactly as before.

The `save-persist-contract` suite (9 tests) drives the real runner, store and
session code against a fake engine that acts like the two fixtures. It covers:

- the passing three-launch run;
- a store that doesn't keep the save, caught at launch B;
- a store that leaks to another title, caught whether or not the guest notices;
- a writer failure, after which nothing is committed;
- a read-back PASS whose stored file fails the host check;
- `launch` requiring entry, cleanup and the expected outcome;
- unchanged `evaluate` defaults;
- the read-back contract.

Removing any one of four checks makes a test fail: the isolation host check, the
read-back host check, the B staging check, and C's expected failure. The suite
also caught two real runner bugs during development, a missing case folder and a
filter that dropped every audit event.

Run on the Windows research machine, after owner approval:

```
python tools/run_save_persist.py --engine build/upstream/windows-x64-strict/shadPS4.exe --engine-report build/upstream/strict-evidence/strict-build.json --writer build/homebrew/save-roundtrip/save_roundtrip.oelf --reader build/homebrew/save-readback/save_readback.oelf --supervisor build/native/ps4-startup-supervisor.exe --output build/save-persist/run-001
```

## Guest run result (15 November 2026)

**PASSED on the first attempt, with no retry.** The owner approved one run. Full
data is in
[the result record](../research/results/2026-11-15-save-persistence-guest-run.json).

The run used the research setup rebuilt that day from pinned inputs:

- **Engine:** the strict engine, patched tree `854265c1…`.
- **Fixtures:** `save_roundtrip.oelf` and `save_readback.oelf`, each matching its
  pinned hash.
- **Command:** the one above, run from this branch after #73 and #74 were merged.

| Launch | Fixture and title | Staged from store | Guest | Host |
| --- | --- | --- | --- | --- |
| `a-write` | `save_roundtrip`, `PRTS00001` | nothing | `PASS bytes=256 remount=1 search=1` | `verify_save` passed; commit kept user 1000's save (2 files) |
| `b-same-title` | `save_readback`, `PRTS00001` | user 1000, 2 files | `PASS bytes=256 existing=1 search=1` | `verify_save` passed again; store unchanged |
| `c-other-title` | `save_readback`, `PRTS00002` | nothing | `FAIL mount existing 0x809f0008` | no save folder in the session |

A separate check of the stored files found the following:

- `result.bin` is byte-identical in A's session, B's session and the store, and
  B's copy equals the host's transform of the shared challenge.
- B's engine-written `param.sfo` names `PRTS00001` and `PS4RTSAVE01`.
- The store holds only `PRTS00001`.

`save_readback` never creates save data, so B's save could only have come from
the store.

Every launch observed guest entry and confirmed tree cleanup. Each was stopped by
the runner on request after its result line: exit 125, forced termination, root
exit and an empty tree verified. No normal-close claim is made. Raw evidence
stays local under `build/save-persist/run-001`.

This is the first guest evidence that the per-title store keeps a title's save
across launches and hides it from another title. It covers one directory, one
file and one user. Wiring the store into the registered launch contract is the
next step.

## Risks and limits

- The engine's save layout (`home/<user>/savedata/<TITLE_ID>/<directory>`) is
  taken from the save-roundtrip result. A different layout for other save
  features would need a new review.
- Copying is bounded (64 MiB and 4,096 files per title in this step). Large real
  saves would need a measured limit later.
- Only save data persists. Trophies, settings files and other per-title data
  stay per-session.
- There is no concurrent-launch locking yet: one launch per title at a time is
  assumed and documented, not enforced.
