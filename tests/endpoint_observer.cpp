// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
// Test-only read-only polling. Never opens an audio stream or calls a setter.
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <endpointvolume.h>
#include <mmdeviceapi.h>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <string>

namespace {
void Check(HRESULT result) {
    if (FAILED(result)) throw std::runtime_error("Endpoint observation failed");
}
template<class T> struct Com {
    T* value = nullptr;
    ~Com() { if (value) value->Release(); }
    T* operator->() const { return value; }
    Com() = default;
    Com(const Com&) = delete;
    Com& operator=(const Com&) = delete;
};
struct Apartment {
    Apartment() { Check(CoInitializeEx(nullptr, COINIT_MULTITHREADED)); }
    ~Apartment() { CoUninitialize(); }
};
struct State {
    std::wstring id;
    BOOL muted = FALSE;
    float volume = 0;
};
State Read(IMMDeviceEnumerator* enumerator) {
    Com<IMMDevice> device;
    Check(enumerator->GetDefaultAudioEndpoint(eRender, eConsole, &device.value));
    DWORD active = 0;
    Check(device->GetState(&active));
    if (active != DEVICE_STATE_ACTIVE) throw std::runtime_error("Default render endpoint inactive");
    LPWSTR id = nullptr;
    Check(device->GetId(&id));
    State result;
    try { result.id = id; } catch (...) { CoTaskMemFree(id); throw; }
    CoTaskMemFree(id);
    Com<IAudioEndpointVolume> volume;
    Check(device->Activate(__uuidof(IAudioEndpointVolume), CLSCTX_ALL, nullptr,
                          reinterpret_cast<void**>(&volume.value)));
    Check(volume->GetMute(&result.muted));
    Check(volume->GetMasterVolumeLevelScalar(&result.volume));
    return result;
}
}

int wmain(int argc, wchar_t** argv) {
    try {
        if (argc != 6 || std::wstring(argv[1]) != L"--watch")
            throw std::runtime_error("Usage: --watch report.jsonl stop.request ready.txt timeout-ms");
        const std::wstring number(argv[5]);
        if (number.empty() || number.find_first_not_of(L"0123456789") != std::wstring::npos)
            throw std::runtime_error("Invalid bounded timeout");
        const auto timeout = std::stoul(number);
        if (timeout < 100 || timeout > 600000) throw std::runtime_error("Timeout outside 100..600000 ms");
        const std::filesystem::path report(argv[2]), stop(argv[3]), ready(argv[4]);
        if (report == stop || report == ready || stop == ready ||
            std::filesystem::exists(report) || std::filesystem::exists(stop) || std::filesystem::exists(ready))
            throw std::runtime_error("Observer requires distinct unused output paths");
        std::ofstream log(report);
        log.exceptions(std::ios::badbit | std::ios::failbit);
        Apartment apartment;
        Com<IMMDeviceEnumerator> enumerator;
        Check(CoCreateInstance(__uuidof(MMDeviceEnumerator), nullptr, CLSCTX_ALL,
                              __uuidof(IMMDeviceEnumerator), reinterpret_cast<void**>(&enumerator.value)));
        const State initial = Read(enumerator.value);
        if (!initial.muted) throw std::runtime_error("Windows must already be muted; no settings were changed");
        const auto began = std::chrono::steady_clock::now();
        unsigned samples = 0;
        for (;;) {
            const State state = Read(enumerator.value);
            const auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(
                std::chrono::steady_clock::now() - began).count();
            const bool unchanged = state.id == initial.id && state.muted == initial.muted && state.volume == initial.volume;
            log << std::setprecision(9) << "{\"elapsed_ms\":" << elapsed
                << ",\"muted\":" << (state.muted ? "true" : "false")
                << ",\"volume\":" << state.volume << ",\"same_endpoint\":"
                << (state.id == initial.id ? "true" : "false") << "}\n" << std::flush;
            ++samples;
            if (!unchanged) throw std::runtime_error("Observed Windows endpoint change; stopping validation");
            if (samples == 1) {
                std::ofstream signal(ready);
                signal.exceptions(std::ios::badbit | std::ios::failbit);
                signal << "muted\n";
            }
            if (std::filesystem::exists(stop)) {
                log << "{\"status\":\"passed\",\"samples\":" << samples << "}\n";
                return 0;
            }
            if (elapsed >= static_cast<long long>(timeout)) throw std::runtime_error("Observer budget expired");
            Sleep(25);
        }
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
