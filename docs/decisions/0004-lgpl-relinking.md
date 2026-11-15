# 0004: Meeting the LGPL relinking terms in a binary engine release

Date: 15 November 2026. Status: **accepted by the owner on 15 November 2026
(option A).** No binary is distributed and nothing is relicensed by this record. It covers one
release hold 3 decision from the [engine link inventory](../engine-link-inventory.md).
It builds on [decision 0003](0003-release-gpl-version.md) (binaries under
GPL-3.0-or-later). This is an engineering compliance analysis, not legal advice.

## Question

Three LGPL libraries are linked **statically** into the engine executable. How
does a binary release meet their relinking terms? Under those terms, a user must
be able to modify the library and use the modified version with the application.

## Facts

| Library | Grant (from its own notices) | How it reaches the engine |
| --- | --- | --- |
| FFmpeg (`avcodec`, `avformat`, `avutil`, `swresample`, `swscale`) | All six built libraries report **LGPL-2.1-or-later** in their configuration; GPL, version 3 and non-free options are absent ([FFmpeg audit](../release-audit.md)) | **Prebuilt** static libraries from the pinned `ext-ffmpeg-core` archive. Their exact corresponding source and build are not yet established (release hold 2) |
| libusb | "LGPL version 2.1 … or (at your option) any later version" (source headers; `COPYING` is LGPL-2.1) | Built **from the pinned submodule** as a static library |
| OpenAL Soft | "GNU Library General Public License … version 2 … or (at your option) any later version" | Built **from the pinned submodule**, forced static (`LIBTYPE STATIC`) |

The LGPL offers two relevant routes:

- **Convert to the GPL.** LGPL-2.1 section 3, and the same section of LGPL-2.0,
  lets a distributor apply the ordinary GNU GPL instead of the LGPL to a copy of
  the library. Because the grants are "or any later version", that includes
  GPL-3.0, which matches decision 0003.
- **Static linking with relinking materials.** LGPL-2.1 section 6(a) allows
  static linking if the release provides the library's complete source **and**
  the rest of the application as source or object code, so that a user can
  modify the library and relink.

Under decision 0003, a binary release must already provide the **complete
corresponding source of the whole engine** under GPL-3.0. That includes these
three libraries' sources and the scripts that build and link them. Complete
source of the application with its build scripts lets a user rebuild with a
modified library. That is the relinking the LGPL asks for.

## Options

**A. Provide complete corresponding source; keep static linking (recommended).**

- Ship every binary release with, or alongside, its complete corresponding
  source. That covers this project, shadPS4, every library source including
  these three, and the build scripts that reproduce the release build. Do it in a
  way GPL-3.0 section 6 accepts: accompanying the binary, or an equivalent
  download from the same place.
- Include the LGPL and GPL license texts and the libraries' notices in the
  release.
- **FFmpeg is the gap.** Its static libraries are downloaded prebuilt, so their
  exact corresponding source is not established. Option A therefore requires
  building FFmpeg ourselves from its pinned source in the release pipeline. The
  roadmap already has this item: independently rebuild the pinned FFmpeg recipe
  (hold 2). The release then ships that source and its build scripts.
- No engine code change is needed.

**B. Switch the three libraries to DLLs.** Users could then replace a DLL without
rebuilding the engine (LGPL-2.1 section 6(b)). But the release must still offer
the libraries' source, and under decision 0003 the whole engine's source as
well. The changes:

- FFmpeg's prebuilt static libraries would have to become DLLs, so the hold 2
  rebuild is still needed.
- OpenAL Soft and libusb would have to be built shared, against upstream's
  forced static settings.
- Each change needs its own inventory, CNG-style tests and guest regressions.

It adds work and risk without removing any obligation that A already meets.

**C. Ship object files for relinking** (section 6(a) object-code route). This is
redundant once the complete source is shipped, as A does. It is fragile: object
files are toolchain-specific. It also does not fix the FFmpeg gap.

## Decision (accepted: option A)

- **Option A:** static linking stays. Every binary release provides the
  complete corresponding source and build scripts for the whole engine, plus the
  license texts and notices. That meets the GPL-3.0 terms (decision 0003) and,
  through them, the LGPL relinking terms.
- **FFmpeg must be built from source** in the release pipeline. The prebuilt
  archive is acceptable for local research only. This makes the hold 2 rebuild a
  prerequisite of any binary release.
- The libusb and OpenAL Soft sources are already pinned submodules. Their
  source, with the engine's build files, goes into the release source bundle.
- **This decision alone approves no redistribution.** Still open: the FFmpeg
  source build itself, the Visual C++ runtime terms, the font and notice bundle,
  and the release source-bundle tooling.

## Follow-through

1. Done: the owner accepted option A on 15 November 2026 ("Accept option A").
2. Done: `config/engine-link-components.json` records each LGPL component's
   method: complete corresponding source, with a source origin of either a
   pinned submodule or a prebuilt download. The inventory now fails if:
   - a flagged component has no valid method;
   - a prebuilt component claims to be built from a pinned submodule.

   It reports every LGPL component that is still a prebuilt download as a
   **release blocker**. Today that is FFmpeg, on both the strict engine and the
   release-no-libressl variant.
3. Open: the hold 2 FFmpeg source build. Build the pinned FFmpeg recipe from
   source and link the engine against it. Then rerun the inventory, the strict
   suites and a bounded guest regression.
