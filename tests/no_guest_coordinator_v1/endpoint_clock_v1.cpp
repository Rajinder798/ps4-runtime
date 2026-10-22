// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
// Separate read-only clocked endpoint observer. No audio stream or setters.
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <endpointvolume.h>
#include <mmdeviceapi.h>
#include <cmath>
#include <filesystem>
#include <iomanip>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
using Tick = long long;
Tick Qpc() {
    LARGE_INTEGER n{};
    if (!QueryPerformanceCounter(&n))
        throw std::runtime_error("clock");
    return n.QuadPart;
}
Tick Frequency() {
    LARGE_INTEGER n{};
    if (!QueryPerformanceFrequency(&n))
        throw std::runtime_error("clock");
    return n.QuadPart;
}
void Check(HRESULT code) {
    if (FAILED(code))
        throw std::runtime_error("query");
}
template <class T> struct Com {
    T *value = nullptr;
    ~Com() {
        if (value)
            value->Release();
    }
    T *operator->() const { return value; }
};
struct Apartment {
    Apartment() { Check(CoInitializeEx(nullptr, COINIT_MULTITHREADED)); }
    ~Apartment() { CoUninitialize(); }
};
struct Point {
    unsigned token = 0;
    bool available = false;
    DWORD state = 0;
    bool muted = false;
    float volume = 0;
    bool same = false;
};
struct Sample {
    unsigned selected = 0;
    std::vector<Point> points;
};
struct Provider {
    virtual ~Provider() = default;
    virtual Sample Query() = 0;
};
struct Synthetic final : Provider {
    Sample Query() override { return {0, {{0, true, 1, true, 0.32F, true}}}; }
};
struct Real final : Provider {
    Apartment apartment;
    Com<IMMDeviceEnumerator> enumerator;
    struct Seen {
        std::wstring id;
        float baseline = 0;
        bool initialized = false;
    };
    std::vector<Seen> seen;
    Real() {
        Check(CoCreateInstance(__uuidof(MMDeviceEnumerator), nullptr, CLSCTX_ALL,
                               __uuidof(IMMDeviceEnumerator),
                               reinterpret_cast<void **>(&enumerator.value)));
    }
    Sample Query() override {
        Com<IMMDevice> selected;
        Check(enumerator->GetDefaultAudioEndpoint(eRender, eConsole, &selected.value));
        LPWSTR raw = nullptr;
        Check(selected->GetId(&raw));
        std::wstring id;
        try {
            id = raw;
        } catch (...) {
            CoTaskMemFree(raw);
            throw;
        }
        CoTaskMemFree(raw);
        unsigned at = 0;
        while (at < seen.size() && seen[at].id != id)
            ++at;
        if (at == seen.size()) {
            if (seen.size() == 4)
                throw std::runtime_error("identity_cap");
            seen.push_back({id, 0, false});
        }
        Sample out;
        out.selected = at;
        for (unsigned i = 0; i < seen.size(); ++i) {
            Point p;
            p.token = i;
            Com<IMMDevice> device;
            auto code = enumerator->GetDevice(seen[i].id.c_str(), &device.value);
            if (SUCCEEDED(code))
                Check(device->GetState(&p.state));
            else if (code != HRESULT_FROM_WIN32(ERROR_NOT_FOUND))
                Check(code);
            p.available = SUCCEEDED(code) && p.state == DEVICE_STATE_ACTIVE;
            if (p.available) {
                Com<IAudioEndpointVolume> volume;
                Check(device->Activate(__uuidof(IAudioEndpointVolume), CLSCTX_ALL, nullptr,
                                       reinterpret_cast<void **>(&volume.value)));
                BOOL mute = FALSE;
                Check(volume->GetMute(&mute));
                Check(volume->GetMasterVolumeLevelScalar(&p.volume));
                p.muted = mute != FALSE;
                if (!seen[i].initialized) {
                    seen[i].baseline = p.volume;
                    seen[i].initialized = true;
                }
                p.same = p.volume == seen[i].baseline;
            }
            out.points.push_back(p);
        }
        return out;
    }
};
struct Trace {
    HANDLE file = INVALID_HANDLE_VALUE;
    unsigned sequence = 0;
    std::uint64_t bytes = 0;
    bool failed = false;
    explicit Trace(const std::filesystem::path &path) {
        file = CreateFileW(path.c_str(), FILE_APPEND_DATA, FILE_SHARE_READ, nullptr, CREATE_NEW,
                           FILE_ATTRIBUTE_NORMAL, nullptr);
        if (file == INVALID_HANDLE_VALUE)
            throw std::runtime_error("storage");
    }
    ~Trace() {
        if (file != INVALID_HANDLE_VALUE)
            CloseHandle(file);
    }
    void Emit(const std::string &event, const std::string &fields = "", bool reserve = false) {
        std::string line =
            "{\"schema\":\"endpoint-clock-v1\",\"sequence\":" + std::to_string(sequence) +
            ",\"qpc\":" + std::to_string(Qpc()) + ",\"event\":\"" + event + "\"" + fields + "}\n";
        if (bytes + line.size() + (reserve ? 0 : 2048) > 8 * 1024 * 1024 ||
            sequence + (reserve ? 0 : 3) >= 12000)
            throw std::runtime_error("capacity");
        DWORD written = 0;
        if (!WriteFile(file, line.data(), static_cast<DWORD>(line.size()), &written, nullptr) ||
            written != line.size())
            throw std::runtime_error("storage");
        bytes += line.size();
        ++sequence;
    }
    void Fail() {
        if (!failed) {
            failed = true;
            Emit("first_failure", ",\"reason\":\"endpoint_guard_failure\"", true);
            if (!FlushFileBuffers(file))
                throw std::runtime_error("storage");
        }
    }
};
} // namespace
int wmain(int argc, wchar_t **argv) {
    // Validate mode, flags and fresh paths before any COM/audio initialization.
    bool host = argc == 6 && std::wstring_view(argv[1]) == L"--host-test-clock-v1";
    bool live = argc == 7 && std::wstring_view(argv[1]) == L"--observe-endpoint-clock-v1" &&
                std::wstring_view(argv[6]) == L"--endpoint-monitoring-authorized";
    if (!host && !live)
        return 2;
    std::unique_ptr<Trace> trace;
    unsigned samples = 0;
    try {
        std::wstring number(argv[5]);
        if (number.empty() || number.find_first_not_of(L"0123456789") != number.npos)
            return 2;
        unsigned duration = static_cast<unsigned>(std::stoul(number));
        if (duration < 100 || duration > 120000)
            return 2;
        auto log = std::filesystem::absolute(argv[2]).lexically_normal(),
             stop = std::filesystem::absolute(argv[3]).lexically_normal(),
             ready = std::filesystem::absolute(argv[4]).lexically_normal();
        if (log == stop || log == ready || stop == ready || std::filesystem::exists(log) ||
            std::filesystem::exists(stop) || std::filesystem::exists(ready))
            return 2;
        trace = std::make_unique<Trace>(log);
        auto frequency = Frequency();
        auto begin = Qpc();
        trace->Emit("header", ",\"origin\":\"" + std::string(host ? "host-test" : "live") +
                                  "\",\"qpc_frequency\":" + std::to_string(frequency) +
                                  ",\"process_id\":" + std::to_string(GetCurrentProcessId()));
        std::unique_ptr<Provider> provider;
        if (host)
            provider = std::make_unique<Synthetic>();
        else
            provider = std::make_unique<Real>();
        unsigned previous = 0;
        for (;;) {
            auto query_begin = Qpc();
            Sample sample;
            try {
                sample = provider->Query();
            } catch (...) {
                trace->Fail();
                throw;
            }
            auto query_end = Qpc();
            bool valid = !sample.points.empty();
            std::ostringstream fields;
            fields << std::setprecision(9);
            fields << ",\"qpc_begin\":" << query_begin << ",\"qpc_end\":" << query_end
                   << ",\"default_token\":" << sample.selected << ",\"default_changed\":"
                   << (samples && previous != sample.selected ? "true" : "false")
                   << ",\"endpoints\":[";
            for (unsigned i = 0; i < sample.points.size(); ++i) {
                auto p = sample.points[i];
                if (i)
                    fields << ',';
                fields << "{\"token\":" << p.token
                       << ",\"available\":" << (p.available ? "true" : "false")
                       << ",\"device_state\":" << p.state;
                if (p.available) {
                    fields << ",\"muted\":" << (p.muted ? "true" : "false")
                           << ",\"volume\":" << p.volume
                           << ",\"same_device_volume\":" << (p.same ? "true" : "false");
                    valid = valid && p.muted && p.same && std::isfinite(p.volume) &&
                            p.volume >= 0 && p.volume <= 1;
                } else {
                    fields << ",\"muted\":null,\"volume\":null,\"same_device_volume\":null";
                    if (i == sample.selected)
                        valid = false;
                }
                fields << '}';
            }
            fields << ']';
            trace->Emit("sample", fields.str());
            ++samples;
            previous = sample.selected;
            if (!valid) {
                trace->Fail();
                throw std::runtime_error("state");
            }
            if (samples == 1) {
                auto h = CreateFileW(ready.c_str(), GENERIC_WRITE, FILE_SHARE_READ, nullptr,
                                     CREATE_NEW, FILE_ATTRIBUTE_NORMAL, nullptr);
                if (h == INVALID_HANDLE_VALUE)
                    throw std::runtime_error("ready");
                if (!CloseHandle(h))
                    throw std::runtime_error("ready");
            }
            if (std::filesystem::exists(stop)) {
                provider.reset();
                trace->Emit("summary",
                            ",\"status\":\"passed\",\"samples\":" + std::to_string(samples) +
                                ",\"stop_requested\":true",
                            true);
                return 0;
            }
            if (Qpc() - begin >= frequency * duration / 1000) {
                trace->Fail();
                throw std::runtime_error("deadline");
            }
            Sleep(25);
        }
    } catch (...) {
        if (trace) {
            try {
                trace->Fail();
                trace->Emit("summary",
                            ",\"status\":\"failed\",\"samples\":" + std::to_string(samples) +
                                ",\"stop_requested\":false",
                            true);
            } catch (...) {
            }
        }
        return 1;
    }
}
