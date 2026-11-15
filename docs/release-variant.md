# Release candidate engine variant: release-no-libressl

Date: 15 November 2026. Status: local research build and license inventory verified.
Engine redistribution remains blocked. This engineering effort addresses release hold 3
following [decision 0003](decisions/0003-release-gpl-version.md). It distributes no binaries
and does not modify the strict research engine.

## Purpose and background

[Decision 0003](decisions/0003-release-gpl-version.md) resolved the GPL version for binary engine
releases to **GPL-3.0-or-later** (while keeping the original source license at GPL-2.0-or-later).
The decision established that:
- Abseil (Apache-2.0) and 17 of 25 included Vulkan headers (Apache-2.0 only) require GPL-3.0.
- Dual-licensed components (FreeType, zstd, dr_flac, stb) are satisfied under their selected licenses.
- **LibreSSL**, used for HTTP/TLS networking and P2P payload cryptography, contains OpenSSL and SSLeay
  advertising clauses that forbid placing the code under the GNU General Public License. As a result,
  LibreSSL is incompatible with both GPL-2.0 and GPL-3.0 and acts as a binary release blocker.

To eliminate this blocker without waiting for a full network stack rewrite (e.g., OpenSSL 3.x or
Windows SChannel), the project developed the `release-no-libressl` engine variant. This variant
builds the engine without vendored LibreSSL, replacing its P2P cryptographic operations with
Windows Cryptography Next Generation (CNG / `bcrypt.dll`), and letting HTTP/TLS fallback to
upstream's no-SSL path.

## The release-no-libressl patch

The variant patch (`research/shadps4/release-no-libressl.patch`, SHA-256 `427cc1fa...`) is layered
cleanly on the strict research patch (SHA-256 `1927fd9f...`; patched tree `854265c1...`).
Combined with the CNG header, the expected source tree is `ac4788d837bd728fc17b2a037b2a82294e5b9ef7`.

Key changes introduced by the patch:
1. **CMake build option:** Introduces `PS4RT_WITHOUT_LIBRESSL` (default OFF). When ON, the vendored
   LibreSSL directory in `externals/CMakeLists.txt` is completely bypassed. Target `shadps4` defines
   `PS4RT_P2P_CRYPTO_CNG` and links the Windows system import library `bcrypt.lib`.
2. **P2P payload crypto routing:** In `src/core/net/p2p_crypto.cpp`, all OpenSSL includes
   (`<openssl/crypto.h>`, `<openssl/evp.h>`, `<openssl/hmac.h>`, `<openssl/rand.h>`) are replaced
   under `#ifdef PS4RT_P2P_CRYPTO_CNG` with the internal header `"core/net/p2p_crypto_cng.h"`.
3. **HTTP/TLS fallback:** Without LibreSSL, `cpp-httplib` compiles without `CPPHTTPLIB_OPENSSL_SUPPORT`.
   `libSceHttp` uses upstream's existing fallback code path.

## Cryptographic implementation and equivalence verification

The header `research/shadps4/p2p_crypto_cng.h` provides drop-in Windows CNG equivalents for the four
primitives used by shadPS4's P2P subsystem:
- **AES-128-CFB128:** Built on top of `BCryptEncrypt` using raw AES-ECB block operations. CFB mode
  is a stream mode where ciphertext feedback is encrypted with ECB and XORed with plaintext.
- **HMAC-SHA1:** Computed via `BCryptCreateHash`, `BCryptHashData` and `BCryptFinishHash` with `BCRYPT_ALG_HANDLE_HMAC_FLAG`.
- **Cryptographic Random:** `BCryptGenRandom` using `BCRYPT_USE_SYSTEM_PREFERRED_RNG`.
- **Constant-time comparison:** `ConstantTimeEqual` provides a timing-attack resistant byte comparison.

### Automated tests: CTest `p2p-crypto-cng`

`tests/p2p_crypto_cng_tests.cpp` provides automated unit testing for the CNG implementation:
- **NIST SP 800-38A F.3.13:** Validates 64-byte AES-128-CFB128 ciphertext matches the official NIST test vector.
- **Prefix consistency:** Tests all partial lengths from 0 to 64 bytes to verify stream behavior.
- **RFC 2202 HMAC-SHA1:** Validates standard HMAC test vectors, including keys longer than the block size.
- **Zero-length payloads:** Checks the empty-message HMAC case used by `DeriveCommunicationId`.
- **RNG & constant-time equality:** Confirms random generation outputs differ and `ConstantTimeEqual` behaves correctly.

All tests pass under CTest.

### Equivalence verification: LibreSSL comparison

A dedicated verification fixture (`tests/p2p_crypto_libressl_compare.cpp`) compares the CNG implementation
directly against the strict engine's own LibreSSL static library (`crypto.lib`), replicating the exact OpenSSL
calls made by upstream shadPS4.

It tests:
- 2,000 rounds of AES-128-CFB128 encryption and decryption across payload lengths from 0 to 1,499 bytes with random keys and IVs.
- 2,000 rounds of HMAC-SHA1 across varying message lengths.
- Constant-time comparison equivalence against LibreSSL's `CRYPTO_memcmp`.

Result: **8,000 cases tested, 0 mismatches.**

To reproduce the manual comparison in the Visual Studio x64 developer environment:
```powershell
clang-cl -std:c++20 /MD /O2 -I research/shadps4 `
  -I build/upstream/shadps4-strict/externals/libressl/include `
  tests/p2p_crypto_libressl_compare.cpp `
  build/upstream/windows-x64-strict/externals/libressl/crypto/crypto.lib `
  bcrypt.lib ws2_32.lib advapi32.lib /Febuild/p2p_compare.exe
build/p2p_compare.exe
```

## Building the variant

The variant is built into isolated directories (`build/upstream/shadps4-release-variant` and
`build/upstream/windows-x64-release-variant`) so the strict research engine remains untouched:

```powershell
python tools/build_release_variant.py --jobs 8 --seed-from build/upstream/shadps4-strict
```

The script:
1. Validates the base strict contract and hashes.
2. Seeds a fresh checkout from `build/upstream/shadps4-strict` and resets to `e6c79a5f`.
3. Applies the strict research patch and headers, verifying the tree matches `854265c1`.
4. Applies `research/shadps4/release-no-libressl.patch` and copies `src/core/net/p2p_crypto_cng.h`.
5. Confirms the final source tree matches the contract (`ac4788d837bd728fc17b2a037b2a82294e5b9ef7`).
6. Configures CMake with `-DPS4RT_WITHOUT_LIBRESSL=ON`.
7. Compiles `p2p_crypto.cpp.obj` first to surface any integration regressions early, then builds `shadPS4.exe`.
8. Verifies the CLI help output, checks git status for clean source, and writes build evidence to
   `build/upstream/release-variant-evidence/release-variant-build.json`.

Observed build artifact:
- Binary: `build/upstream/windows-x64-release-variant/shadPS4.exe`
- Binary SHA-256: `5a50c4e8e7ae615c7d85fc85e810ae99cdbdd331c18c347439ebfebcd7aa575f`
- Source tree: `ac4788d837bd728fc17b2a037b2a82294e5b9ef7`

## Link inventory verification

The engine link inventory (`tools/engine_link_inventory.py`) was run against the variant using `--variant release-no-libressl`:

```powershell
ninja -C build/upstream/windows-x64-release-variant -t deps > variant-deps.txt
python tools/engine_link_inventory.py --variant release-no-libressl `
  --map build/upstream/windows-x64-release-variant/ps4-runtime-research.map `
  --engine build/upstream/windows-x64-release-variant/shadPS4.exe `
  --engine-report build/upstream/release-variant-evidence/release-variant-build.json `
  --source build/upstream/shadps4-release-variant `
  --deps variant-deps.txt `
  --output build/link-inventory/variant-002/inventory.json
```

Results (recorded in `research/results/2026-11-15-release-variant-inventory.json`):
- **Status:** `passed` (0 errors).
- **LibreSSL absence:** Confirmed absent from the static link graph (0 linked libraries) and from the compiled source closure (0 files in `source_closure.components`).
- **Linked libraries:** 93 static libraries mapped to reviewed components (`bcrypt` import library mapped to `windows-sdk`).
- **DLL imports:** 77 imports, all Windows system DLLs or MSVC runtime (`third_party_dlls_imported` is empty).
- **Release blockers:** LibreSSL is no longer one. Since [decision 0004](decisions/0004-lgpl-relinking.md),
  the only blocker is **FFmpeg**, a static LGPL library from a prebuilt download, until it is built from source (hold 2).
- **Enforcement:** The contract fails closed if `libressl` is linked or if any of its source files are compiled into the binary.

## Research runner variant support

To prepare for bounded guest regressions on the variant engine (`hello-world`, `service-roundtrip`, `save-roundtrip`, and `save-counter`), the research runners support variant contract validation:

- **`tools/run_variant_startup.py`:** A dedicated startup runner for the variant engine. The shared `tools/run_homebrew_startup.py` is hash-pinned by reviewed G4 physical safety attestations (`research/results/2026-10-25-issue39-host-safety-v2.json`) and guarded by `tests/pad_disconnected_close_recorded_tests.py`. Following the architectural pattern established by `run_save_roundtrip.py` and `live-av-v2`, `run_variant_startup.py` reuses the unchanged helpers from `run_homebrew_startup.py` (hashing, audit reading, session preparation and Windows supervision) while implementing variant contract validation for `hello-world` and `service-roundtrip`.
- **`tools/run_save_roundtrip.py`:** Updated to accept `--variant release-no-libressl`, validating the variant contract when specified and preserving strict engine checks when omitted.
- **`tools/run_save_counter.py` & `tools/run_save_persist.py`:** Forward the optional `--variant` argument to save runner verification.
- **Shared check:** both runners call `tools/release_variant.py`, which finds the variant's contract through the `contract` field of `config/engine-link-components.json` rather than its name.
- **Contract verification:** Validates `config/release-variant.json` and `config/engine-link-components.json`, checking `status == "release_variant_engine_built"`, base hashes and tree matching the strict research contract, variant patch and header hashes, patched tree `ac4788d8...`, CMake defines `{"PS4RT_WITHOUT_LIBRESSL": "ON"}`, and executable SHA-256.
- **Unit test coverage:** `tests/save_runner_tests.py` includes comprehensive test cases verifying positive variant validation, rejection when variant flag is omitted, unknown variant rejection, tampered report fields, tampered files on disk, and base contract mismatches. All 45 local CTests pass cleanly.

## Guest regression (15 November 2026)

**PASSED on the first attempt, with no retry.** The owner approved one run. Full data is in
[the result record](../research/results/2026-11-15-release-variant-guest-run.json).

The run used the variant engine (tree `ac4788d8…`, binary `5a50c4e8…`), the pinned fixtures and
the variant runners. Every input was checked against its contract before launch.

| Launch | Runner | Guest output | Host check |
| --- | --- | --- | --- |
| `hello-world` | `run_variant_startup.py` | `Hello world! Waiting 2 seconds!`, then `Done. Infinitely looping...` | strict-audit markers |
| `service-roundtrip` | `run_variant_startup.py` | `PASS threads=2 bytes=256 seek=128` | result file equals the host's calculation |
| `save-counter` | `run_save_counter.run_attempt`, fresh store | `PASS previous=0 count=1` | `counter.bin` decodes to 1 and is valid; the store copy is identical |

- Every launch used the variant engine, whose hash matches its build report.
- Every launch reached guest entry with **zero unresolved imports**, so removing LibreSSL left no
  import the fixtures need unresolved.
- Each launch was stopped on request after its result line: exit 125, forced termination, root exit
  and an empty tree verified. No normal-close claim is made.
- The run did not exercise networking, and `save-counter` ran once (0 to 1). Carry-over across
  launches was shown earlier on the strict engine, not on this variant.

Raw evidence stays local under `build/variant-guest/run-001`.

## Strict post-build suites on the variant (15 November 2026)

**PASSED.** The variant now meets the strict engine's post-build bar. Full data is in
[the result record](../research/results/2026-11-15-release-variant-strict-suites.json).

`tools/build_release_variant.py` runs the strict build's own checks after building. With
`--tests-only`, it runs just those checks on an existing build, after confirming the checkout tree
(`ac4788d8…`) and the executable hash. The executable was unchanged afterwards.

| Check | Result |
| --- | --- |
| AAC decoder suite | passed: 26,240 backend checks, the same as the strict engine, plus the adapter test |
| Host-exception suite | passed: all 6 cases |
| FDK linkage audit | passed: no FDK AAC objects linked; native FFmpeg AAC present |

`research_contract.verify` (and the two suite runners) now take an optional reviewed tree. The
strict build's calls are unchanged. A first attempt stopped before running any suite, because the
check accepted only the strict tree.

**Variant runs now require these suites.** `tools/release_variant.py` refuses a variant build report
unless `strict_tests_run` is true, both suites passed, the AAC backend is FFmpeg and FDK is absent.
Removing that requirement fails five test cases.

## Scope, limitations, and next steps

- **Network HTTPS limitation:** Because LibreSSL is omitted and TLS replacement is deferred, `libSceHttp`
  does not support HTTPS in this variant.
- **Operating system scope:** Uses Windows CNG APIs (`bcrypt.h`, `bcrypt.lib`); Windows 10/11 x86-64 only.
- **Guest execution:** one approved regression of three launches passed (see below). It shows the
  variant still runs the supported homebrew. It does not exercise networking.
- **Redistribution holds:** Resolving the LibreSSL blocker clears one major licensing requirement.
  Remaining holds (LGPL relinking materials, VC++ runtime terms, fonts/notices, FFmpeg corresponding source)
  continue to block public binary distribution.
