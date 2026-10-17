# Roadmap

## 0. Repository setup

- [x] Create a separate repository.
- [x] Document the project goal and current limitations.
- [x] Draft architecture and development milestones.

## 1. Choose the foundation

- [ ] Inventory the God of War III loader, runtime, GPU integration, and title-specific assumptions.
- [ ] Compare that inventory with the general infrastructure in shadPS4.
- [ ] Record a foundation decision, dependency versions, and applicable licenses.
- [ ] Select a reproducible homebrew or test executable for initial bring-up.

## 2. Establish a development baseline

- [ ] Add a minimal build and command-line entry point for Windows x86-64.
- [ ] Add executable inspection and clear format validation errors.
- [ ] Establish structured diagnostics and meaningful loader tests.
- [ ] Add continuous integration for the implemented build and tests.

## 3. Bring up executable loading

- [ ] Implement or integrate segment mapping, relocations, imports, and thread-local storage.
- [ ] Run the selected test executable with a minimal system layer.
- [ ] Report missing functions explicitly rather than silently accepting them.

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
