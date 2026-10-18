# FFmpeg source input kit

Gate: G3 release prerequisite. This kit supplies verified source **inputs**, not
a complete engine release or evidence that the prebuilt libraries were rebuilt.
`upstream_redistribution_approved`, `independent_binary_rebuild_verified` and
`static_relink_kit_complete` remain false.

## Contents and provenance

The kit retains the full pinned FFmpeg 7.1.1 source archive, vcpkg snapshot
`df8bfe519564ae001903e5cdd32af0999531ef71` and ext-ffmpeg-core wrapper snapshot
`94dde08c8a9e4271a93a2a7e4159e9fb05d30c0a`. Checksums are recorded in
`config/ffmpeg-audit.json` and `config/ffmpeg-source-kit.json`. The complete
snapshots retain build helpers, nested port recipes, tool acquisition manifests
and their notices; they do not include every binary/tool/source downloaded by
those recipes. No upstream script is executed during assembly or verification.

`source/ffmpeg/` contains all FFmpeg source files after applying the 12 patches
in the exact order listed by the pinned port. `changes/ffmpeg.diff` records their
combined source changes. `recipe/ports/ffmpeg/portfile.cmake` separately contains
the port after the wrapper's `ffmpeg.patch`. That wrapper patch changes the
recipe, not the FFmpeg source directly. The original snapshots preserve both
sets of patches. The five FFmpeg root license texts and the wrapper/vcpkg root
notices are also copied to `notices/`; per-file notices remain in the source.
These components retain their own licenses, not this project's license grant.

The kit includes this guide, the original GPL-2.0-or-later assembly tool, its
contracts and the project LICENSE. `manifest.json` inventories every payload
file with its size, SHA-256 and executable bit. It is an inventory, not a
signature or independent trust anchor. Compare contracts/tooling with the
reviewed repository revision before relying on a kit received from elsewhere.

## Assemble and verify

Python 3.9+ and Git are sufficient on Windows or Linux. No compiler is required.
Run from the repository; use a fresh output under ignored `build/`:

```powershell
python tools/ffmpeg_source_kit.py assemble --output build/release-audit/source-kit-001
python tools/ffmpeg_source_kit.py verify --kit build/release-audit/source-kit-001/kit
python tools/ffmpeg_source_kit.py verify --kit build/release-audit/source-kit-001/ffmpeg-source-kit.zip
```

The first command downloads checksum-locked snapshots into
`build/release-audit/source-kit-cache`, applies patches in isolated temporary
Git repositories, constructs a kit directory and deterministic ZIP, and verifies
the ZIP by independently reconstructing its payload. To assemble again without
network access, add `--offline` and choose another fresh output. Missing or
modified cached input fails; it is never silently downloaded over. ZIP paths,
timestamps, order and permission metadata are fixed. Identical inputs/tooling
produce identical ZIP bytes locally; byte identity across compression-library
versions is not asserted. The normalized source-tree checksum is independent
of timestamps, checkout path and host executable-bit behavior.

Both `verify` forms always work offline. They check every input checksum,
reapply all patches, verify the pinned source-tree checksum, reconstruct the
expected notices/recipes/tooling and compare every file, including the manifest.
Missing, modified and extra files fail even if a supplied manifest was edited
to agree. Symlinks, hardlinks, devices, traversal paths, case collisions and
oversized archives are rejected. ZIP verification also checks permissions.
Existing engine checkouts and their indexes are not modified. Host logs,
libraries and engine executables are never packaged.

## Independent rebuild still required

The archived wrapper workflow records this Windows installation request:

```text
vcpkg --overlay-triplets=./triplets install ffmpeg[avcodec,avfilter,avdevice,avformat,swresample,swscale]:x64-win-llvm-static-release
```

This uses the wrapper triplets and the patched vcpkg port; a generic modern
`vcpkg install ffmpeg` does not reproduce it. The full snapshots allow preparing
that source environment in a fresh **space-free** build path. The pinned port
explicitly rejects spaces in its source path. Bootstrap vcpkg, acquire tools and
build only as a separate deliberate step; this kit does not run those scripts.
The archived workflow is provenance, not a script to run blindly: it contains
runner-specific paths and resets an existing checkout. Use fresh directories.

Before a release, independently build the pinned recipe, retain actual configure
and link commands, check downloaded tool and selected dependency closure, match
the output to the libraries used by the engine, and run the native AAC/adapter
and strict startup regressions. The archived feature request includes avdevice;
the engine wrapper links six libraries excluding avdevice. No tool version,
build result or binary equivalence is inferred from source reconstruction.

For static linking, a release plan must also provide the applicable application
source/object and relink materials, instructions and all remaining dependency
notices/source. This kit has no engine object files or tested relink procedure.
It does not establish the exact corresponding source of the existing prebuilt
libraries. See [release audit](release-audit.md) and FFmpeg's
[distribution guidance](https://ffmpeg.org/legal.html), which calls for matching
source, changes and build information. LGPL 2.1 section 6 addresses the
[materials needed to modify and relink a linked work](https://www.gnu.org/licenses/old-licenses/lgpl-2.1.html#SEC6).
The complete license terms and the eventual distribution arrangement govern.

## Validation

Portable tests exercise real Git patch application, wrong patch order, tampered
inputs/source/manifest, missing/extra files, archive safety and deterministic
packing. A separate source-kit workflow assembles the real snapshots on Windows
and Linux, verifies the directory and ZIP offline, and compares two assemblies.
It uploads only the public summary, never the kit or source archives. Local and
hosted results are reported separately in the PR. No guest code is executed by
this milestone.
