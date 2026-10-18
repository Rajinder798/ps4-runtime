# Owned-process Windows render audio research

Gate: G4 Windows audio-path increment. The unchanged combined homebrew can now
use SDL's WASAPI backend, with independently checked PCM from Windows' audio
engine for the owned shadPS4 process tree. This extends the earlier SDL disk
result to an active Windows render session. It does not establish acoustic
speaker/headphone output, hardware/DAC behavior or full G4 completion.

## Boundary and evidence

`--audio-backend wasapi --capture-helper <path>` is available only for the fixed
`interactive-av` research profile with `--shutdown window-close`. The normal
research default stays `disk`; registration, shortcuts and supported Settings
remain unchanged. The new native `ps4-process-audio-capture` target is separate
from the inspector and engine. It links Windows-provided COM/audio APIs and is
not an engine patch or a new third-party dependency bundle.

The runner sets child-local `SDL_AUDIO_DRIVER=wasapi`, removes disk-output hints
and requests 48 kHz stereo float output. After the first guest state is ready,
the helper requires an active default render endpoint and a matching active
render session for the engine PID. It verifies that its sibling supervisor has
that engine as a direct child, that the engine executable file matches the
verified path, and that the engine is still alive. A process handle is retained
through capture. The native checks run before capture activation; unrelated
processes are rejected without creating capture files.

The helper activates `VAD\Process_Loopback` with the include-target-process-tree
mode. It exposes no microphone, whole-endpoint or exclude-tree capture mode.
Microsoft documents that this process filter excludes other applications' audio
and is independent of the physical endpoint. It requires Windows build 20348 or
later; ordinary Windows 10 builds such as 19045 cannot run this research capture.
See the [Microsoft process-loopback sample description](https://learn.microsoft.com/en-us/samples/microsoft/windows-classic-samples/applicationloopbackaudio-sample/)
and [activation parameters](https://learn.microsoft.com/en-us/windows/win32/api/audioclientactivationparams/ns-audioclientactivationparams-audioclient_process_loopback_params).
The helper is original project code using the documented API; Microsoft sample
implementation files are not copied into this repository.

COM activation has a five-second wait, readiness an eight-second host deadline,
and capture a finite budget of at most 60 seconds/16 MiB. Windows converts the
process stream to F32LE stereo at 48 kHz. Packet silent flags produce explicit
zero samples; discontinuity/timestamp-error counts are recorded. The packet API
and stream resources are released on success/failure. The helper never changes
endpoint mute/volume; its report records their initial values, active-session
evidence, exact PIDs, format, frame/packet counts and stop reason.

The host holds the initial neutral guest state for at least 0.6 seconds after
capture readiness, then uses the existing owned-window key/image transport.
The same independent PCM oracle requires sustained silence, the challenge's
left/right fundamentals, then restored silence, using unchanged Goertzel/RMS
thresholds and the combined fixture's 3–20 second frame-count bound. All three
Vulkan images, exact guest pad records, strict entry/completion/import evidence
and normal engine window close must also pass. The raw captured file's size
must equal the native report's frame count times eight bytes. Missing/foreign
PID, wrong filter, format, active-session evidence, helper failure, forced helper
termination or a host-requested capture stop cannot grant Windows-render success.

The helper normally notices the engine's exit and stops itself. The runner waits
for completion, with a bounded stop/kill fallback and confirmed helper exit on
errors. An input abort must clean both the engine tree and capture helper; that
cleanup is not a passing guest result. Silent/swapped PCM can complete guest
graphics/input/close while correctly failing combined audio acceptance.

## Reproduce and tests

Use the existing Windows x86-64/Vulkan/strict-engine prerequisites and all six
fixed fixtures. Build the native targets with the normal CMake commands in
[development](development.md). For Visual Studio, native helpers are in `Release/`.
The render endpoint must be active. A physical controller is not needed.

```powershell
build/native/ps4-process-audio-capture.exe --preflight
python tools/run_videoout_research.py --profile interactive-av --shutdown window-close --audio-backend wasapi --capture-helper build/native/ps4-process-audio-capture.exe --engine build/upstream/windows-x64-strict/shadPS4.exe --engine-report build/upstream/strict-evidence/strict-build.json --fixture build/homebrew/interactive-av/interactive_av.oelf --supervisor build/native/ps4-startup-supervisor.exe --output build/windows-audio/single-new
python tests/windows_audio_guest_tests.py --engine build/upstream/windows-x64-strict/shadPS4.exe --engine-report build/upstream/strict-evidence/strict-build.json --supervisor build/native/ps4-startup-supervisor.exe --capture-helper build/native/ps4-process-audio-capture.exe --fixture build/homebrew/interactive-av/interactive_av.oelf --hello-world build/homebrew/hello-world/hello_world.oelf --service-roundtrip build/homebrew/service-roundtrip/service_roundtrip.oelf --videoout-pattern build/homebrew/videoout-pattern/videoout_pattern.oelf --pad-videoout build/homebrew/pad-videoout/pad_videoout.oelf --audio-pattern build/homebrew/audio-pattern/audio_pattern.oelf --output build/windows-audio/acceptance-new
```

Choose new output directories. `videoout-result.json` retains separate
`windows_render_verified`, combined/signal/input/close results and helper
diagnostics; `hardware_playback_tested` remains false. Raw captured PCM is under
`session/wasapi-capture/wasapi-output.raw`. There must be no SDL disk result in a
Windows-render session. Unsupported platform/device/API activation is a reported
failure, never a passing skip or fallback to system-wide capture.

The opt-in matrix checks two real Windows-render successes, actual silent/swapped
guest output rejection, input-abort cleanup and the complete earlier 11-case disk
matrix across six fixtures. It requires parent-environment isolation and both
engine/helper cleanup. The [filtered local evidence](../research/results/2026-10-18-windows-audio.json)
records source/input/output/audit hashes, signal windows, render/packet diagnostics,
images, pad records and expected outcomes. Raw data remains local under
`build/windows-audio/acceptance-001`. Hosted results are separate in the PR.

The sixteenth suite, `windows-render-capture-contract`, has three portable
policy/environment/CLI tests and two Windows native helper argument/foreign-
process rejection tests. The Windows tests deliberately reject requests before
opening audio, so CI needs no render device. Linux explicitly skips those two
native tests. Host tests and helper source compilation do not establish guest
audio; the opt-in local matrix supplies that evidence.

## Limits and release holds

The tested host is Windows 11 build 26220. Windows 10 render compatibility,
acoustic output, endpoint/device switching, endpoint enhancements, spatial audio,
exclusive mode, Bluetooth, microphone input, physical controllers, latency,
AV synchronization and commercial gameplay remain unverified. Packet counts
and sample windows are diagnostics, not FPS/latency or full-stream quality
certification. Endpoint mute/volume are snapshots; process capture is not a
microphone measurement of sound leaving a speaker. The existing 256-frame
concurrent limitation remains; the unchanged fixture uses 2,048-frame buffers.

The fixture/engine/patch/header pins are unchanged. The source-based launch IDs,
installer and Settings scope are unchanged. New source uses GPL-2.0-or-later;
no engine, SDK, fixture/game/audio binary, firmware or key is committed/uploaded.
Existing [source/relink/runtime/resource holds](release-audit.md) still block
engine redistribution. This research helper adds no engine distribution approval.
