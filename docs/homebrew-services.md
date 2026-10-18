# Second homebrew: file and worker-thread roundtrip

Gate: G2 coverage expansion before G3 launch integration. This is an original
OpenOrbis application, independent of the SDK's hello_world sample. It runs in
the same pinned, patched shadPS4 research process; it adds no engine code to the
standalone inspector/probe and does not clear engine redistribution holds.

## Acceptance and implementation

The reviewed [source](../research/homebrew/service_roundtrip/main.cpp) uses
`sceKernelOpen/Read/Close` to read exactly 256 bytes from `/app0/challenge.bin`.
Two `scePthreadCreate` workers transform separate 128-byte halves using
`output[i] = ((input[i] XOR 0xa5) + i) modulo 256`. Main joins both threads and
checks their return arguments. It creates `/data/service-result.bin`, writes
and closes the result, reopens it, seeks to offset 128 and back to zero, and
checks both halves against its own computed output. Only then does it print:

```text
service-roundtrip: begin
service-roundtrip: PASS threads=2 bytes=256 seek=128
```

Every checked operation has an explicit guest failure message. The fixture
uses PS4 kernel open flag values, rather than the SDK's generic musl constants.
It intentionally waits in a sleep loop after completion/failure so the existing
supervisor owns shutdown. Natural guest exit is not tested.

The runner's `--profile service-roundtrip` selects only the reviewed source and
converted ELF hashes in [the contract](../config/service-roundtrip.json).
It preserves exact engine/patch/header checks, strict imports, event ordering,
bounded output/time and Job Object cleanup. It does not accept arbitrary guest
hashes or expected messages. The default profile retains hello_world's hashes,
messages and minimum 1.9-second interval.

Each run creates an isolated app mount with the verified fixture and a fresh
random challenge. The host never prepares a result file. After the guest's
strict completion events and confirmed tree cleanup, the host independently
calculates all 256 expected bytes and requires an exact output-file match.
Missing, short, oversized, altered or previous-challenge results fail. The
result records challenge/output hashes; the actual challenge, output, structured
trace and logs remain in that local session for reproduction and inspection.

## Reproduction

Use the [existing pinned toolchain and strict engine](startup-research.md#build-and-run),
Python 3.12+, Windows x86-64 and a compatible Vulkan host. The compiler used to
establish this fixture hash is the locked LLVM-MinGW 20261006 (Clang 23.1.3)
already used by the homebrew workflow. The source and converted ELF hashes are
checked during build; a different output fails rather than updating the lock.

```powershell
python tools/build_homebrew.py --sample service-roundtrip --llvm-bin build/tools/llvm-mingw-20261006-ucrt-x86_64/bin --inspector build/native/ps4-runtime.exe
python tools/run_homebrew_startup.py --profile service-roundtrip --engine build/upstream/windows-x64-strict/shadPS4.exe --engine-report build/upstream/strict-evidence/strict-build.json --fixture build/homebrew/service-roundtrip/service_roundtrip.oelf --supervisor build/native/ps4-startup-supervisor.exe --output build/startup/services-001 --timeout 30
```

Visual Studio native builds place the inspector/supervisor under `Release/`.
Each runner output must be a new directory. For repeated success and real guest
failure cases in one command, choose another new output:

```powershell
python tests/service_guest_tests.py --engine build/upstream/windows-x64-strict/shadPS4.exe --engine-report build/upstream/strict-evidence/strict-build.json --fixture build/homebrew/service-roundtrip/service_roundtrip.oelf --supervisor build/native/ps4-startup-supervisor.exe --output build/startup/services-acceptance
```

This opt-in acceptance script runs two successes with different random inputs,
then removes or truncates the staged input in two separate sessions. It requires
actual guest entry, the specific guest failure line, rejection of success and
confirmed cleanup for both negative cases. It changes only the staged input;
it does not substitute guest code, engine services or audit events. It writes
`summary.json` only after every case passes its expectation. These GPU-dependent
guest tests are separate from CTest and hosted compiler/policy tests.

## Validation and limits

Local results and input identifiers are recorded in the
[public evidence summary](../research/results/2026-10-18-homebrew-services.json).
All nine local CTest suites pass, including 18 startup contract tests. A repeated
fixture build produced the same converted ELF hash. The original hello_world
guest regression also passed, including its two-second sleep and tree cleanup.
Hosted Windows/Linux regression results and both Windows fixture builds are
reported separately in the PR; hosted builds do not execute a PS4 guest.

These tests demonstrate these operations for one small application. They do not
establish complete filesystem/pthread conformance, concurrent shared-memory
correctness, save persistence across launches, guest rendering, input, audio or
commercial playability. Existing missing optional sample assets/fonts/modules,
PT_INTERP/SCE metadata diagnostics and host Vulkan extension/format warnings
remain; strict import counts are zero. No proprietary module is supplied to
silence those diagnostics. Job Objects control process lifetime and are not a
guest memory security sandbox.

The new application, harness changes and tests are original GPL-2.0-or-later
source. The SDK/engine retain their own terms and remain local build inputs.
No SDK, fixture binary, engine binary, game, firmware or keys are committed or
uploaded. FFmpeg corresponding-source/relink materials and the remaining
dependency/runtime/resource reviews in [the release audit](release-audit.md)
still block engine redistribution. The next functional work is the stable
Windows launch contract; installer distribution depends on those release holds.
