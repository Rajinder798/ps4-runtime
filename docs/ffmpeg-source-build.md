# FFmpeg source build (release hold 2)

Status: **built from the pinned source and verified (15 November 2026). Not yet
linked into the engine.** This is release-track evidence. It approves no
redistribution.

## Why

The engine links FFmpeg statically. Until now those libraries came from the
prebuilt `ext-ffmpeg-core` archive, whose exact corresponding source is not
established. [Decision 0004](decisions/0004-lgpl-relinking.md) requires every
binary release to ship the complete corresponding source of the FFmpeg it links.
So the inventory reports the prebuilt FFmpeg as the last release blocker on the
[release-no-libressl engine](release-variant.md). Building FFmpeg ourselves, from
the pinned source and with a script in this repository, is what removes that
blocker.

## How it is built

`tools/build_ffmpeg_source.py` works from the [FFmpeg source kit](ffmpeg-source-kit.md):

1. It verifies the kit: every input checksum, the 12 patches reapplied, and the
   patched source tree (FFmpeg 7.1.1).
2. It runs FFmpeg's own `configure` under MSYS2 with **exactly the semantic flags
   the prebuilt libraries report about themselves** (117 flags, from the
   [FFmpeg audit](release-audit.md)). It adds the toolchain of the wrapper's
   `x64-win-llvm-static-release` triplet: clang-cl, lld-link, llvm-nm and the
   static C runtime (`/MT`).
3. It runs `make` and `make install`.
4. It applies **the same metadata review as the prebuilt**: library versions,
   matching headers, "LGPL version 2.1 or later", no license-enabling options,
   and identical semantic flags.

Requirements:

- Windows, in the Visual Studio 2022 x64 developer shell;
- MSYS2 with `make`, `nasm`, `pkgconf` and `diffutils`.

Nothing is downloaded during the build.

```powershell
python tools/ffmpeg_source_kit.py assemble --output build/release-audit/source-kit-001
python tools/build_ffmpeg_source.py --kit build/release-audit/source-kit-001/kit --output build/ffmpeg-source/build-003
```

## Result (15 November 2026)

Full data is in [the result record](../research/results/2026-11-15-ffmpeg-source-build.json).

| Check | Result |
| --- | --- |
| Source kit | verified; 12 patches; FFmpeg 7.1.1 at `db69d06e…` |
| Library versions | avcodec 4002661, avfilter 656484, avformat 3999588, avutil 3876708, swresample 328548, swscale 525156; all equal to the prebuilt, headers matching |
| Reported license | "LGPL version 2.1 or later" for all six; no GPL, version 3, non-free or FDK options |
| Semantic configure flags | **all 117 identical** to the prebuilt |
| AAC decoder suite, linked against the rebuilt libraries | passed: 26,240 backend checks and the adapter test, the same as with the prebuilt |

**Differences from the prebuilt**, recorded rather than hidden:

- **Compiler:** clang-cl 19.1.5 (VS Build Tools) instead of the clang 20.1.8 seen
  in the prebuilt objects.
- **Archiver:** MSVC `lib.exe` instead of `llvm-lib` through automake's `ar-lib`.
- **Build driver:** FFmpeg's own configure and make, not vcpkg.

So the libraries are **not byte-identical** to the prebuilt. Equivalence rests on
versions, the reported license and identical features.

Two earlier attempts are kept, not replaced:

- `build-001` failed at the archive step. `configure` recognises a Windows-style
  archiver only by the word "Microsoft" in its output, so it gave `llvm-lib` Unix
  `ar` arguments.
- `build-002` built everything but reported this repository's commit as the
  FFmpeg version. FFmpeg's version script ran `git describe` inside this checkout.
  The build now points `GIT_DIR` at a missing path, so the `RELEASE` file
  (`7.1.1`) is used, as in a normal release build.

`tools/test_aac_backend.py` gained an optional `ffmpeg` argument to run against a
given FFmpeg build. Its default is unchanged: the prebuilt archive with its
audited hashes.

## Next step and limits

- **The engine still links the prebuilt.** The next step is an engine variant
  that links these libraries. Then rerun the inventory, with FFmpeg recorded as
  built from pinned source; the expectation is no release blockers. After that,
  the strict suites and a bounded guest regression.
- One build, on one machine. The libraries stay local and are pinned in the
  record by hash.
- The release source bundle and its tooling, the Visual C++ runtime terms and the
  font and notice bundle remain open.
