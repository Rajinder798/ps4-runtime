// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once
#include <chrono>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <stdexcept>
#include <string>
#include <string_view>
#ifdef _WIN32
#include <windows.h>
#else
#include <unistd.h>
#endif

namespace arrival_v1 {
inline std::int64_t Ticks() {
#ifdef _WIN32
    LARGE_INTEGER q{};
    if (!QueryPerformanceCounter(&q)) throw std::runtime_error("QPC unavailable");
    return q.QuadPart;
#else
    return std::chrono::steady_clock::now().time_since_epoch().count();
#endif
}
inline std::int64_t Frequency() {
#ifdef _WIN32
    LARGE_INTEGER q{};
    if (!QueryPerformanceFrequency(&q)) throw std::runtime_error("QPC frequency unavailable");
    return q.QuadPart;
#else
    return std::chrono::steady_clock::period::den / std::chrono::steady_clock::period::num;
#endif
}
inline unsigned ProcessId() {
#ifdef _WIN32
    return GetCurrentProcessId();
#else
    return static_cast<unsigned>(getpid());
#endif
}
inline bool RawType(unsigned type) {return type==0x605 || type==0x606 || (type>=0x653 && type<=0x655);}
inline std::string RawAssessment(unsigned type,unsigned id,unsigned original,bool removed,unsigned opens) {
    if (!RawType(type)) throw std::runtime_error("Unknown raw SDL device event");
    if(type==0x653)return (!removed && opens==1 && id==original)?"initial_announcement":
        ((removed && opens==1)?"enumeration_required":"unexpected_addition");
    if(type==0x654)return (!removed && opens==1 && id==original)?"selected_removal":"unexpected_removal";
    return type==0x655?"remap_rejected":"joystick_only";
}
inline std::string Quote(std::string_view text) {
    std::string result="\"";
    for (unsigned char ch : text) {
        if (ch=='"' || ch=='\\') result+='\\';
        if (ch<32 || ch>126) throw std::runtime_error("Non-public diagnostic string");
        result+=static_cast<char>(ch);
    }
    return result+'"';
}
// No name, serial, GUID, path, MAC or arbitrary SDL error text is serialized.
inline bool IntendedPath(std::wstring_view path) {
    if (path.empty() || path.size()>1023) throw std::runtime_error("Invalid interface payload length");
    std::wstring upper(path);
    for (auto& ch:upper) if (ch>=L'a' && ch<=L'z') ch-=32;
    const auto at=upper.find(L"VID_054C&PID_0CE6");
    return (upper.starts_with(L"\\\\?\\USB#") || upper.starts_with(L"\\\\?\\HID#")) && at!=std::wstring::npos &&
        at>0 && upper[at-1]==L'#' && at+17<upper.size() &&
        (upper[at+17]==L'#' || upper[at+17]==L'&');
}
inline std::string Candidate(int count,unsigned vendor,unsigned product,int type,bool virt,
                             unsigned id,unsigned previous) {
    if (count!=1) return "device_count";
    if (virt) return "virtual_device";
    if (vendor!=1356 || product!=3302 || type!=6) return "wrong_device";
    if (!id || (previous && id==previous)) return "stale_instance";
    return "candidate"; // Wired transport is checked only after an actual open.
}
class Trace {
#ifdef _WIN32
    HANDLE file=INVALID_HANDLE_VALUE;
#else
    std::ofstream file;
#endif
    std::size_t bytes=0,sequence=0;
    const std::size_t max_bytes,max_records;
    bool failed=false,finished=false;
    void Write(std::string_view event,const std::string& fields,bool reserved) {
        if (finished) throw std::runtime_error("Diagnostic stream already finalized");
        const std::string row="{\"schema\":\"arrival-v1\",\"sequence\":"+std::to_string(sequence)+
            ",\"qpc\":"+std::to_string(Ticks())+",\"event\":"+Quote(event)+fields+"}\n";
        if (bytes+row.size()>(reserved?max_bytes:max_bytes-1024) ||
            sequence>=(reserved?max_records:max_records-3)) {
            throw std::runtime_error("Diagnostic storage exhausted");
        }
#ifdef _WIN32
        DWORD written=0;
        if (!WriteFile(file,row.data(),static_cast<DWORD>(row.size()),&written,nullptr) || written!=row.size())
            throw std::runtime_error("Diagnostic append I/O failed");
#else
        file<<row<<std::flush;
#endif
        bytes+=row.size();++sequence;
    }
public:
    Trace(const Trace&)=delete;
    Trace& operator=(const Trace&)=delete;
    explicit Trace(const std::filesystem::path& path,bool host_test=false,
                   std::size_t limit=8*1024*1024,std::size_t records=20000):max_bytes(limit),max_records(records) {
        if (limit<2048 || records<8 || std::filesystem::exists(path))
            throw std::runtime_error("Fresh bounded diagnostic output required");
#ifdef _WIN32
        file=CreateFileW(path.c_str(),FILE_APPEND_DATA,FILE_SHARE_READ,nullptr,CREATE_NEW,FILE_ATTRIBUTE_NORMAL,nullptr);
        if (file==INVALID_HANDLE_VALUE) throw std::runtime_error("Fresh diagnostic file creation failed");
#else
        file.exceptions(std::ios::failbit|std::ios::badbit);file.open(path,std::ios::out|std::ios::app);
#endif
        try {
            Write("header",",\"origin\":"+Quote(host_test?"host-test":"live")+",\"process_id\":"+std::to_string(ProcessId())+
                ",\"qpc_frequency\":"+std::to_string(Frequency())+",\"max_bytes\":"+
                std::to_string(limit)+",\"max_records\":"+std::to_string(records),false);
        } catch (...) {
#ifdef _WIN32
            CloseHandle(file);file=INVALID_HANDLE_VALUE;
#endif
            throw;
        }
    }
    ~Trace() {
#ifdef _WIN32
        if(file!=INVALID_HANDLE_VALUE) CloseHandle(file);
#endif
    }
    void Emit(std::string_view event,const std::string& fields="") {Write(event,fields,false);}
    void Fail(std::string_view reason) {
        if (failed) return;
        failed=true;Write("first_failure",",\"reason\":"+Quote(reason),true);
    }
    bool Failed() const {return failed;}
    void Finish(bool cleanup_ok) {
        if (!cleanup_ok) Fail("cleanup_failed");
        Write("cleanup",std::string(",\"ok\":")+(cleanup_ok?"true":"false"),true);
        Write("summary",",\"status\":"+Quote(failed?"failed":"passed")+
              ",\"records\":"+std::to_string(sequence+1),true);
        finished=true;
    }
};
} // namespace arrival_v1
