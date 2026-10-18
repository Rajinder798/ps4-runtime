# Windows engine release audit

Status: source/provenance audit in progress. Engine redistribution remains
blocked. This is the next G3 prerequisite after the selected G2 homebrew startup
passed; it does not add an installer or change the tested guest execution path.

## FFmpeg source and binary identification

The previous [focused review](decisions/0002-g2-engine-boundary.md) identified a
pinned wrapper and prebuilt archive but left their complete build/source scope
open. The repeatable audit now queries the **six static FFmpeg libraries actually
linked by the Windows wrapper**, rather than inferring their license from the
wrapper's root notice. The seventh archive library, `avdevice.lib`, is not in
that wrapper's link list; this is not an approval to redistribute the archive.

The [locked audit inputs](../config/ffmpeg-audit.json) and
[local public result](../research/results/2026-10-18-ffmpeg-audit.json) establish:

| Input/check | Observed result |
| --- | --- |
| Wrapper | `94dde08c8a9e4271a93a2a7e4159e9fb05d30c0a`; workflow, CMake, patch, Windows triplet and toolchain-support inputs hashed; canonical header tree verified. |
| Static archive | SHA-256 matches `config/upstream-lock.json`; each of the six selected `.lib` members also has a locked SHA-256. |
| Linked version APIs | FFmpeg **7.1.1**; all six component numeric versions exactly match their API headers. |
| License/configuration APIs | All six report **LGPL version 2.1 or later**, with identical configure strings. Top-level `--enable-gpl`, `--enable-version3`, `--enable-nonfree` and `--enable-libfdk-aac` are absent; `--disable-libfdk-aac` is present. |
| vcpkg | `df8bfe519564ae001903e5cdd32af0999531ef71`; version 7.1.1, port version 1; 18 port/patch/support inputs verified, including the 12 source patches named by the port. Wrapper patch applies to that exact portfile. |
| Source archive | Official FFmpeg `n7.1.1`, resolved commit `db69d06eeeab4f46da15030a80d539efb4503ca8`. Archive SHA-512 matches the pinned vcpkg recipe; five source license/notice files verified. |

The wrapper's unused `libavutil/ffversion.h` still labels itself **5.1.2**.
No engine source references that header or `FFMPEG_VERSION`; the actual library
APIs and numeric ABI headers agree on 7.1.1. The stale label is recorded, not
used as the binary version or treated as a demonstrated ABI failure. The audit
does not modify the pinned wrapper to hide the discrepancy.

Version/configuration/license API results are evidence from a specific locked
binary, not proof that its complete contents were independently reproduced.
The port's `license: null` also does not mean license-free. Rebuilding from the
complete recipe, confirming the full dependency closure, assembling notices
and corresponding source/relink materials remain necessary release work.

The pinned [upstream workflow](https://github.com/shadps4-emu/ext-ffmpeg-core/blob/94dde08c8a9e4271a93a2a7e4159e9fb05d30c0a/.github/workflows/build.yml),
[patched port](https://github.com/shadps4-emu/ext-ffmpeg-core/blob/94dde08c8a9e4271a93a2a7e4159e9fb05d30c0a/ffmpeg.patch),
[vcpkg recipe](https://github.com/microsoft/vcpkg/blob/df8bfe519564ae001903e5cdd32af0999531ef71/ports/ffmpeg/portfile.cmake)
and [FFmpeg source license](https://github.com/FFmpeg/FFmpeg/blob/db69d06eeeab4f46da15030a80d539efb4503ca8/LICENSE.md)
are the provenance sources. FFmpeg's own
[distribution guidance](https://ffmpeg.org/legal.html) calls for matching source
and build information; identifying the release tag alone does not supply that.

## Reproduction and acceptance

Use Python 3.12+, Git, and a Windows x64 clang-cl/MSVC developer environment.
Obtain the exact wrapper checkout and prebuilt archive using the
[existing pinned build recipe](upstream-baseline.md). Then:

```powershell
python tools/audit_ffmpeg.py --wrapper build/upstream/shadps4-strict/externals/ffmpeg-core --archive build/upstream/windows-x64-strict/externals/ffmpeg-94dde08.zip --output build/release-audit/run-001
```

Use a new output directory on each run. Output/cache must stay under ignored
`build/`. The audit reads canonical pinned Git headers, verifies the archive
and individual members, downloads/checks official source/recipe inputs, checks
the wrapper patch, compiles the repository's small host metadata helper and
queries the linked libraries. It does not initialize a decoder or launch a
guest. It reads source archives without extracting executable build scripts.
Only the explicitly verified wrapper portfile patch is applied in an isolated
output directory; no upstream checkout is modified.

Exit 0 means the locked provenance checks passed, **not** permission to ship an
engine. The resulting `audit.json` always keeps
`upstream_redistribution_approved: false`. Errors exit nonzero. Reused output,
wrong wrapper/header tree, archive/member/recipe/notice checksum mismatch,
header/binary/version/license mismatch, inconsistent library configurations
or unexpected license-enabling options fail. Cached tampering is rejected
without downloading over it. The public report filters configure switches;
raw compiler output and arbitrary paths never enter it.

Local full audit passes. The normal Windows build passes all six CTest suites,
including nine portable metadata/rejection/privacy tests. Hosted Windows/Linux
policy tests and a separate Windows metadata audit run on relevant pushes; the
metadata workflow uploads only `audit.json`, never libraries, helper binaries,
source archives or compiler logs. See each PR for hosted results. Neither these
tests nor metadata queries establish guest media decoding or security clearance.

## Remaining release holds and next implementation

1. **Separate FDK AAC linkage:** the unmodified pinned baseline and older
   engines retain this dependency. The [native AAC replacement](aac-replacement.md)
   now removes it from the verified patched research target, with real decoding,
   adapter, active-graph/link-map and repeated G2 tests. That evidence closes
   this particular link-dependency hold only for the new exact patched build.
   Unsupported AAC configurations remain documented. Muting audio or merely
   moving an older engine to another process does not remove its dependency.
2. **FFmpeg release materials:** the [source input kit](ffmpeg-source-kit.md)
   reconstructs the complete patched FFmpeg tree, preserves all source patches,
   full wrapper/vcpkg source snapshots and notices, and verifies the result
   offline. This supplies source inputs without proving binary correspondence.
   Independently build the complete pinned recipe,
   check selected nested dependencies and build tools, and assemble exact source,
   patches, notices and the applicable static-link/relink materials. This audit
   identifies source inputs and reported license options, not a complete release
   source bundle or binary reproducibility proof.
3. **Other dependencies/resources/runtime:** finish the Windows link-graph
   review, LGPL handling for OpenAL/libusb, Apache/GPL version selection,
   embedded fonts/resources, toolchain-runtime terms and attribution/source
   closure. The 54 recursive Git pins alone are not a complete SBOM.

## Source input kit validation

The [local source-kit result](../research/results/2026-10-18-ffmpeg-source-kit.json)
records 8,563 reconstructed source files, all 12 ordered source patches, two
byte-identical offline assemblies, complete ZIP reconstruction checks and a
standalone offline directory check using the packaged verifier. All nine local
CTest suites pass, including 12 source-kit policy tests. The result contains
only source identifiers and validation outcomes. Hosted Windows/Linux results
are reported separately in the PR; no binary rebuild or guest run is implied.

## PR #9 completed-build review

[Hosted strict build 39095967989](https://github.com/Rajinder798/ps4-runtime/actions/runs/39095967989)
passed the final patch/header hashes and staged tree
`5ff7e99291a218fa58df2aa0d1159f591b507bae`, checked 54 recursive pins, linked the
engine and passed strict CLI help. All four Windows/Linux push/PR regression
jobs passed. No compiler error or warning was found in the new service code.

Remaining log items include expected negative Windows platform probes,
optional/backend detection, LF/CRLF notices, upstream CMake deprecations, an
unused compiler flag, and warnings in LibreSSL/libusb/fmt/ImGui. They did not
block the research build and are not newly introduced service-code defects.
Dependency-wide correctness/security review remains open; in particular a
successful build does not by itself clear callback-cast or packing warnings.
PR #9 was merged with the owner's explicit authorization after this review.
