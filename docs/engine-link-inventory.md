# Engine link inventory (release hold 3, first step)

Status: **implemented and run once on the research machine (15 November 2026).
Passed.** This is licensing-track evidence. It approves no redistribution, and it
is not runtime or compatibility progress.

## Why

[Release hold 3](release-audit.md#remaining-release-holds-and-next-implementation)
starts with "finish the Windows link-graph review". Its later items (LGPL
handling, Apache/GPL version selection, fonts and resources, toolchain runtime
terms) all need one fact base first: what the strict research engine actually
contains and loads. Until now that was inferred from build files rather than
read from the built binary.

## What it checks

`tools/engine_link_inventory.py` reads three things from one strict build:

1. **The linker map.** It lists every static library that contributed a symbol,
   with symbol counts, plus the engine's own objects.
2. **The executable's PE import tables**, both normal and delay-loaded. These
   list every DLL Windows loads at startup.
3. **The compiled-in fonts and resources.** It checks their hashes and their
   declarations in the upstream `REUSE.toml`.

Each item must match the reviewed table in `config/engine-link-components.json`.
For every component, the table records:

- the linked library names;
- the license, as identified from the notice text in the pinned checkout;
- the notice file, pinned by SHA-256 in the upstream checkout, or in the engine
  build directory for a dependency CMake downloads at configure time. For a
  download, the declaring CMake file is pinned too, and it must name the recorded
  URL and archive hash;
- any further bundled notices;
- flags for the obligations a binary release would raise.

The check fails closed on any of these:

- a linked library that matches no reviewed component, or more than one;
- a reviewed component that is not linked (a stale entry);
- a missing or changed notice file;
- an asset that is missing, changed, or not declared with the recorded license;
- a DLL import outside the Windows-system and Visual C++ runtime allowlists;
- an engine that does not match its strict build report.

## Result (15 November 2026)

Full data is in [the result record](../research/results/2026-11-15-engine-link-inventory.json).
The engine is the strict build rebuilt that day (patched tree `854265c1…`), at
upstream revision `e6c79a5f`.

- **94 linked libraries**, all mapped to 30 reviewed components. The engine's own
  objects contribute 254,873 symbols.
- **78 imported DLLs:** 74 Windows system DLLs and 4 Visual C++ runtime DLLs
  (`msvcp140`, `msvcp140_atomic_wait`, `vcruntime140`, `vcruntime140_1`). There
  are **no delay-loaded imports and no third-party DLL imports**: every
  third-party library is linked statically.
- **22 compiled-in assets:**
  - five Noto fonts, `OFL-1.1`;
  - ProggyVector, `MIT`;
  - 13 PNG images, a WAV file and two AMD lookup tables, all declared
    `GPL-2.0-or-later` by upstream `REUSE.toml`.
- **Independent cross-checks:** the DLL list equals `llvm-readobj --coff-imports`
  exactly, and the library list equals a separate scan of the map.
- **fmt is downloaded at build time, not taken from its submodule.** spdlog is
  configured before the `fmt::fmt` target exists, so spdlog's
  `cmake/fmtlib.cmake` downloads **fmt 12.1.0** from
  `github.com/fmtlib/fmt` (archive SHA-256 `ea7de429…`, checked by CMake). The
  `externals/fmt` submodule (12.1.1-dev) is never built. The MIT notice text is
  the same apart from line endings. This was found in the build's header
  dependency log and corrected before review. It is the only third-party code in
  the engine that comes from outside the pinned submodules.

### Obligations a binary release would raise

The tool reports these from the reviewed table. They are findings to resolve,
not decisions.

| Flag | Components | Meaning |
| --- | --- | --- |
| `lgpl-static-relink` | FFmpeg, libusb, OpenAL Soft | Static LGPL code: ship source and allow relinking with a modified library |
| `gpl3-selection` | Abseil (`Apache-2.0`) | Compatible with GPL-3.0 only, so a binary release must use GPL-3.0-or-later terms |
| `gpl-compatibility-review` | LibreSSL (`OpenSSL AND ISC`) | OpenSSL/SSLeay advertising clauses need an explicit GPL compatibility decision |
| `dual-license-choice` | FreeType (`FTL OR GPL-2.0-or-later`), zstd (`BSD-3-Clause OR GPL-2.0-only`) | Record which license the release uses |
| `bundled-notices` | ImGuiFileDialog, OpenAL Soft | Further bundled code with its own notices (listed and hashed) |
| `build-time-download` | fmt | Downloaded at configure time outside the pinned submodules; a release must keep that exact source archive |
| `proprietary-runtime-terms` | Visual C++ runtime | Redistribution follows the Visual Studio license terms |

The fonts add an `OFL-1.1` notice obligation. The two AMD lookup tables rely on
upstream's `GPL-2.0-or-later` declaration; their provenance has not been reviewed
separately.

## Reproduction

On the research machine, after building the strict engine:

```
python tools/engine_link_inventory.py --map build/upstream/windows-x64-strict/ps4-runtime-research.map --engine build/upstream/windows-x64-strict/shadps4.exe --engine-report build/upstream/strict-evidence/strict-build.json --source build/upstream/shadps4-strict --output build/link-inventory/run-003/inventory.json
```

Exit 0 means passed. The CTest suite `engine-link-inventory-contract` (14 tests)
uses a synthetic PE, map and checkout, so it runs on the Linux and Windows CI
runners without the engine. It also checks the committed table against the
recorded run. Removing any one of ten checks makes it fail:

- the stale-entry check;
- notice hashes;
- the DLL allowlist;
- delay-import reading;
- the `REUSE.toml` license check;
- unmapped-library refusal;
- own-object counting;
- the download declaration's hash;
- its URL and archive-hash match;
- build-directory notice paths.

## Limits

- **Header-only code** compiled into the engine's own objects (for example JSON,
  stb, robin-map and magic_enum) is invisible in a link map. A source and include
  closure review is the next step.
- **Runtime-loaded libraries**, such as the Vulkan loader and GPU drivers, are
  loaded with `LoadLibrary` and are not covered here.
- Licenses were identified from each component's notice text. Per-file headers
  inside components were not swept.
- One strict build, on one machine. The map and engine hashes are in the record.
- **Redistribution is not approved.** Holds 1 to 3 in the release audit still
  stand, apart from what this inventory establishes.
