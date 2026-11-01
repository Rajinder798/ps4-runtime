# Save-storage fixture (save-roundtrip)

Status: **built and inspected in hosted CI; runner and host oracle implemented. No guest run yet.** This is the
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

## Runner and host oracle

Implemented and covered by portable tests; **not yet run against the engine.**

- `tools/run_save_roundtrip.py` is a separate runner. The shared
  `tools/run_homebrew_startup.py` is hash-pinned by reviewed G4 records (the
  disconnected-close attestation and the issue-39 host-safety review), so it is
  left unchanged. The new runner reuses only its unchanged helpers (hashing,
  audit reading, session preparation, supervision), as the live-av-v2 contract
  does, and re-implements the strict-build input checks for this fixture's
  contract.
- It stages a fresh app folder with the verified fixture, a random 256-byte `challenge.bin` and an
  original minimal `sce_sys/param.sfo` (`TITLE_ID` `PRTS00001`, a made-up
  identity, plus `TITLE` and `APP_VER`). `tools/psf.py` writes and reads PSF
  files. Its layout follows the pinned engine's `PSF::Open`, and its reader also
  accepts the engine encoder's own layout (insertion order, unpadded key table).
- The run must pass the existing strict-audit rules: no unresolved import, one
  guest entry, then `save-roundtrip: begin` and the `PASS` line in order. Any
  `save-roundtrip: FAIL` line fails it.
- **Host oracle (`verify_save`).** After the guest's `PASS`:
  - exactly one save directory must exist, at
    `user/home/<user>/savedata/PRTS00001/PS4RTSAVE01`;
  - no directory may sit outside the title folder;
  - its `result.bin` must equal the host's own transform of the challenge it
    generated;
  - the engine-written `sce_sys/param.sfo` must name `TITLE_ID` `PRTS00001` and
    `SAVEDATA_DIRECTORY` `PS4RTSAVE01`.

  So the guest's `PASS` alone cannot pass the run, and the save must be stored
  under the title from our `param.sfo`.
- The `save-roundtrip-contract` CTest suite covers the strict-audit rules,
  input binding, oracle positives and negatives, staging, failure evidence and
  the PSF format. It runs no engine.
- `tests/save_guest_tests.py` (opt-in, Windows only) runs five real cases through
  the unchanged save runner, changing only staged host files:
  - two valid runs with fresh challenges;
  - a missing challenge and a 128-byte challenge, which must produce
    `FAIL open challenge` and `FAIL read challenge`;
  - a pre-existing save directory, which must produce `FAIL create mount`.

  Every case requires guest entry and confirmed process-tree cleanup.

## Guest run on the Windows research machine

Use the existing strict engine build (the strict patch is unchanged) and the
usual research tools. Adjust the `build/native` paths if that machine uses a
single-configuration generator.

```
git pull
python tools/build_homebrew.py --sample save-roundtrip --llvm-bin build/tools/llvm-mingw-20261006-ucrt-x86_64/bin --inspector build/native/Release/ps4-runtime.exe
python tests/save_guest_tests.py --engine build/upstream/windows-x64-strict/shadPS4.exe --engine-report build/upstream/strict-evidence/strict-build.json --fixture build/homebrew/save-roundtrip/save_roundtrip.oelf --supervisor build/native/Release/ps4-startup-supervisor.exe --output build/save/run-001
```

`build/save/run-001/summary.json` and each case's `save-result.json` are the
evidence. A first attempt may fail if the engine handles `param.sfo` or save
paths differently than the source review predicts. Keep that output, as in the
other research records, rather than retrying until it passes.

Limits even after a passing run: one directory, one file, one user. No icons,
parameters, backups, quotas, corruption handling or save-data dialogs.
