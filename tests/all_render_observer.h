// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once
#include "all_render_loop.h"
#include <vector>

// Included by endpoint_observer.cpp after its legacy read-only COM helpers.
namespace {
std::string EndpointUtf8(const wchar_t* value) {
    const int size = WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, value, -1, nullptr, 0, nullptr, nullptr);
    if (!size) throw AllRender::ReadFailure("identity_utf8", {}, "Win32", GetLastError());
    std::vector<char> bytes(static_cast<size_t>(size));
    if (!WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, value, -1, bytes.data(), size, nullptr, nullptr))
        throw AllRender::ReadFailure("identity_utf8", {}, "Win32", GetLastError());
    return std::string(bytes.data());
}
void EndpointCheck(HRESULT code, const char* phase, const std::string& id = {}) {
    if (FAILED(code)) throw AllRender::ReadFailure(phase, id, "HRESULT", code);
}
struct AllRenderApartment {
    AllRenderApartment() { EndpointCheck(CoInitializeEx(nullptr, COINIT_MULTITHREADED), "CoInitializeEx"); }
    ~AllRenderApartment() { CoUninitialize(); }
};
std::string EndpointId(IMMDevice* device) {
    LPWSTR id = nullptr;
    EndpointCheck(device->GetId(&id), "GetId");
    try { auto result = EndpointUtf8(id); CoTaskMemFree(id); return result; }
    catch (...) { CoTaskMemFree(id); throw; }
}
class AllRenderProvider final : public AllRender::Provider {
    IMMDeviceEnumerator* enumerator;
public:
    explicit AllRenderProvider(IMMDeviceEnumerator* e) : enumerator(e) {}
    AllRender::Snapshot Read() override {
        AllRender::Snapshot s;
        constexpr ERole roles[] = {eConsole, eMultimedia, eCommunications};
        constexpr const char* phases[] = {"GetDefaultConsole", "GetDefaultMultimedia", "GetDefaultCommunications"};
        for (size_t role = 0; role < s.defaults.size(); ++role) {
            Com<IMMDevice> current;
            EndpointCheck(enumerator->GetDefaultAudioEndpoint(eRender, roles[role], &current.value), phases[role]);
            s.defaults[role] = EndpointId(current.value);
        }
        Com<IMMDeviceCollection> collection;
        EndpointCheck(enumerator->EnumAudioEndpoints(eRender, DEVICE_STATE_ACTIVE, &collection.value), "EnumAudioEndpoints");
        UINT count = 0;
        EndpointCheck(collection->GetCount(&count), "GetCount");
        if (count > AllRender::Limit) throw AllRender::ReadFailure("endpoint_limit", {}, {}, std::nullopt);
        for (UINT i = 0; i < count; ++i) {
            Com<IMMDevice> device;
            EndpointCheck(collection->Item(i, &device.value), "Item");
            const auto id = EndpointId(device.value);
            DWORD state = 0;
            EndpointCheck(device->GetState(&state), "GetState", id);
            if (state != DEVICE_STATE_ACTIVE) {
                s.endpoints.push_back({id, false, false, 0});
                continue;
            }
            Com<IAudioEndpointVolume> volume;
            EndpointCheck(device->Activate(__uuidof(IAudioEndpointVolume), CLSCTX_ALL, nullptr,
                reinterpret_cast<void**>(&volume.value)), "ActivateEndpointVolume", id);
            BOOL muted = FALSE;
            float scalar = 0;
            EndpointCheck(volume->GetMute(&muted), "GetMute", id);
            EndpointCheck(volume->GetMasterVolumeLevelScalar(&scalar), "GetVolume", id);
            s.endpoints.push_back({id, true, muted != FALSE, scalar});
        }
        return s;
    }
};
struct AllRenderOperations {
    const std::filesystem::path& stop;
    const std::filesystem::path& ready;
    auto Now() const { return std::chrono::steady_clock::now(); }
    auto UnixNs() const {
        return std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::system_clock::now().time_since_epoch()).count();
    }
    void Ready() const {
        std::ofstream signal;
        signal.exceptions(std::ios::badbit | std::ios::failbit);
        signal.open(ready);
        signal << "all render endpoints muted\n";
        signal.flush(); signal.close();
    }
    bool Stopped() const { return std::filesystem::exists(stop); }
    void Pause() const { Sleep(25); }
};
int WatchAllRenderInitialized(std::ofstream& log, const std::filesystem::path& stop,
                   const std::filesystem::path& ready, unsigned long timeout, bool fixed_inventory = false) {
    AllRenderApartment apartment;
    Com<IMMDeviceEnumerator> enumerator;
    EndpointCheck(CoCreateInstance(__uuidof(MMDeviceEnumerator), nullptr, CLSCTX_ALL,
        __uuidof(IMMDeviceEnumerator), reinterpret_cast<void**>(&enumerator.value)), "CreateEnumerator");
    AllRenderProvider provider(enumerator.value);
    AllRenderOperations operations{stop, ready};
    if (fixed_inventory) return AllRender::Watch(provider, log, operations, timeout, AllRender::OutputLimit, true);
    return AllRender::Watch(provider, log, operations, timeout);
}
int WatchAllRender(std::ofstream& log, const std::filesystem::path& stop,
                   const std::filesystem::path& ready, unsigned long timeout, bool fixed_inventory = false) {
    try { return WatchAllRenderInitialized(log, stop, ready, timeout, fixed_inventory); }
    catch (const AllRender::ReadFailure& e) {
        const auto unix_ns = std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::system_clock::now().time_since_epoch()).count();
        std::ostringstream failure;
        failure << "{\"schema_version\":2,\"event\":\"failure\",\"elapsed_ms\":null,\"unix_ns\":" << unix_ns
            << ",\"reason\":\"query_failed\",\"phase\":" << AllRender::JsonString(e.phase) << ",\"identity\":" << AllRender::JsonString(e.identity)
            << ",\"code_domain\":" << AllRender::JsonString(e.domain) << ",\"code\":";
        if (e.code) failure << *e.code; else failure << "null";
        failure << "}\n{\"schema_version\":2,\"event\":\"summary\",\"status\":\"failed\",\"samples\":0}\n";
        AllRender::WriteBounded(log, failure.str());
        std::cerr << "All-render endpoint setup failed: " << e.phase << '\n';
        return 1;
    }
}
} // namespace
