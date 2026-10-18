// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
// See LICENSE in the project root for the full license text.

// Research-only Windows process-filtered render capture. No endpoint/microphone
// capture or exclude-tree mode. The engine must be our sibling supervisor's child.
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <tlhelp32.h>
#include <audioclient.h>
#include <audiopolicy.h>
#include <endpointvolume.h>
#include <mmdeviceapi.h>
#include <objidl.h>
#include <atomic>
#include <bit>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
void Check(HRESULT value, const char* operation) {
    if (FAILED(value)) {
        std::ostringstream error;
        error << operation << ": HRESULT 0x" << std::hex << static_cast<unsigned long>(value);
        throw std::runtime_error(error.str());
    }
}
void WinCheck(BOOL value, const char* operation) {
    if (!value) throw std::runtime_error(std::string(operation) + ": Win32 " + std::to_string(GetLastError()));
}
struct Handle {
    HANDLE value;
    explicit Handle(HANDLE p) : value(p) {}
    ~Handle() { if (value && value != INVALID_HANDLE_VALUE) CloseHandle(value); }
    Handle(const Handle&) = delete;
    Handle& operator=(const Handle&) = delete;
};
template<class T> struct Com {
    T* value = nullptr;
    ~Com() { if (value) value->Release(); }
    T* operator->() const { return value; }
    Com() = default;
    Com(const Com&) = delete;
    Com& operator=(const Com&) = delete;
};
struct StreamRun {
    IAudioClient* client;
    ~StreamRun() { client->Stop(); }
};
struct PacketRelease {
    IAudioCaptureClient* capture;
    UINT32 frames;
    bool released = false;
    ~PacketRelease() { if (!released) capture->ReleaseBuffer(frames); }
};
DWORD Number(const wchar_t* text) {
    const std::wstring value(text);
    if (value.empty() || value.find_first_not_of(L"0123456789") != std::wstring::npos)
        throw std::runtime_error("Expected an unsigned decimal number");
    size_t parsed = 0;
    const auto number = std::stoull(value, &parsed);
    if (parsed != value.size() || number > MAXDWORD) throw std::runtime_error("Number outside DWORD range");
    return static_cast<DWORD>(number);
}
DWORD Parent(DWORD pid) {
    Handle snapshot(CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0));
    WinCheck(snapshot.value != INVALID_HANDLE_VALUE, "Process snapshot");
    PROCESSENTRY32W entry{};
    entry.dwSize = sizeof(entry);
    for (BOOL ok = Process32FirstW(snapshot.value, &entry); ok; ok = Process32NextW(snapshot.value, &entry)) {
        if (entry.th32ProcessID == pid) return entry.th32ParentProcessID;
    }
    throw std::runtime_error("Required process is absent");
}
void Owns(DWORD supervisor, DWORD root, const std::filesystem::path& engine, HANDLE process) {
    if (!supervisor || !root || Parent(GetCurrentProcessId()) != Parent(supervisor) || Parent(root) != supervisor)
        throw std::runtime_error("Capture requires our sibling supervisor's direct engine child");
    wchar_t path[32768];
    DWORD size = 32768;
    WinCheck(QueryFullProcessImageNameW(process, 0, path, &size), "Engine image path");
    if (!engine.is_absolute() || !std::filesystem::equivalent(engine, std::filesystem::path(path)))
        throw std::runtime_error("Owned engine executable path mismatch");
    if (WaitForSingleObject(process, 0) != WAIT_TIMEOUT) throw std::runtime_error("Owned engine has already exited");
}
DWORD Build() {
    using Version = LONG(WINAPI*)(OSVERSIONINFOW*);
    const auto function = std::bit_cast<Version>(GetProcAddress(GetModuleHandleW(L"ntdll.dll"), "RtlGetVersion"));
    if (!function) throw std::runtime_error("RtlGetVersion unavailable");
    OSVERSIONINFOW info{};
    info.dwOSVersionInfoSize = sizeof(info);
    if (function(&info) != 0) throw std::runtime_error("Cannot identify Windows build");
    return info.dwBuildNumber;
}
struct Endpoint {
    Com<IMMDeviceEnumerator> enumerator;
    Com<IMMDevice> device;
    BOOL muted = FALSE;
    float volume = 0;
    Endpoint() {
        Check(CoCreateInstance(__uuidof(MMDeviceEnumerator), nullptr, CLSCTX_ALL,
              __uuidof(IMMDeviceEnumerator), reinterpret_cast<void**>(&enumerator.value)), "Device enumerator");
        Check(enumerator->GetDefaultAudioEndpoint(eRender, eConsole, &device.value), "Default render endpoint");
        DWORD state = 0;
        Check(device->GetState(&state), "Render endpoint state");
        if (state != DEVICE_STATE_ACTIVE) throw std::runtime_error("Default render endpoint is not active");
        Com<IAudioEndpointVolume> level;
        Check(device->Activate(__uuidof(IAudioEndpointVolume), CLSCTX_ALL, nullptr,
              reinterpret_cast<void**>(&level.value)), "Endpoint volume interface");
        Check(level->GetMute(&muted), "Endpoint mute");
        Check(level->GetMasterVolumeLevelScalar(&volume), "Endpoint volume");
    }
    bool ActiveSession(DWORD root) {
        Com<IAudioSessionManager2> manager;
        Check(device->Activate(__uuidof(IAudioSessionManager2), CLSCTX_ALL, nullptr,
              reinterpret_cast<void**>(&manager.value)), "Render session manager");
        Com<IAudioSessionEnumerator> sessions;
        Check(manager->GetSessionEnumerator(&sessions.value), "Render session enumeration");
        int count = 0;
        Check(sessions->GetCount(&count), "Render session count");
        for (int i = 0; i < count; ++i) {
            Com<IAudioSessionControl> control;
            Check(sessions->GetSession(i, &control.value), "Render session");
            Com<IAudioSessionControl2> details;
            Check(control->QueryInterface(__uuidof(IAudioSessionControl2), reinterpret_cast<void**>(&details.value)), "Session details");
            DWORD pid = 0;
            AudioSessionState state{};
            if (SUCCEEDED(details->GetProcessId(&pid)) && pid == root && SUCCEEDED(details->GetState(&state)) &&
                state == AudioSessionStateActive) return true;
        }
        return false;
    }
};
// Documented Windows ABI, represented locally because older MinGW SDKs omit the
// activation-parameter header. Only include-target-process-tree mode is allowed.
struct ProcessActivation { DWORD type = 1, target = 0, mode = 0; };
static_assert(sizeof(ProcessActivation) == 12);
class Completion final : public IActivateAudioInterfaceCompletionHandler, public IAgileObject {
    std::atomic<ULONG> references{1};
public:
    Handle event{CreateEventW(nullptr, TRUE, FALSE, nullptr)};
    Com<IAudioClient> client;
    HRESULT result = E_PENDING;
    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID iid, void** output) override {
        if (!output) return E_POINTER;
        *output = nullptr;
        if (iid == __uuidof(IUnknown) || iid == __uuidof(IActivateAudioInterfaceCompletionHandler))
            *output = static_cast<IActivateAudioInterfaceCompletionHandler*>(this);
        else if (iid == __uuidof(IAgileObject)) *output = static_cast<IAgileObject*>(this);
        else return E_NOINTERFACE;
        AddRef(); return S_OK;
    }
    ULONG STDMETHODCALLTYPE AddRef() override { return ++references; }
    ULONG STDMETHODCALLTYPE Release() override {
        const auto remaining = --references;
        if (!remaining) delete this;
        return remaining;
    }
    HRESULT STDMETHODCALLTYPE ActivateCompleted(IActivateAudioInterfaceAsyncOperation* operation) override {
        Com<IUnknown> object;
        HRESULT activated = E_FAIL;
        result = operation->GetActivateResult(&activated, &object.value);
        if (SUCCEEDED(result)) result = activated;
        if (SUCCEEDED(result)) result = object->QueryInterface(__uuidof(IAudioClient), reinterpret_cast<void**>(&client.value));
        SetEvent(event.value);
        return S_OK;
    }
};
void Capture(DWORD supervisor, DWORD root, const std::filesystem::path& engine,
             const std::filesystem::path& output, DWORD timeout) {
    Handle process(OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, FALSE, root));
    WinCheck(process.value != nullptr, "Open owned engine");
    Owns(supervisor, root, engine, process.value);
    if (!output.is_absolute() || !std::filesystem::is_directory(output) || !std::filesystem::is_empty(output) ||
        timeout < 1000 || timeout > 60000) throw std::runtime_error("New empty absolute output and 1000..60000 ms budget required");
    const DWORD build = Build();
    if (build < 20348) throw std::runtime_error("Process loopback requires Windows build 20348 or later");
    Endpoint endpoint;
    if (!endpoint.ActiveSession(root)) throw std::runtime_error("Owned engine has no active default render session");
    Com<Completion> completion;
    completion.value = new Completion;
    WinCheck(completion->event.value != nullptr, "Activation event");
    ProcessActivation parameters{1, root, 0};
    PROPVARIANT blob{};
    blob.vt = VT_BLOB;
    blob.blob.cbSize = sizeof(parameters);
    blob.blob.pBlobData = reinterpret_cast<BYTE*>(&parameters);
    Com<IActivateAudioInterfaceAsyncOperation> operation;
    Check(ActivateAudioInterfaceAsync(L"VAD\\Process_Loopback", __uuidof(IAudioClient), &blob,
          completion.value, &operation.value), "Process loopback activation");
    if (WaitForSingleObject(completion->event.value, 5000) != WAIT_OBJECT_0)
        throw std::runtime_error("Process loopback activation timed out");
    Check(completion->result, "Process loopback activation result");
    WAVEFORMATEX format{};
    format.wFormatTag = WAVE_FORMAT_IEEE_FLOAT;
    format.nChannels = 2; format.nSamplesPerSec = 48000; format.wBitsPerSample = 32;
    format.nBlockAlign = 8; format.nAvgBytesPerSec = 384000;
    auto* client = completion->client.value;
    Check(client->Initialize(AUDCLNT_SHAREMODE_SHARED, AUDCLNT_STREAMFLAGS_LOOPBACK |
          AUDCLNT_STREAMFLAGS_EVENTCALLBACK | AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM,
          0, 0, &format, nullptr), "Initialize process loopback stream");
    Handle available(CreateEventW(nullptr, FALSE, FALSE, nullptr));
    WinCheck(available.value != nullptr, "Audio event");
    Check(client->SetEventHandle(available.value), "Set audio event");
    Com<IAudioCaptureClient> capture;
    Check(client->GetService(__uuidof(IAudioCaptureClient), reinterpret_cast<void**>(&capture.value)), "Capture service");
    Handle file(CreateFileW((output / "wasapi-output.raw").c_str(), GENERIC_WRITE, FILE_SHARE_READ,
                           nullptr, CREATE_NEW, FILE_ATTRIBUTE_NORMAL, nullptr));
    WinCheck(file.value != INVALID_HANDLE_VALUE, "Create PCM output");
    Owns(supervisor, root, engine, process.value);
    Check(client->Start(), "Start process capture");
    StreamRun running{client};
    {
        std::ofstream ready(output / "ready.json");
        ready << "{\"schema_version\":1,\"root_pid\":" << root << ",\"ready\":true}\n";
        if (!ready) throw std::runtime_error("Cannot publish capture readiness");
    }
    const auto began = std::chrono::steady_clock::now();
    uint64_t frames_total = 0, packets = 0, discontinuities = 0, timestamp_errors = 0;
    bool exited = false, requested = false;
    try {
        while (true) {
            WaitForSingleObject(available.value, 20);
            UINT32 packet = 0;
            Check(capture->GetNextPacketSize(&packet), "Next capture packet");
            while (packet) {
                BYTE* data = nullptr;
                UINT32 frames = 0; DWORD flags = 0;
                Check(capture->GetBuffer(&data, &frames, &flags, nullptr, nullptr), "Capture buffer");
                PacketRelease release{capture.value, frames};
                const uint64_t bytes = uint64_t(frames) * 8;
                if ((frames_total + frames) * 8 > 16 * 1024 * 1024 || bytes > MAXDWORD)
                    throw std::runtime_error("Process PCM exceeds bounded output");
                std::vector<BYTE> silence;
                if (flags & AUDCLNT_BUFFERFLAGS_SILENT) { silence.resize(static_cast<size_t>(bytes)); data = silence.data(); }
                DWORD written = 0;
                const BOOL copied = WriteFile(file.value, data, static_cast<DWORD>(bytes), &written, nullptr);
                Check(capture->ReleaseBuffer(frames), "Release capture buffer");
                release.released = true;
                WinCheck(copied && written == bytes, "Write captured PCM");
                frames_total += frames; ++packets;
                if (flags & AUDCLNT_BUFFERFLAGS_DATA_DISCONTINUITY) ++discontinuities;
                if (flags & AUDCLNT_BUFFERFLAGS_TIMESTAMP_ERROR) ++timestamp_errors;
                Check(capture->GetNextPacketSize(&packet), "Next capture packet");
            }
            exited = WaitForSingleObject(process.value, 0) == WAIT_OBJECT_0;
            requested = std::filesystem::exists(output / "stop.request");
            if (exited || requested) break;
            if (std::chrono::steady_clock::now() - began > std::chrono::milliseconds(timeout))
                throw std::runtime_error("Process capture timed out");
        }
        Check(client->Stop(), "Stop process capture");
        WinCheck(FlushFileBuffers(file.value), "Flush captured PCM");
    } catch (...) { client->Stop(); throw; }
    std::ofstream report(output / "capture.json");
    report << "{\"schema_version\":1,\"status\":\"captured\",\"backend\":\"wasapi-process-loopback\","
           << "\"root_pid\":" << root << ",\"supervisor_pid\":" << supervisor
           << ",\"include_target_tree\":true,\"owned_process_verified\":true,\"default_render_active\":true,"
           << "\"engine_render_session_active\":true,\"endpoint_muted\":" << (endpoint.muted ? "true" : "false")
           << ",\"endpoint_volume\":" << endpoint.volume << ",\"windows_build\":" << build
           << ",\"sample_format\":\"F32LE\",\"sample_rate\":48000,\"channels\":2,\"frames\":" << frames_total
           << ",\"packets\":" << packets << ",\"discontinuities\":" << discontinuities
           << ",\"timestamp_errors\":" << timestamp_errors << ",\"root_exited\":" << (exited ? "true" : "false")
           << ",\"stop_requested\":" << (requested ? "true" : "false") << "}\n";
    if (!report) throw std::runtime_error("Cannot write capture report");
}
} // namespace

int wmain(int argc, wchar_t* argv[]) {
    if (argc == 2 && std::wstring(argv[1]) == L"--help") {
        std::cout << "Research process audio helper: --preflight | --capture supervisor-pid engine-pid engine-path output timeout-ms\n";
        return 0;
    }
    bool com = false;
    try {
        if (argc != 2 && argc != 7) throw std::runtime_error("Invalid capture helper arguments");
        if (argc == 7) {
            if (std::wstring(argv[1]) != L"--capture") throw std::runtime_error("Only owned process capture is supported");
            // Ownership is checked before initializing any audio API.
            const DWORD supervisor = Number(argv[2]), root = Number(argv[3]);
            Handle process(OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, FALSE, root));
            WinCheck(process.value != nullptr, "Open owned engine");
            Owns(supervisor, root, argv[4], process.value);
        } else if (std::wstring(argv[1]) != L"--preflight") throw std::runtime_error("Invalid capture helper arguments");
        Check(CoInitializeEx(nullptr, COINIT_MULTITHREADED), "Initialize COM"); com = true;
        if (argc == 2) {
            const DWORD build = Build();
            if (build < 20348) throw std::runtime_error("Process loopback requires Windows build 20348 or later");
            Endpoint endpoint;
            std::cout << "{\"schema_version\":1,\"status\":\"available\",\"windows_build\":" << build
                      << ",\"default_render_active\":true,\"endpoint_muted\":" << (endpoint.muted ? "true" : "false")
                      << ",\"endpoint_volume\":" << endpoint.volume << "}\n";
        } else Capture(Number(argv[2]), Number(argv[3]), argv[4], argv[5], Number(argv[6]));
        CoUninitialize(); return 0;
    } catch (const std::exception& error) {
        if (com) CoUninitialize();
        std::cerr << "process-audio-capture: " << error.what() << '\n';
        return 1;
    }
}
