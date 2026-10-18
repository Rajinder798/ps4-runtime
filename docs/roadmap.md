# Roadmap

## 0. Repository setup

- [x] Create a separate repository.
- [x] Document the project goal and current limitations.
- [x] Draft architecture and development milestones.

## 1. Choose the foundation

- [x] Inventory the God of War III loader, runtime, GPU integration, and title-specific assumptions.
- [x] Compare that inventory with the general infrastructure in shadPS4.
- [x] Record a foundation direction, candidate revision, reuse boundaries and inspected licenses.
- [x] Select a reproducible synthetic test executable for initial bring-up.
- [x] Adopt GPL-2.0-or-later for the project's original code and supporting files.
- [ ] Complete the dependency/license audit before upstream integration.
- [x] Identify the locked Windows FFmpeg binary/source inputs and add a [repeatable metadata audit](release-audit.md); full release/source compliance and separate FDK AAC linkage remain open.

## 2. Establish a development baseline

- [x] Add a minimal build and command-line entry point for Windows x86-64.
- [x] Add executable inspection and clear format validation errors.
- [x] Establish text/JSON diagnostics and meaningful parser/CLI tests.
- [x] Add continuous integration configuration for the implemented build and tests.

Local validation and hosted CI results are recorded separately. A workflow file
alone does not establish a passing hosted build. See [development](development.md).

## 3. Bring up executable loading

- [ ] Implement or integrate segment mapping, relocations, imports, and thread-local storage.
- [x] First map the synthetic probe, check zero-fill/protections and observe its return value of 42 through a controlled call.
- [x] Build and CLI-smoke-test the pinned upstream Windows baseline.
- [x] Select and reproducibly build actual OpenOrbis hello_world homebrew for future startup/service tests.
- [x] Review pinned startup coupling and focused component notices; select the [G2 process boundary](decisions/0002-g2-engine-boundary.md).
- [x] Implement a [bounded upstream homebrew harness](startup-research.md) with strict unresolved-import diagnostics and tested process cleanup.
- [x] Run the selected test executable with a minimal system layer: the [strict OpenOrbis startup result](startup-research.md#validation-and-limits) records guest entry, both messages, the two-second delay and bounded cleanup in the isolated research engine.
- [x] Report missing functions explicitly rather than silently accepting them; the [first local strict attempt](startup-research.md#converted-fixture-import-review) confirms three missing libkernel exports and stops before guest entry.

## 4. Reach the first playable title

- [ ] Integrate the chosen Vulkan backend and required runtime services.
- [ ] Add input, audio, save storage, and an isolated title profile.
- [ ] Document reproducible gameplay results and remaining issues.

## 5. Expand across different games

- [ ] Bring up a second title with different engine and service requirements.
- [ ] Move reusable fixes into the shared runtime.
- [ ] Track compatibility by title and version with test evidence.
- [ ] Expand coverage based on missing shared features and reproducible failures.

Support for the whole PS4 library is the project direction. No completion date or
universal playability claim is established by these milestones.
