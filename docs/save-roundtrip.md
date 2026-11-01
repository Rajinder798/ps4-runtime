# Save-storage fixture (save-roundtrip)

Status: **built and inspected in hosted CI only. No guest run yet.** This is the
first step toward the save-storage part of the roadmap's G4 item ("Add input,
audio, save storage, and an isolated title profile"). It is not save support, G4
progress or a compatibility claim.

## What the fixture does

`research/homebrew/save_roundtrip/main.cpp` is an original OpenOrbis application
linked against `libSceSaveData` and `libSceUserService`. It follows the
service-roundtrip pattern:

1. Read a host-generated 256-byte `/app0/challenge.bin` and require end of file.
2. Compute `expected[i] = (challenge[i] + 0x3c) ^ (i * 7)` (low byte).
3. `sceUserServiceInitialize`, `sceUserServiceGetInitialUser`,
   `sceSaveDataInitialize3`.
4. `sceSaveDataMount2` directory `PS4RTSAVE01` with `CREATE | RDWR` and the
   minimum 96 blocks. A fresh profile has no such directory, so creation must
   succeed. Write `result.bin` through `sceKernelOpen`/`sceKernelWrite` on the
   returned mount point, then `sceSaveDataUmount`.
5. Remount **read-only**, read `result.bin` back, require end of file and an
   exact match, then unmount. The read-only remount means the readback cannot
   come from the write mount.
6. `sceSaveDataDirNameSearch` for that exact name must report one hit with the
   same name.
7. Print `save-roundtrip: PASS bytes=256 remount=1 search=1`, or
   `save-roundtrip: FAIL <operation> <code>`, then idle like the other fixtures.

The struct layouts it relies on (`OrbisSaveDataMount2`, `OrbisSaveDataMountResult`,
and the directory-search condition and result) were compared between the pinned
OpenOrbis headers (`b458dfd9`) and the pinned engine's `savedata.cpp`; they
agree. Every save-data function the fixture calls has a non-stub implementation
in the pinned engine. That was a manual source review: 29 of its 95 save-data
registrations are not marked `(STUBBED)`.

## Evidence so far

The hosted homebrew workflow builds the fixture and requires the same import,
relocation and startup cross-checks as every other fixture. Its source and `.oelf`
hashes are pinned in `config/save-roundtrip.json`. It also records the static
[engine import coverage](development.md#static-engine-import-coverage)
prediction. Because the fixture has never run as a guest, that prediction is
recorded but not asserted (`FIXTURES_WITHOUT_GUEST_RUNS` in
`tools/build_homebrew.py`).

First hosted build ([run 41298997250](https://github.com/Rajinder798/ps4-runtime/actions/runs/41298997250)):

- the converted `.oelf` is 110,824 bytes, SHA-256 `69172148…381a5`;
- the import, relocation and startup cross-checks all matched (21 imports, 37
  relocations) across modules `libkernel`, `libSceSaveData` and
  `libSceUserService`;
- the static prediction: the patched research engine registers all 21 imports,
  while the unpatched pin lacks only `poll` and `_fcntl`.

That build stopped only because the binary hash was not yet pinned.

## Planned guest acceptance (needs the Windows machine)

Not implemented yet:

- A runner profile that gives the fixture an original minimal `param.sfo` (title
  ID), so the engine stores the save under
  `<home>/<user>/savedata/<title>/PS4RTSAVE01/`. Without one, the pinned engine
  uses an empty title component.
- **Independent oracle:** after a strict run with the guest's `PASS` line, the host
  reads the stored `result.bin` and compares it with its own transform of the
  challenge it generated. Negative cases mirror service-roundtrip: a wrong or
  short challenge must produce `FAIL`, and a pre-existing directory must make
  `CREATE` fail.
- A strict run on the Windows research machine, with the usual cleanup and
  regression rules.

Limits even after that: one directory, one file, one user, no icons, parameters,
backups, quotas, corruption handling or save-data dialogs.
