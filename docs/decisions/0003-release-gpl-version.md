# 0003: GPL version for a binary engine release

Date: 15 November 2026. Status: **accepted by the owner on 15 November 2026
(option A).** No binary is distributed, and no license is changed by this record. It covers one
release hold 3 decision from the
[engine link inventory](../engine-link-inventory.md). This is an engineering
compliance analysis, not legal advice.

## Question

A binary release of the research engine combines the project's own code,
shadPS4 and about 48 third-party components into one executable. Under which GPL
version can that combined binary be distributed so that every component's terms
are met?

This record covers only that question. The LGPL relinking materials, the Visual
C++ runtime terms and the font notices are separate decisions. LibreSSL is
covered here only as far as the GPL version affects it.

## Facts (from the inventory, 15 November 2026)

| Item | Terms | Effect on the GPL version |
| --- | --- | --- |
| This project's original code | GPL-2.0-or-later | Either version |
| shadPS4 `src/` tree (pinned `e6c79a5f`) | 936 SPDX tags are GPL-2.0-or-later; the other 10 are permissive. **No GPL-2.0-only file.** | Either version |
| Abseil (linked, via protobuf) | Apache-2.0 | **GPL-3.0 only** |
| Vulkan headers (17 of 25 included) | Apache-2.0 only | **GPL-3.0 only** |
| FreeType | FTL or GPL-2.0-or-later. FreeType's own notice: FTL is "compatible to … version 3, but not version 2" | Either: GPL-2.0-or-later under v2, either option under v3 |
| zstd | BSD-3-Clause or GPL-2.0-only | Either, by choosing BSD-3-Clause |
| FFmpeg, libusb, OpenAL Soft | LGPL-2.1-or-later / LGPL-2.0-or-later | Either. Relinking is a separate decision |
| dr_flac, stb | Public domain (Unlicense) or MIT-0 / MIT | Either |
| Other components | MIT, BSD, Zlib, BSL-1.0, CC0, libpng, OFL fonts | Either |
| **LibreSSL** (linked; engine networking only: HTTP/TLS and P2P crypto) | OpenSSL and SSLeay licenses with advertising clauses. The SSLeay terms say the code "cannot simply be copied and put under another distribution licence [including the GNU Public Licence.]" | **Neither.** Incompatible with GPL-2.0 and GPL-3.0 without an exception |

The Apache-2.0 incompatibility with GPL-2.0 (and compatibility with GPL-3.0) is
the Free Software Foundation's published position. Upstream FreeType states the
same about FTL.

## Options

**A. Release binaries under GPL-3.0-or-later (recommended).**

- Abseil and the Vulkan headers are satisfied.
- FreeType and zstd are used under GPL-2.0-or-later (or FTL) and BSD-3-Clause.
- The LGPL components remain compatible.
- The project's GPL-2.0-or-later source license is **unchanged**, because "or
  later" already permits distributing the combination under GPL-3.0. The same
  holds for shadPS4's GPL-2.0-or-later files. Nothing needs relicensing.
- GPL-3.0's "System Libraries" definition is also clearer than GPL-2.0's for the
  Visual C++ runtime DLLs shipped alongside. That remains its own decision.

**B. Release binaries under GPL-2.0.** This needs removing or replacing Abseil
(a protobuf dependency) and the Apache-2.0-only Vulkan C headers, which every
Vulkan renderer uses. That is not practical, and it gains nothing over A,
because the source license already allows both.

**C. Don't distribute binaries; users build locally.** This avoids distribution
obligations but contradicts the [product goal](../product-vision.md) of
installing once. It could serve as an interim state only.

## LibreSSL blocks every option

Option A does not resolve LibreSSL; nothing does at the GPL-version level.
Possible paths, each a separate engineering decision:

1. **Build the release engine without LibreSSL.** Turn off the networking
   features that need it. The supported homebrew titles use no networking.
2. **Replace it with a GPL-3.0-compatible library**, for example OpenSSL 3.x,
   which is Apache-2.0 and therefore GPL-3.0-compatible under option A. Another
   possibility is the Windows CNG/SChannel APIs, which are system libraries.
3. **Get a linking exception** from every copyright holder of the
   GPL-licensed code. This is not practical for shadPS4's many contributors.

Path 1 is the smallest change that matches the current scope. Path 2 is the
long-term route if networking ever becomes a supported capability.

## Decision (accepted: option A)

- **Binary releases:** GPL-3.0-or-later. Record the choices for the
  dual-licensed components: FreeType under GPL-2.0-or-later, zstd under
  BSD-3-Clause, dr_flac under MIT-0, stb under MIT.
- **Source license:** unchanged, GPL-2.0-or-later for this project's original
  code.
- **LibreSSL:** no binary release until it is removed from the release build or
  replaced. Decide that as a follow-up, with path 1 preferred for now.
- **Unchanged holds:** LGPL relinking, the Visual C++ runtime terms, the font and
  notice bundle, and FFmpeg's corresponding source (release hold 2) remain open.
  **This decision alone approves no redistribution.**

## Follow-through

1. Done: the owner accepted option A on 15 November 2026 ("Accept option A").
2. Done: `config/engine-link-components.json` records the release license
   (`GPL-3.0-or-later`, citing this record) and the chosen license for each
   dual-licensed component. The inventory now fails if:
   - a dual-licensed component has no recorded choice, or a choice that is not
     one of its alternatives;
   - a component that needs GPL-3.0 meets a release license that is not GPL-3.0.
   It also lists release blockers. Today the only one is LibreSSL.
3. Open: the LibreSSL follow-up. Prototype a release build with the networking
   features off, and re-run the inventory to show LibreSSL is no longer linked.
