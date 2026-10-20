# Physical USB DualSense research

Gate: G4 physical controller input through the existing pinned SDL engine and
original `live-av` fixture. This is an opt-in human-assisted hardware test,
separate from keyboard automation, host-generated test data and hosted builds.
It is not broad controller compatibility, analog verification or complete G4.

This page preserves the original PR #36 Cross-only result. The subsequent
[Circle/D-pad and analog increment](dualsense-controls.md) records the expanded
physical verification, isolated new analog fixture and retained failed attempts.

## Scoped protocol

Use a real Sony PS5 DualSense connected directly by USB. Windows discovery
records only device families/status, omitting paths, serials and Bluetooth
addresses. Inspect common remapping processes/drivers without stopping them or
changing global configuration. The observer must enumerate exactly one
nonvirtual PS5-type `054c:0ce6` gamepad and confirm SDL's wired connection state.
Multiple devices or failed recognition are explicit preflight blockers.

The test observer links the existing `SDL3-static.lib` from the pinned local
research build; it does not download dependencies or rebuild the engine. Its
library, source and executable hashes are recorded. It initializes gamepad
support only, has no window/audio stream and uses a process-local background
observation hint. It calls no synthetic input, virtual attachment, rumble,
LED or sensor-setting API. SDL itself may perform its normal device-init
protocol, and the unchanged engine performs its existing controller setup.
An independent observer is not a trace inside the engine's SDL event loop.

The human operates each control only after a recorded instruction. The test
records physical SDL button edges/state separately from strict guest Pad output
and the guest-written 24-byte records. The engine log must select its sole
controller for slot zero. Cross must pass two distinct press/release cycles,
each held for at least three seconds in both SDL and guest timestamps.
The default Cross-only plan has five states/images. Optional `--controls buttons`
adds separate Circle/four-D-pad expectations (15 states/images), but that option's
existence and host tests do not qualify those physical controls.
Every state requires the existing full-pixel, sequence-bound Vulkan oracle.
Only Cross changes the checkerboard phase; other buttons still change the
guest observation/sequence pixels, not the palette phase.

The host sends **no gameplay or diagnostic keyboard events**, controller
events, focus changes or window-close messages. To request the pinned engine's
Vulkan readback, the human physically presses laptop F12 only after the panel
confirms matching SDL/guest state and at least three stable SDL seconds. Keep the
game window focused while acting. After the final neutral capture the human
closes the window normally.
Test expectation files never enter the guest and cannot change its state.

Unexpected actions, missing readbacks, short holds, guest errors and deadlines
fail explicitly and retain all evidence. No physical action is automatically
repeated. A new explicitly labelled attempt does not erase an earlier failure.
The `--guided` local test panel waits for a real Ready click before starting any
guest or endpoint/controller observer. It then gives distinct neutral, press,
capture and release instructions without requesting focus when labels change.
It is test support, not a new product settings/frontend. The outer active-test
budget remains 540 seconds; a timeout requests owned process cleanup.
All guest execution is guarded by the existing read-only endpoint observer,
which requires Windows already muted and stops on mute/volume/device changes.
No PCM or audible-speaker qualification is performed.

## Capability limits

The unchanged guest records all button-mask changes and checks pad connection
on each read. It does not record analog axes, so stick input is not qualified
merely from SDL recognition. No fixture extension is required for this scope.
It treats a failed/disconnected pad read as `live-av: FAIL pad read/connection`;
that outcome must not be called graceful disconnect support.

Disconnect requires separate, explicit owner permission **after** normal input
verification. Use a fresh `--guided --disconnect-authorized` session, capture initial
neutral, record the permission/instruction, and only then ask the human to
unplug USB. Preserve SDL removal, Windows discovery, guest outcome and cleanup.
Do not reconnect unless separately authorized. This flag cannot itself unplug
or reconnect hardware. If the guest remains running for five seconds after SDL
removal, request human window close and report only that bounded observation,
without claiming graceful handling. An unexpected error remains failed evidence.

## Reproduction

From the existing research MSVC environment:

```powershell
python tools/build_dualsense_probe.py --engine build/upstream/windows-x64-strict/shadPS4.exe --engine-report build/upstream/strict-evidence/strict-build.json --fixture build/homebrew/live-av/live_av.oelf --engine-build build/upstream/windows-x64-strict --sdl-source build/upstream/shadps4-strict/externals/sdl3 --output build/dualsense/probe-new
build/dualsense/probe-new/dualsense-sdl-probe.exe --discover
python tests/dualsense_guest_tests.py --engine build/upstream/windows-x64-strict/shadPS4.exe --engine-report build/upstream/strict-evidence/strict-build.json --fixture build/homebrew/live-av/live_av.oelf --supervisor build/native/ps4-startup-supervisor.exe --sdl-observer build/dualsense/probe-new/dualsense-sdl-probe.exe --muted-endpoint-observer build/native/ps4-endpoint-observer.exe --guided --output build/dualsense/physical-new
```

The guided panel records consecutive `{index, instruction, monotonic}` lines in
`human-commands.jsonl` using the selected fixed plan. In non-guided mode an
assisting operator explicitly records each instruction before asking the human
to act. Progress is an append-only `progress.jsonl`; read only complete lines.
Advance only after `phase_verified`; do not manufacture a record or image.
Actual hardware completion and current-head Windows/Linux CI remain required
before any readiness claim. Original code is GPL-2.0-or-later; no engine, SDK,
fixture or third-party binary is committed. Separate release holds remain open.

## Retained attempts and test-support limitations

The local attempts remain separate under `build/dualsense/physical-00N`:

- 001: new logger timestamp-key collision before neutral qualification. A host
  regression now preserves the operator issue time separately from log time.
- 002: neutral image qualified; actual physical/guest Cross press and release
  recorded, but the pressed readback exactly matches earlier neutral sequence 0.
  Release before pressed-image qualification failed the protocol. The image is
  retained unchanged; no rendered pressed-state success is inferred. SDL/guest
  hold durations were about 3.17/3.18 seconds, compared within their own clocks.
- 003: neutral image qualified; the 540-second safety budget expired during a
  chat interruption before Cross testing. No physical button event was recorded.
  A later operator command was appended after timeout but was never consumed or
  presented as a physical Cross instruction; it is explicitly unqualified.
- 004: physical Cross reached the guest while initial neutral capture was pending;
  no neutral image qualified. The owner explicitly requested restart. Panel text
  now distinguishes neutral/F12-only from HOLD CROSS.
- 005: test-only `progress.json` replacement failed with Windows error 1175;
  no physical button event or qualified image. The original competing handle is
  unknown. Owner-death cleanup confirms an empty tree and signaled root. Test
  progress now uses append-only history and a host open-reader regression;
  production status publication is unchanged and no underlying Windows fix is
  claimed. This and every earlier error remain preserved, without retrying a
  failed publication or silently repeating a physical action.

Attempt 006 passes the Cross-only guided protocol using the unchanged engine,
fixture and supervisor. Physical SDL Cross holds are 8.0576841 and 24.1274229
seconds; the corresponding guest timestamp intervals are 8.049611 and 24.115896
seconds. Five actual 24-byte guest-written records exactly match strict guest
output, and five independently checked 640x360 Vulkan images bind every state
to its sequence. SDL reports one nonvirtual wired Sony DualSense; the engine
selects its sole gamepad for slot zero. Guest connection is checked by the
existing fixture guard, not a newly added connection field in its record format.
The human confirmed completion and closed the game: engine exit 0, no forced
termination, empty process tree and `root_exit_verified: true`.

The 3,267 endpoint samples span 102,409 ms with a 43 ms maximum gap; all retain
mute, scalar volume 1 and the same default endpoint. Polling cannot exclude
between-sample changes. Audio-block progression is not PCM or acoustic
qualification. Circle, D-pad and analog sticks remain physically unverified;
no broader-controller support is inferred from host tests or bindings.

The owner subsequently approved one separate USB-disconnect observation.
`disconnect-001` qualifies a fresh neutral guest/image, then asks the human to
unplug USB. SDL records removal and connected=false; Windows no longer lists
the Sony USB interface. Remaining paired Bluetooth entries do not establish
Bluetooth gameplay. The guest reports `live-av: FAIL pad read/connection`.
The unchanged strict session monitor rejects that output and requests cleanup:
engine exit 125, forced termination, empty tree and verified root exit. The
observation test passes because it records this specific rejection/containment;
the guest session itself fails. Graceful disconnect, hotplug recovery and
reconnect support are **not** established. Reconnect was neither authorized
nor attempted. All 703 endpoint samples remain muted and unchanged over
22,147 ms (maximum gap 54 ms).

Physical acceptance is Cross-only with the default N input configuration;
physical use with the saved G preference is not separately qualified. The
neutral states establish a zero **button mask**, not measured analog-stick
neutrality. SDL observer/guest records do not contain axis values in this scope.
Separate N/G/Settings/shortcut regressions verify those existing contracts.
All 21 scoped regressions pass in the final batch: nine N/G CLI/Shell/Settings,
nine previous volume/Settings/shortcut outcomes including the 125-second
no-input launch, and three no-input-close/launcher-death/requested-stop cases.
All 21 local Windows host suites pass after the final source changes. The
earlier 73-outcome audio/guest campaign remains historical, not newly rerun.

The first new keyboard regression batch passed five cases, then timed out in
UI-inherited G through Shell; three later cases were not run in that attempt.
Its trace records focus loss followed by guest release before requested key-up,
with only one mapped action and three verified images. Forced cleanup succeeds.
One explicitly labelled follow-up matrix passes all nine cases; it neither
erases the failure nor diagnoses the earlier untraced input observations.
This branch does not change the keyboard driver, runtime, engine, fixture or
thresholds, and adds no focus restoration or key resend.

Completed normal/disconnect engine logs match all 29 warning/error patterns
from prior keyboard-only evidence, with no new pattern; existing asset/font,
Vulkan capability and stub/dummy-service diagnostics remain limitations.
The guest's expected disconnect FAIL is recorded separately. Final-head hosted
Windows/Linux CI and completed-log review are pending at evidence collection;
the PR provides their final conclusions without treating host CI as hardware
execution. Exact hashes, all failures and artifact manifests are in
[the evidence report](../research/results/2026-10-20-dualsense-usb.json).

No earlier failed attempt counts as passing. The existing audio anomaly/input
observations in issue #33 remain open. The test-only progress-file 1175 error
does not establish a production regression or a Windows root cause.
