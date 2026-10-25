// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once
#include "all_render_guard.h"
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
std::string JsonString(const std::string& value) {
    std::string text = "\"";
    constexpr char hex[] = "0123456789abcdef";
    for (const unsigned char ch : value) {
        if (ch == '\\' || ch == '"') { text += '\\'; text += static_cast<char>(ch); }
        else if (ch < 32) { text += "\\u00"; text += hex[ch >> 4]; text += hex[ch & 15]; }
        else text += static_cast<char>(ch);
    }
    return text + '"';
}
int WatchAllRenderInitialized(std::ofstream& log, const std::filesystem::path& stop,
                   const std::filesystem::path& ready, unsigned long timeout) {
    AllRenderApartment apartment;
    Com<IMMDeviceEnumerator> enumerator;
    EndpointCheck(CoCreateInstance(__uuidof(MMDeviceEnumerator), nullptr, CLSCTX_ALL,
        __uuidof(IMMDeviceEnumerator), reinterpret_cast<void**>(&enumerator.value)), "CreateEnumerator");
    AllRenderProvider provider(enumerator.value);
    AllRender::Guard guard;
    const auto began = std::chrono::steady_clock::now();
    unsigned samples = 0;
    size_t published = 0;
    for (;;) {
        const auto observed = guard.Poll(provider);
        const auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - began).count();
        if (!observed.ok) {
            const auto unix_ns = std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::system_clock::now().time_since_epoch()).count();
            log << "{\"schema_version\":2,\"event\":\"failure\",\"elapsed_ms\":" << elapsed
                << ",\"unix_ns\":" << unix_ns << ",\"reason\":" << JsonString(observed.reason)
                << ",\"phase\":" << JsonString(observed.phase) << ",\"identity\":" << JsonString(observed.identity)
                << ",\"code_domain\":" << JsonString(observed.domain) << ",\"code\":";
            if (observed.code) log << *observed.code; else log << "null";
            log << "}\n{\"schema_version\":2,\"event\":\"summary\",\"status\":\"failed\",\"samples\":" << samples << "}\n" << std::flush;
            std::cerr << "All-render mute guard failed: " << observed.reason << " (" << observed.phase << ")\n";
            return 1;
        }
        const auto& known = guard.Identities();
        while (published < known.size()) {
            log << "{\"schema_version\":2,\"event\":\"identity\",\"token\":" << published
                << ",\"identity\":" << JsonString(known[published].id) << "}\n";
            ++published;
        }
        log << std::setprecision(9) << "{\"schema_version\":2,\"event\":\"sample\",\"elapsed_ms\":" << elapsed
            << ",\"default_tokens\":[" << guard.Token(observed.snapshot.defaults[0]) << ','
            << guard.Token(observed.snapshot.defaults[1]) << ',' << guard.Token(observed.snapshot.defaults[2])
            << "],\"endpoints\":[";
        bool comma = false;
        for (const auto& e : observed.snapshot.endpoints) {
            if (comma) log << ',';
            comma = true;
            log << "{\"token\":" << guard.Token(e.id) << ",\"active\":true,\"muted\":true,\"volume\":" << e.volume << '}';
        }
        log << "]}\n" << std::flush;
        ++samples;
        if (samples == 1) {
            std::ofstream signal(ready); signal.exceptions(std::ios::badbit | std::ios::failbit); signal << "all render endpoints muted\n";
        }
        if (std::filesystem::exists(stop)) {
            log << "{\"schema_version\":2,\"event\":\"summary\",\"status\":\"passed\",\"samples\":" << samples << "}\n";
            return 0;
        }
        if (elapsed >= static_cast<long long>(timeout)) throw std::runtime_error("All-render observer budget expired");
        if (log.tellp() > 32 * 1024 * 1024) throw std::runtime_error("All-render observer output exceeds 32 MiB");
        Sleep(25);
    }
}
int WatchAllRender(std::ofstream& log, const std::filesystem::path& stop,
                   const std::filesystem::path& ready, unsigned long timeout) {
    try { return WatchAllRenderInitialized(log, stop, ready, timeout); }
    catch (const AllRender::ReadFailure& e) {
        const auto unix_ns = std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::system_clock::now().time_since_epoch()).count();
        log << "{\"schema_version\":2,\"event\":\"failure\",\"elapsed_ms\":null,\"unix_ns\":" << unix_ns
            << ",\"reason\":\"query_failed\",\"phase\":" << JsonString(e.phase) << ",\"identity\":" << JsonString(e.identity)
            << ",\"code_domain\":" << JsonString(e.domain) << ",\"code\":";
        if (e.code) log << *e.code; else log << "null";
        log << "}\n{\"schema_version\":2,\"event\":\"summary\",\"status\":\"failed\",\"samples\":0}\n" << std::flush;
        std::cerr << "All-render endpoint setup failed: " << e.phase << '\n';
        return 1;
    }
}
} // namespace
