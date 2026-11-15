# Release-candidate engine: no LibreSSL, FFmpeg from source

Status: **built locally, strict suites passed, license inventory passed with no
release blockers (15 November 2026); guest regression passed after one approved
retry (16 November 2026).** It approves no redistribution; other release holds
remain (see the end).

## What it is

The release-candidate engine is the [release-no-libressl variant](release-variant.md)
with one more layer: it links **FFmpeg built from its pinned source**
([FFmpeg source build](ffmpeg-source-build.md)) instead of the prebuilt
`ext-ffmpeg-core` download. Together these remove both release blockers the
inventory found:

- LibreSSL, which is incompatible with the GPL ([decision 0003](decisions/0003-release-gpl-version.md));
- a static LGPL library without established corresponding source
  ([decision 0004](decisions/0004-lgpl-relinking.md)).

## Layers and build

Each layer is checked against its pinned tree:

1. Strict research patch and headers: tree `854265c1…`.
2. `release-no-libressl.patch` and the CNG header: tree `ac4788d8…`.
3. `research/shadps4/release-ffmpeg-source.patch`: tree `0c8282ba…`. It adds the
   CMake option `PS4RT_FFMPEG_PREFIX`. When set, the engine's `FFmpeg::ffmpeg`
   target uses that prefix's `include/` and `lib/`, and the prebuilt archive is
   never downloaded or unpacked.

`tools/build_release_candidate.py` builds it in its own directories. The strict
engine and the release-no-libressl variant are untouched. The script:

- copies the verified FFmpeg source build into the engine build directory
  (`ps4rt-ffmpeg/`), and checks every library's hash against the
  [source-build record](../research/results/2026-11-15-ffmpeg-source-build.json);
- copies FFmpeg's own license notices from the source kit (`LICENSE.md` and the
  `COPYING.*` files), each checked against the pinned FFmpeg audit;
- configures with `PS4RT_WITHOUT_LIBRESSL=ON` and that prefix, and fails if the
  prebuilt archive appears;
- builds, then runs the strict post-build suites against the same FFmpeg
  libraries.

```powershell
python tools/build_release_candidate.py --ffmpeg-build build/ffmpeg-source/build-003 --kit build/release-audit/source-kit-001/kit --seed-from build/upstream/shadps4-strict --jobs 8
```

Before switching headers, the engine's FFmpeg includes were checked. All 41
FFmpeg headers the engine compiles exist in the source build's install. The
prebuilt wrapper's headers differ from the patched source in one declaration:
`av_stream_get_first_dts`, added by a pinned vcpkg patch. Its version label also
says `5.1.2` for 7.1.1 libraries.

## Results (15 November 2026)

| Check | Result |
| --- | --- |
| Build | `release_candidate_engine_built`; tree `0c8282ba…`; executable `eab87dfa…` |
| AAC decoder suite, against the source-built FFmpeg | passed: 26,240 backend checks plus the adapter |
| Host-exception suite | passed |
| FDK linkage audit | passed: FDK absent |
| [License inventory](../research/results/2026-11-15-release-candidate-inventory.json) (`--variant release-candidate`) | passed, with **no release blockers**: 93 libraries, LibreSSL absent, FFmpeg recorded as built from the pinned source kit, all 41 FFmpeg headers from that build, no third-party DLLs |

For comparison, the strict engine's blockers are FFmpeg and LibreSSL, and the
release-no-libressl variant's are FFmpeg only.

The inventory's `release-candidate` variant overrides the FFmpeg component:

- kind `source-built-static`;
- notices read from the staged copy;
- LGPL source origin `pinned-source-kit`;
- headers classified through the staged prefix.

The reviewed table itself still describes the prebuilt.
`tools/release_variant.py` now also verifies a candidate build report: both
layers, both trees, and the FFmpeg library hashes against the source-build
record. Guest runs can therefore target this engine.

## Guest regression (16 November 2026)

Full data, including both attempts, is in
[the result record](../research/results/2026-11-16-release-candidate-guest-run.json).
The runners checked the engine and fixtures against their contracts before each
launch. Each launch was stopped on request after its result line; no normal-close
claim is made.

| Launch | Attempt 1 | Approved retry |
| --- | --- | --- |
| `hello-world` | **passed** | — |
| `service-roundtrip` | **failed**: imports checked at entry (0 unresolved), then no guest entry. A 30 s timeout followed, and the forced stop could not confirm cleanup | **passed**: `PASS threads=2 bytes=256 seek=128`, result file checked, cleanup confirmed |
| `save-counter` | **passed**: `PASS previous=0 count=1`, counter checked on disk | — |

**Attempt 1's failure, as recorded:**

- The owner reports pressing the laptop's sleep button during the run.
- Windows logged one Modern Standby, at 00:28:39–00:28:41 local time. That was
  after the whole attempt had ended (00:28:07). Nothing is logged during the
  stalled launch (00:27:26–00:28:01).
- The engine log was cut off by the forced stop. No engine process remained
  afterwards.

**The cause is therefore not confirmed.** The failure is kept on record, not
replaced by the retry. The owner approved the retry separately, and it ran once.

## Limits and what remains

- The guest regression covers three homebrew programs, one of which needed the
  approved retry. Networking is not exercised.
- One build, on one machine. Not byte-identical to any upstream binary.
- Release holds still open:
  - the release source bundle and its tooling (decision 0004 requires complete
    corresponding source with every binary);
  - the Visual C++ runtime redistribution terms;
  - the font (OFL) and notice bundle.
- No TLS: HTTPS uses upstream's no-SSL fallback.
