# Persistent settings for supported capabilities

Gate: G3 settings-core increment. The local launch interface now persists a
global preference and per-title overrides for a capability the pinned engine
already implements: diagnostic log level. The optional graphical Settings UI,
other settings categories and installer lifecycle remain future work. This
source/Python workflow still uses the separate research engine and does not
clear its redistribution holds.

## Supported preference and commands

`log_level` accepts `debug`, `info` or `warning`. Default is `info`. It controls
the engine's per-session diagnostic log after its logging configuration is
loaded. Debug includes more detail; Warning retains warnings/errors while
excluding Info/Debug records. Bootstrap diagnostics, structured strict audit,
Vulkan host capture and required guest behavior checks are retained independently.
This does not change graphics quality, performance, audio or input.

```powershell
python tools/ps4_launch.py --state-dir build/launch/local settings show --json
python tools/ps4_launch.py --state-dir build/launch/local settings set log_level warning --json
python tools/ps4_launch.py --state-dir build/launch/local settings set log_level debug --title hello-world --json
python tools/ps4_launch.py --state-dir build/launch/local settings show --title hello-world --json
python tools/ps4_launch.py --state-dir build/launch/local settings reset --title hello-world --json
python tools/ps4_launch.py --state-dir build/launch/local settings reset --json
python tools/ps4_launch.py --state-dir build/launch/local settings reset --all --json
```

Use the same state directory as registration/shortcuts. As before, omitting
`--state-dir` uses `PS4_RUNTIME_HOME` or the platform default. Settings commands
work without launching an engine or requiring registration, and support the
two known launch IDs. No unsupported controls or telemetry opt-in are exposed.
This preference layer adds no upload/telemetry operation; logs remain local.

The resolution order is **defaults → global → per-title override**. `show`
returns stored settings, defaults, effective values, their sources (`default`,
`global`, `title`) and `takes_effect: next_launch`. Without a title, it shows
global effective values. Reset with a title removes that title's overrides and
inherits global values. Reset without a title clears global overrides while
preserving title overrides. `--all` clears both. Reset does not delete logs,
registration, shortcuts, inputs or session data.

## Persistence and launch behavior

`settings.json` schema 1 is separate from `launch-config.json` registration:

```json
{
  "schema_version": 1,
  "global": {"log_level": "warning"},
  "titles": {"hello-world": {"log_level": "debug"}}
}
```

The initial format has no prior schema to migrate. Missing files use defaults
without creating a file or prompt. Unknown/future versions, fields, titles,
invalid types/levels, duplicate keys, malformed/oversized JSON fail closed.
They are not silently discarded, downgraded or overwritten, including by reset.
Future supported migrations must be explicit and tested before accepting a new
format. To recover a damaged/unsupported file, preserve a copy and repair it or
move it aside deliberately; the runtime never performs that recovery silently.

Updates hold a nonblocking OS file lock, read the latest valid document, and
publish a fully written temporary file with atomic replacement. Concurrent
writers receive `settings_busy`; closing the handle or terminating the writer
releases the lock. `.settings.lock` is a persistent lock file, not a stale
ownership marker. Failed validation/save preserves the published preferences.
Readers see a complete old or new document. Storage failures use
`settings_write_failed` (exit 6); invalid settings and contention use exit 3.
Invalid CLI values/usage retain exit 2. JSON/text behavior matches the existing
launch interface.

Each launch takes one validated effective-settings snapshot before allocating
a session. Both launch responses and retained session results record effective
values and their sources. Corrupt preferences reject execution before an engine
starts. Changing settings affects the next launch and does not modify an active
session. Existing shortcuts read the current settings on every activation,
without recreation or extra prompts.

The launcher supplies the effective log level to the shared strict runner,
which writes only the supported `Log.filter` value (`*:debug`, `*:info` or
`*:warning`) in that session's fresh `user/config.json`. It also fixes
`Log.flush_level` to `trace` so accepted diagnostics are flushed before bounded
termination. This is an internal evidence-retention measure, not a user knob.
The engine merges this group over its defaults and saves its normal complete
config. The standalone research runner keeps its existing default behavior
when no preference is supplied. No pinned engine source/patch/header is changed.

## Reproduction and evidence

CTest `settings-contract` has eight policy/CLI tests for precedence, reset,
persistence across processes, future/invalid format preservation, failed writes,
real OS writer contention/release, immutable launch snapshots and pre-execution
rejection. These are host tests, not PS4 guest execution.

```powershell
python tests/settings_guest_tests.py --engine build/upstream/windows-x64-strict/shadPS4.exe --engine-report build/upstream/strict-evidence/strict-build.json --supervisor build/native/ps4-startup-supervisor.exe --hello-world build/homebrew/hello-world/hello_world.oelf --service-roundtrip build/homebrew/service-roundtrip/service_roundtrip.oelf --helper build/native/ps4-shortcut-helper.exe --output build/settings/acceptance-001
```

Choose a new output. This runs six real guest sessions across default, global,
per-title override and reset cases, using both direct CLI launches and existing
Windows shortcuts. It checks the engine's retained filter, actual session-log
levels, strict guest messages/timing, independent service output and tree cleanup.
Warning records must remain, so a broken filter that disables all logging cannot
pass. Registration and shortcut command properties must remain unchanged.
A future-version settings file is then rejected before execution and preserved
by a rejected reset. The filtered [local evidence record](../research/results/2026-10-18-settings.json)
contains measured log-level counts and input/source identifiers, not performance
benchmarks. Complete logs/configs/audits remain in the local acceptance output.
Hosted checks are recorded separately in the PR.

No optional graphical settings window, graphics/performance/input/audio controls,
commercial compatibility or release readiness is established. New source is
original GPL-2.0-or-later with no additional third-party dependency. No engine,
SDK/homebrew/game binaries, firmware or keys are committed or uploaded. The
[existing dependency/source/relink holds](release-audit.md) remain open.
