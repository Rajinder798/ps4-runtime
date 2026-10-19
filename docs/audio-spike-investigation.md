# PR #32 intermittent Windows audio investigation

Gate: G3 launch regression investigation against the existing G4 AudioOut fixture.
Acceptance requires matched actual guest PCM, unchanged strict amplitude limits,
normal close/containment, all 19 host suites, nine registered live scenarios and
64 prior expected guest outcomes. Passing later runs does not establish a repair.
No production fix is justified without locating a defect.

## Preserved failure

The original `build/live-launch/volume-settings-001` directory is retained without
modification. A manifest records every file's SHA-256, length and last-write UTC.
The failed session is `960dc39373784706954d7a4b82588526`, the restored-full Shell
launch immediately after title mute in the legacy saved-volume sequence.

The full-volume PCM has 366,240 stereo frames at 48 kHz. Expected amplitude is
2000/32768 = 0.06103515625; observed peak is 0.1220703125. Exactly 1,600 frames
exceed the unchanged 5% cap. First/last offending frame indices are 170432 and
172383 (zero based), spanning 1,952 frames, 40.667 ms. The overshoot begins
3.550667 seconds into the capture. This is capture-relative time; no original
packet QPC timestamps exist to align it exactly with guest/API calls.

The surrounding waveform is more specific than a uniform gain jump:

- At frame 170400 both channels change from ordinary amplitude to zero.
- Left stays zero for 480 frames. Right alternates zero and +/-2A during that
  interval, with 16-frame nonzero and 32-frame zero spans.
- After 64 frames at ordinary amplitude, both channels run at +/-2A for 1,440
  frames, then return to ordinary amplitude at frame 172384.

Cancellation plus doubled values is consistent with overlapping contributions,
but that is a hypothesis, not evidence identifying a mixer or a duplicated
buffer. A single stationary pair of phase-shifted square waves does not fit the
whole anomalous region. Merely repeating PCM samples would preserve their peak;
it would require addition or altered values to explain this doubled peak.

The engine config was correctly Debug/100%, initial config SHA-256
`62703557ab204e86b5a58d3e6274bab2cb9a16c477dceee2c5a9ce9e42a1d5a2`.
Guest phases, input, three checked images, worker join and normal engine close
succeeded. The supervisor reported zero exit, no forced termination and an
independently empty job. Capture exited zero with 763 packets, no reported
discontinuity/timestamp flags, and confirmed target ownership/render activity.
Those facts do not prove the returned samples were correct. The strict volume
oracle correctly rejected them. The subsequent test timeout was the desktop
failure dialog waiting for acknowledgement, not a guest shutdown failure.

## Boundary review

| Candidate | Observed code/evidence | Remaining uncertainty |
| --- | --- | --- |
| Guest / AudioOut buffers | One worker generates bounded +/-2000 S16 samples. `sceAudioOutOutput` copies under the port mutex; the output thread consumes and clears `output_ready` under that same mutex. Null output drains rather than enqueues a second buffer. | No original pre-conversion guest PCM trace exists. Static review cannot exclude an intermittent engine/memory defect. |
| shadPS4 conversion / SDL mix | Stereo SIMD conversion multiplies by 1/32768 without summing channels. The log shows one opened port, initial gain 1.000, no gain update, queue clear or device reopen. SDL queues copied input under a stream lock and clears its normal mix buffer before summing bound streams. | No original SDL stream list, per-submit bytes or final render buffer was recorded. Actual overlap/mixing cannot be assigned to a particular stage. |
| SDL / WASAPI playback | Pinned SDL obtains an endpoint buffer, fills/converts it, then releases it; short reads are silenced. | No original endpoint buffer/timing trace. Windows audio processing and driver behavior remain unlocalized. |
| Process loopback | Native helper appends each returned packet once before releasing it; it does no PCM addition, gain or resampling itself. The silent flag supplies zeros. Python decodes/rejects, never edits the file. | Original `GetBuffer` calls passed null device/QPC position outputs. Counts and absent error flags cannot exclude bad transport samples or establish packet overlap. |
| Settings / session state | Fresh config and actual engine log agree on 100%/gain 1.000. Endpoint was unmuted with recorded volume 0.540101. The settings store is snapshotted before launch. | Original application-session gain and complete endpoint processing state were not logged; no device setting was changed to force a result. A simple uniform gain jump alone does not explain cancellation. |
| Race / duplicated audio | The waveform motivates an overlap hypothesis; the reviewed guest-to-port and SDL queue paths have locking/copying. | Neither a specific race nor the responsible buffer has been demonstrated. |
| Pre-existing intermittent issue | Legacy runner, oracle, capture Python/native helper, desktop entry, supervisor and fixture sources are identical on baseline and PR #32. The same engine/helper binaries are used. | Source identity and clean control runs do not establish whether the original event predates this PR. |

Review uses local pinned SDL `d5af35e3fbb5bb6555ed00e69740d52af2a4e877`,
not a newer backend. Microsoft documents the optional frame/QPC outputs and
packet flags in [GetBuffer](https://learn.microsoft.com/en-us/windows/win32/api/audioclient/nf-audioclient-iaudiocaptureclient-getbuffer);
the [official process-loopback sample](https://github.com/microsoft/Windows-classic-samples/blob/main/Samples/ApplicationLoopback/cpp/LoopbackCapture.cpp)
uses the same loopback/event/autoconvert setup. Neither reference diagnoses this
capture. Optional position outputs cannot be reconstructed retrospectively.

## Matched repeat method

`tests/audio_spike_guest_tests.py` uses 20 pairs, alternating which version goes
first. Baseline is the archived Git source at
`d7b2b043c1d0e99f949f4c6045f0e78f3ccd2244`; PR runtime source is
`f34f460ff326e3c58b2522271b767efe0b544261`. Each run creates fresh registration,
saved title Debug/100%, and a diagnostic `.lnk`. Actual Windows Shell starts
matching `pythonw.exe`, imports the selected tree's unchanged desktop entry and
runs its normal launcher/capture path. The test entry replaces only random input
selection: audio `[2,1,0,3]`, palette `[3,2,4,6]`, matching the retained failure.
It does not intercept PCM, alter the fixture or add a production retry.

These diagnostic links target the test entry to fix inputs. Separate unchanged
production links are exercised by both legacy sequences and the live matrix.
The earlier four-plus-four CLI comparison fixed audio, but its attempted palette
hook targeted an unused sampling path; it must not be described as matching the
palette. The new driver fixes the actual `secrets.choice` path and asserts both
inputs and the resulting config hash in retained evidence.

Endpoint snapshots changed during the first campaign: baseline iteration 1
reported 0.540101, while the other 39 captures reported 1.0; all were unmuted.
The owner subsequently confirmed manually changing Windows volume from 54% to
100% between that first pair and confirmed no device switch. The investigation
does not change system volume or devices. The first pair is retained but excluded
from the fully matched-pair count. A separately recorded additional pair at the
owner's unchanged 100% setting supplies 20 fully matched pairs (21 attempted runs
per version in total). All samples are evaluated against the same absolute guest
amplitude without fitting to endpoint volume.

The original failure launched at `2026-10-19T15:08:28.058264+00:00`. The first new
baseline run started at `15:48:13.200440+00:00` and the first PR run at
`15:48:26.540470+00:00`. That later manual change cannot directly cause the earlier
captured spike. The first pair had identical expected PCM peaks at both endpoint
levels, consistent with process-loopback being upstream of endpoint gain. That
pair is only an observation, not an endpoint-volume experiment proving all gain
paths harmless. A 1/0.540101 ratio is approximately 1.8515, rather than the exact
2A observed, and a constant gain change alone would not explain cancellation to
zero. Original session gain and complete endpoint processing state remain
unrecorded; possible earlier changes cannot be reconstructed from these files.

Each attempted case retains UTC bounds, process transport/report, config, audit,
logs, images and raw PCM with hash, peak, offending frame bounds/count and an
independent run of the unchanged strict oracle. Failure is recorded; a modal
failure process may then be terminated using only Shell's owned process handle.
There is no replay. Original artifacts are never used as writable output.

```powershell
git archive d7b2b043c1d0e99f949f4c6045f0e78f3ccd2244 -o build/baseline.tar
# Extract into a new baseline source directory; retain its config/research files.
python tests/audio_spike_guest_tests.py --baseline build/live-launch/baseline-source --output build/audio-investigation/paired-shell-new --runs 20 --engine build/upstream/windows-x64-strict/shadPS4.exe --engine-report build/upstream/strict-evidence/strict-build.json --supervisor build/native/ps4-startup-supervisor.exe --fixture build/homebrew/interactive-av/interactive_av.oelf --capture-helper build/native/ps4-process-audio-capture.exe --helper build/native/ps4-shortcut-helper.exe
```

The new host-only guard `test_brief_doubling_rejects_even_with_sustained_correct_tone`
checks that a 1,600-frame transient is rejected even when sustained tone windows
still match. Its generated input is an oracle test, not guest evidence, a root
cause reproduction or an audio repair. Production audio code, thresholds,
capture bytes, engine/fixture/helper binaries and schemas are unchanged.

## Results and decision

Investigation and regression runs are in progress. Final counts, input hashes,
commands, artifacts, CI log review and verdict will be recorded in the linked
machine-readable investigation result before owner review.

Even a clean bounded campaign cannot prove an intermittent fault eliminated.
If the source remains unknown, the missing decisive evidence is a recurrence
with synchronized pre-SDL and endpoint/loopback packet data, including positions,
timestamps, stream identity and session gain. Instrumentation must remain bounded,
preserve actual PCM and ownership, and be compared against the original engine;
it must not become a retry or a relaxed oracle.

No engine or third-party binaries/media are distributed. Existing GPL source,
dependency and relinking release holds remain open. This investigation makes no
claims about acoustic output, Windows 10, physical controllers, installed G3,
complete G4, commercial games or a standalone execution engine.
