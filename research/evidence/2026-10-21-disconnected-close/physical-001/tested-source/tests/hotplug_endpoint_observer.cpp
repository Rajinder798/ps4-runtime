// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
// Separately approved test protocol. Read-only COM queries, no audio stream/setters.
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <endpointvolume.h>
#include <mmdeviceapi.h>
#include <chrono>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
void Check(HRESULT r) { if (FAILED(r)) throw std::runtime_error("Read-only endpoint query failed"); }
template<class T> struct Com {
    T* value=nullptr;
    ~Com(){if(value)value->Release();}
    T* operator->()const{return value;}
    Com()=default;Com(const Com&)=delete;Com& operator=(const Com&)=delete;
};
struct Apartment {
    Apartment(){Check(CoInitializeEx(nullptr,COINIT_MULTITHREADED));}
    ~Apartment(){CoUninitialize();}
};
struct Endpoint {std::wstring id;float baseline{};bool initialized{};};
std::wstring DefaultId(IMMDeviceEnumerator* enumerator) {
    Com<IMMDevice> device;
    Check(enumerator->GetDefaultAudioEndpoint(eRender,eConsole,&device.value));
    LPWSTR id=nullptr;Check(device->GetId(&id));
    std::wstring result;
    try{result=id;}catch(...){CoTaskMemFree(id);throw;}
    CoTaskMemFree(id);return result;
}
}
int wmain(int argc,wchar_t** argv) {
    try {
        if(argc!=6 || std::wstring(argv[1])!=L"--watch")throw std::runtime_error("Usage: --watch report stop ready timeout-ms");
        const std::wstring number(argv[5]);
        if(number.empty() || number.find_first_not_of(L"0123456789")!=std::wstring::npos)throw std::runtime_error("Invalid timeout");
        const auto timeout=std::stoul(number);
        if(timeout<100 || timeout>600000)throw std::runtime_error("Invalid bounded timeout");
        const std::filesystem::path report(argv[2]),stop(argv[3]),ready(argv[4]);
        if(report==stop || report==ready || stop==ready || std::filesystem::exists(report) ||
           std::filesystem::exists(stop) || std::filesystem::exists(ready))throw std::runtime_error("Distinct fresh output paths required");
        std::ofstream log(report);log.exceptions(std::ios::badbit|std::ios::failbit);
        Apartment apartment;
        Com<IMMDeviceEnumerator> enumerator;
        Check(CoCreateInstance(__uuidof(MMDeviceEnumerator),nullptr,CLSCTX_ALL,__uuidof(IMMDeviceEnumerator),
            reinterpret_cast<void**>(&enumerator.value)));
        std::vector<Endpoint> seen;
        const auto began=std::chrono::steady_clock::now();
        size_t previous=0;unsigned samples=0,changes=0;
        for(;;) {
            const auto id=DefaultId(enumerator.value);
            size_t selected=0;
            while(selected<seen.size() && seen[selected].id!=id)++selected;
            if(selected==seen.size()) {
                if(seen.size()==4)throw std::runtime_error("More than four default endpoint identities; bounded protocol stopped");
                seen.push_back(Endpoint{id,0,false});
            }
            const bool changed=samples>0 && previous!=selected;
            if(changed)++changes;
            const auto elapsed=std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now()-began).count();
            log<<std::setprecision(9)<<"{\"schema_version\":1,\"event\":\"sample\",\"elapsed_ms\":"<<elapsed
                <<",\"default_token\":"<<selected<<",\"default_changed\":"<<(changed?"true":"false")<<",\"endpoints\":[";
            bool valid=true;
            for(size_t i=0;i<seen.size();++i) {
                if(i)log<<',';
                Com<IMMDevice> device;
                const HRESULT query=enumerator->GetDevice(seen[i].id.c_str(),&device.value);
                DWORD state=0;
                if(SUCCEEDED(query))Check(device->GetState(&state));
                else if(query!=HRESULT_FROM_WIN32(ERROR_NOT_FOUND))Check(query);
                const bool available=SUCCEEDED(query) && state==DEVICE_STATE_ACTIVE;
                log<<"{\"token\":"<<i<<",\"available\":"<<(available?"true":"false")<<",\"device_state\":"<<state;
                if(available) {
                    Com<IAudioEndpointVolume> volume;
                    Check(device->Activate(__uuidof(IAudioEndpointVolume),CLSCTX_ALL,nullptr,reinterpret_cast<void**>(&volume.value)));
                    BOOL muted=FALSE;float scalar=0;
                    Check(volume->GetMute(&muted));Check(volume->GetMasterVolumeLevelScalar(&scalar));
                    if(!seen[i].initialized){seen[i].baseline=scalar;seen[i].initialized=true;}
                    const bool unchanged=scalar==seen[i].baseline;
                    log<<",\"muted\":"<<(muted?"true":"false")<<",\"volume\":"<<scalar
                        <<",\"same_device_volume\":"<<(unchanged?"true":"false");
                    valid=valid && muted && unchanged && std::isfinite(scalar) && scalar>=0 && scalar<=1;
                } else {
                    log<<",\"muted\":null,\"volume\":null,\"same_device_volume\":null";
                    if(i==selected)valid=false; // Missing active default is an explicit failure, not fabricated mute.
                }
                log<<'}';
            }
            log<<"]}\n"<<std::flush;
            ++samples;previous=selected;
            if(!valid)throw std::runtime_error("Observed unmuted endpoint, per-device volume change or unavailable default; stopped without setters/retry");
            if(samples==1){std::ofstream signal(ready);signal.exceptions(std::ios::badbit|std::ios::failbit);signal<<"muted hotplug protocol ready\n";}
            if(std::filesystem::exists(stop)) {
                log<<"{\"schema_version\":1,\"event\":\"summary\",\"status\":\"passed\",\"samples\":"<<samples
                    <<",\"default_changes\":"<<changes<<",\"endpoint_identities\":"<<seen.size()<<"}\n";
                return 0;
            }
            if(elapsed>=static_cast<long long>(timeout))throw std::runtime_error("Observer budget expired; no retry");
            Sleep(25);
        }
    }catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
}
