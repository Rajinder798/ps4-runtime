# Per-title save store (isolated title profile, step 1)

Status: **design and host-side store implemented and host-tested. Not yet used
by any launch, and no guest run.** This starts the "isolated title profile" part
of the roadmap's G4 item ("Add input, audio, save storage, and an isolated title
profile"). It is not save support, G4 progress or a compatibility claim.

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
