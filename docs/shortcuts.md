# Local Windows homebrew shortcuts

Gate: G3 local integration increment. After registering the verified local engine
and fixtures, create a normal Windows `.lnk` and double-click it to run the
supported fixture without opening a library or repeating registration. This
remains a Python/source-checkout research workflow with a separate pinned
shadPS4 engine. [Persistent diagnostic preferences](settings.md) apply on each
activation without recreating links. The optional [Settings window](settings.md#optional-windows-settings-window)
is opened separately. Installer, upgrades and uninstall remain open; engine
redistribution is still blocked by the release audit.

## Build and create

Build the normal CMake targets, then use the
[one-time registration command](launch-contract.md#register-once-launch-by-name).
The Windows build now also supplies `ps4-shortcut-helper.exe`, an original small
adapter around Windows Shell Link COM interfaces. It only creates/reads shortcut
metadata, without resolving targets or launching a process.

```powershell
cmake --build build/native --config Release
python tools/ps4_launch.py --state-dir build/launch/local shortcut hello-world --directory build/shortcuts/local --helper build/native/ps4-shortcut-helper.exe --json
python tools/ps4_launch.py --state-dir build/launch/local shortcut service-roundtrip --directory build/shortcuts/local --helper build/native/ps4-shortcut-helper.exe --json
```

Visual Studio places the helper under `build/native/Release/`. The command
requires Windows x86-64, the existing registered runtime/fixture inputs and a
matching `pythonw.exe` alongside the active Python interpreter. Choose an
explicit destination directory; the tool does not automatically change the
user's Desktop, Start menu or file associations. You can select your actual
Desktop directory explicitly after local validation.

Open `PS4 Runtime - hello-world.lnk` or
`PS4 Runtime - service-roundtrip.lnk` normally in Explorer. The shortcut starts
the console-free Python entry point in a separate process. It carries the
source entry point, state directory and fixed supported ID, using Windows
argument quoting without a command shell. It does not embed engine options or
execute guest code in Explorer. The normal launch path rechecks registered
inputs, creates a fresh session and enforces strict guest evidence and cleanup.

Successful runs have no setup/success dialog. A failed launch shows a Windows
error message with the session log path when available. Results are also
retained in `state-dir/desktop-results/<UUID>.json`, in addition to normal
session evidence. Unexpected internal failures mark unobserved lifecycle fields
as null rather than asserting that guest execution did or did not occur.
Error presentation is tested with host-side dialog substitution; successful
real Shell launches are tested separately.

The existing fixtures are console/service tests with deliberate bounded
termination after observation. The empty engine window and messages in logs
are not guest graphics or gameplay. No separate frontend is opened.

## Preservation and errors

Creation validates the selected registration before writing. It builds and
reads back a temporary link, checks its target/arguments/working directory and
description, then
publishes the link atomically without overwriting a destination. The destination
filesystem must support hard links. Existing files, links and concurrent
creation are rejected as `shortcut_exists` (exit 3); they are never replaced.
Missing `pythonw.exe` is `shortcut_prerequisite_failed` (exit 4); backend/storage
failure is `shortcut_failed` (exit 6). Unsupported hosts retain exit 4. The
existing launch/registration contracts are unchanged; `--json` creation returns
one schema-1 object with `operation: shortcut`, `status: created`, `title`,
`shortcut` and `engine_launch_attempted: false`.

Remove a shortcut using ordinary Windows file deletion when desired. This
removes only the link; registration, source, engine, fixtures and logs remain.
Automatic shortcut upgrade/removal and installer lifecycle are not implemented.
The source checkout and Python location must stay available. Existing local
configuration trust, native guest execution and Job Object lifetime limits
remain; a shortcut does not create a security sandbox or authorize arbitrary
guest inputs. Logs remain local with no telemetry/upload.

## Reproduction and evidence

CTest `shortcut-contract` runs eight tests for silent success/error reporting,
local result retention, structured CLI failure, atomic publication and collision
protection. On Windows it also runs the actual COM helper with Unicode paths,
quotes, trailing slashes and newline-bearing metadata; those native tests are
explicitly skipped on Linux. These tests do not execute a PS4 guest.

For real Windows Shell activation, build/register the fixtures as above and run:

```powershell
python tests/shortcut_guest_tests.py --engine build/upstream/windows-x64-strict/shadPS4.exe --engine-report build/upstream/strict-evidence/strict-build.json --supervisor build/native/ps4-startup-supervisor.exe --hello-world build/homebrew/hello-world/hello_world.oelf --service-roundtrip build/homebrew/service-roundtrip/service_roundtrip.oelf --helper build/native/ps4-shortcut-helper.exe --output build/shortcuts/acceptance-001
```

Use a new output. This creates links in a test directory containing Unicode and
spaces, verifies overwrite refusal, and invokes each link twice through Windows
Shell's normal `open` verb. It requires successful desktop-process exit, unique
session/results, actual strict guest behavior and confirmed cleanup. Registration
must remain unchanged. It writes `summary.json` after every case passes.
The test does not install links on the user's Desktop or Start menu.

The [filtered local record](../research/results/2026-10-18-shortcuts.json)
contains source/fixture/engine/host identifiers and actual results. Full logs,
links and desktop/session responses remain under the local acceptance output.
Hosted Windows/Linux results are reported separately in the PR; no hosted
policy result is treated as guest execution. The new code is original
GPL-2.0-or-later and uses Windows system COM APIs without a new third-party
library. No engine/SDK/homebrew binaries, games, firmware or keys are committed
or uploaded. Existing [release holds](release-audit.md) remain open.
