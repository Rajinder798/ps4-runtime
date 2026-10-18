# Native FFmpeg AAC replacement

This G3 release prerequisite replaces the patched research engine's separately
linked FDK AAC decoder with FFmpeg's native `aac` decoder. The selected FFmpeg
libraries were [audited separately](release-audit.md); no new decoder library
or proprietary SDK is introduced. This is a deliberately bounded research
implementation, not a claim of complete AJM/AAC compatibility or guest audio.

## Supported contract and risks

- AAC-LC, 1024 samples per channel, mono/stereo. ADTS uses one unprotected
  raw-data block per frame. Raw mode supplies the standard two-byte AAC-LC
  AudioSpecificConfig from AJM's indexed rate/channel configuration and accepts
  one complete access unit per call. Concatenated raw units are rejected when
  they produce additional queued frames; they are not silently dropped.
- Interleaved S16, S32 and float PCM, converted by libswresample at the original
  sample rate. Bitrate is reported as unknown (zero). HE-AAC/SBR, CRC-protected
  ADTS, multiple ADTS raw blocks, PCE/other channel layouts, surround-order
  flags and other profiles/frame sizes return explicit errors.
- Own refcounted, padded packets, decoder frames and conversion buffers. No
  caller input pointer is retained or passed unpadded to FFmpeg. Partial ADTS
  consumes nothing. Other decoder errors record actual accepted input bytes
  and propagate failure; malformed payloads do not become successful silence.
  AJM `internal_result` carries FFmpeg diagnostic values, not a reproduced FDK
  error-number ABI; full console error-code conformance is not established.
- The AJM adapter preflights actual next-frame output capacity before decoding,
  including a channel change from the preceding frame. Short output consumes
  nothing and changes no gapless state. Byte-oriented sparse writes preserve
  PCM across odd chunk boundaries. Gapless skip/total limits cannot overrun
  decoded data; the existing two-frame prefill/nondelay policy is retained.
- Reset releases/recreates decoder state; invalid initialization/flags/layouts
  fail instead of indexing a rate table or dereferencing an unopened decoder.
  Querying format before ADTS establishes channels returns an unknown channel
  mask instead of calling the upstream mask helper with zero.

The AAC coverage is narrower than the unmodified upstream FDK implementation.
Those unsupported configurations are a compatibility limit of this research
build; no previously established commercial/guest audio compatibility is
claimed. The inspector, fixed synthetic probe and their CLI contracts remain
independent of this backend.

FFmpeg's [send/receive API](https://ffmpeg.org/doxygen/7.1/group__lavc__encdec.html)
defines packet/frame state and EAGAIN handling. The replacement selects the
decoder by name `aac`, checks all allocation/open/send/receive/convert results,
and rejects extra output rather than discard a queued frame. The converter
uses the documented [libswresample API](https://ffmpeg.org/doxygen/7.1/group__lswr.html).
Native codec execution retains the engine process trust model; these checks do
not establish a memory security sandbox or a dependency-wide security audit.

## Tests and original fixtures

`tools/make_aac_tones.cpp` generates original 440 Hz mono (44.1 kHz) and
440/880 Hz stereo (48 kHz) sine input and encodes it with the Windows Media
Foundation AAC-LC encoder. Eight 1024-sample input blocks plus encoder drain
produce the committed fixture header. No game, downloaded media or firmware is
used. The independent source frequencies and amplitude provide the decoding
oracle; ADTS and raw modes additionally must yield identical PCM.

The [encoder API](https://learn.microsoft.com/en-us/windows/win32/medfound/aac-encoder)
documents 16-bit PCM input, the sample rates, ADTS payload and 1024-sample
blocks. The generator is only a test-development tool; it is not a runtime
dependency, and CI uses the checked-in fixtures. Encoded bytes may vary with
the Windows encoder implementation; no bit-exact cross-version encoder
reproduction is claimed.

Host tests compile the same original decoder header used by the engine and
the **actual patched `ajm_aac.cpp`**. Only logging and the small channel-mask
utility are isolated in adapter tests; no PS4 service/export is replaced by a
test success stub. Tests cover:

- Independent tone energy/frequency/channel-order checks, ADTS/raw equality,
  S16/S32/float conversion and exact reset reproducibility.
- Every truncation of the first frame, corrupted sync/payload, invalid raw
  initialization, unsupported layouts/flags, concatenated raw packets, and a
  Windows inaccessible guard page immediately after caller input.
- Actual adapter output guards, exact input/output accounting, odd sparse
  boundaries, 37-sample skip plus a 513-sample total limit, capacity rejection,
  prefill, reset, raw configuration and channel-change capacity rechecking.
- Portable framing/range checks, deterministic malformed-header cases and
  randomized bounded-input invariants. Portable tests do not link FFmpeg or
  execute a decoder. Link-evidence policy tests reject FDK targets, sources,
  include/link paths, symbols and incomplete evidence.

## Build, linkage proof and reproduction

The existing [strict build recipe](startup-research.md#build-and-run) installs
and hashes `aac_decoder.h` alongside the audit/service headers. The manifest
also pins the exact expected staged tree. The builder verifies it before/after
compilation, runs the native tests and inspects actual CMake file-API/link-map
evidence before reporting a qualifying engine build. The homebrew runner
rejects old FDK builds, missing AAC test success or stale patch/header/tree data.

The patch removes both `add_subdirectory(aacdec)` and the `fdk-aac` link target.
The original recursive source pins/notices remain intact in the local checkout;
absence from the **active compiled graph** does not mean that the separately
pinned source directory was deleted. Old `.lib` files left in a reused ignored
build directory cannot satisfy the active-graph/link-map checks.

After a strict build, these may also be run separately from the x64 clang-cl
developer environment, using a new native-test output directory:

```powershell
python tools/test_aac_backend.py --source build/upstream/shadps4-strict --build build/upstream/windows-x64-strict --output build/aac/check-001
python tools/audit_engine_linkage.py --build build/upstream/windows-x64-strict --output build/aac/linkage.json
```

The linkage audit requires no configured FDK target/source/include/link input
and no FDK object/API symbol in the generated map; native AAC and AJM symbols
must be present. The builder generates a fresh map in its normal link step.
Evidence consistency is not independent binary attestation. Full maps, native
test binaries, compiler logs and private host data remain local/ignored. CI
uploads only the test/linkage summaries in the strict evidence directory.

The [local result](../research/results/2026-10-18-aac-replacement.json) records a
passing full engine rebuild/strict CLI help, native decoder and 125 actual
adapter checks, all eight CTest suites, and positive FDK-absence evidence from
the active graph/link map. Two fresh-profile G2 runs passed with zero unresolved
imports, both expected messages separated by 1,999,767 and 2,000,531 microseconds,
and requested process-tree cleanup. Hosted results are tracked in the PR.
Host AAC tests do not prove a guest audio job, speaker output, interactive
homebrew or game audio.

## Release implications

This removes the **separate FDK link dependency** from the locally verified
patched engine. The unmodified baseline and older engine builds still
have their original dependency. A successful new linkage audit applies only to
that exact patched build.

Engine redistribution is still not approved. FFmpeg corresponding source and
relink/notice materials, the remaining Windows dependency/resource audit,
OpenAL/libusb handling and toolchain-runtime obligations remain open. Replacing
one dependency does not complete those release requirements.
