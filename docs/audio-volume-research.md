# Combined-homebrew audio volume research

Gate: G4 audio-control increment and prerequisite for a capability-backed G3
audio preference. This checks the pinned engine's existing volume gain using
actual combined-homebrew PCM. It adds no supported launch ID, persistent audio
preference or Settings control. The registered hello/service fixtures do not
exercise audio; those product-facing changes need functional launch acceptance.

## Contract and independent checks

The fixed `interactive-av` runner accepts optional `--volume-percent 0|50|100`.
Other profiles and fractional/out-of-range values fail before CLI output creation
or execution. Omitting the option retains the prior tone/silence contract. The
runner writes `General.volume_slider` into the fresh isolated `user/config.json`
before launching. It never changes the Windows endpoint or another application's
volume. The setting takes effect for that attempt.

At the unchanged engine pin, `src/core/emulator_settings.h` serializes the field
as `volume_slider`; `src/core/libraries/audio/sdl_audio_out.cpp` multiplies the
slider percentage by guest channel gain and calls `SDL_SetAudioStreamGain`.
The reviewed fixture emits S16 stereo square waves of +/-2000. Expected float
RMS is therefore `(2000 / 32768) * percent / 100` on each channel. This expectation
is calculated from the fixture, never fitted to a captured reference or accepted
merely because configuration/logging says so.

At 50/100 percent the original ordered silence/channel-specific tone/silence
oracle must pass. A second analysis requires four sustained windows within
**+/-5% of expected RMS** on both channels and a whole-capture peak ceiling of
105% of that amplitude. It searches beyond onset windows that may mix silence
with tones. Original frame/frequency/silence thresholds remain unchanged.
Mute requires every finite sample of the bounded 3–20 second capture to have
magnitude below 0.00001. Its report explicitly records `tone_verified: false`:
silence alone does not prove a source produced tones. The complete matrix
separately checks unmuted output and restoration.

Both SDL disk and owned-process WASAPI retain their original format/source
provenance requirements. Requested volume cannot replace active render-session,
exact ownership, helper termination, strict guest entry/zero unresolved imports,
three Vulkan images, actual neutral/Cross/release observations or normal engine
close evidence. `volume_verified` is granted only after the requested PCM check;
muted combined acceptance means requested silence, not audible tone output.
`hardware_playback_tested` remains false.

## Reproduce and acceptance

Use the [Windows audio prerequisites](windows-audio-research.md), unchanged
strict engine and six fixed fixtures. Choose new output directories.

```powershell
python tools/run_videoout_research.py --profile interactive-av --shutdown window-close --volume-percent 50 --audio-backend wasapi --capture-helper build/native/ps4-process-audio-capture.exe --engine build/upstream/windows-x64-strict/shadPS4.exe --engine-report build/upstream/strict-evidence/strict-build.json --fixture build/homebrew/interactive-av/interactive_av.oelf --supervisor build/native/ps4-startup-supervisor.exe --output build/audio-volume/single-new
python tests/audio_volume_guest_tests.py --engine build/upstream/windows-x64-strict/shadPS4.exe --engine-report build/upstream/strict-evidence/strict-build.json --supervisor build/native/ps4-startup-supervisor.exe --capture-helper build/native/ps4-process-audio-capture.exe --fixture build/homebrew/interactive-av/interactive_av.oelf --hello-world build/homebrew/hello-world/hello_world.oelf --service-roundtrip build/homebrew/service-roundtrip/service_roundtrip.oelf --videoout-pattern build/homebrew/videoout-pattern/videoout_pattern.oelf --pad-videoout build/homebrew/pad-videoout/pad_videoout.oelf --audio-pattern build/homebrew/audio-pattern/audio_pattern.oelf --output build/audio-volume/acceptance-new
```

The opt-in matrix runs full/half/mute/restored-full and silent/swapped negatives
for **both** backends: 12 actual guest attempts. Each positive capture must also
reject a different requested volume in separate host analysis. The engine's
saved configuration must retain the exact requested integer, and the parent
environment must remain unchanged. The earlier 16-outcome Windows/disk matrix
then reruns all six fixtures, including input-abort/helper cleanup: **28 expected
guest outcomes**, not supported titles or a performance benchmark.

The seventeenth CTest suite, `audio-volume-contract`, checks generated amplitude,
wrong gain/channel/silence/nonfinite/bounds rejection, mute leakage and CLI
scope/value rejection on Windows/Linux. Host tests do not establish guest runs.
Actual local results and completed hosted checks are reported separately in
this task's PR and filtered research evidence.

The [filtered local result](../research/results/2026-10-18-audio-volume.json)
records all **28 expected guest outcomes passed** and **17/17 local CTest suites
passed**. Full/half RMS was 0.06103515625/0.030517578125 on this host; both mute
captures were entirely zero. Raw evidence remains under
`build/audio-volume/acceptance-002`. It preserves source/native/fixture hashes,
commands, capture diagnostics, images/pad/config/audit/PCM hashes and the initial
onset-window false rejection from `acceptance-001`. The final matrix used a fresh
directory after sustained-window selection was corrected without widening the
amplitude bound. Hosted CI and engine rebuild evidence remain separate.

## Dependencies, risks and limits

This depends on the verified combined fixture, strict engine, Vulkan/keyboard
transport, shutdown supervisor and process capture helper. No engine/fixture/
patch/header or dependency changes are needed. A Windows render device/API
failure is a failure, never a passing disk-only fallback. Unsupported device/
driver transformations may fail the fixed amplitude bound; do not tune it from
measured data to make an unsupported host pass.

Only the three named research levels are tested. Persistent global/per-title
audio settings, live adjustment, device selection, latency, other formats,
physical controllers, acoustic output, Windows 10 render compatibility,
commercial gameplay and full G4 remain unverified. The existing 256-frame
concurrent limitation remains; this fixture uses 2,048-frame buffers. Original
source is GPL-2.0-or-later. No engine/SDK/fixture/audio binary, firmware or key
is committed/uploaded. All [release holds](release-audit.md) remain.
