// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
#include "arrival_windows_v1.h"
#include <cfgmgr32.h>
#include <algorithm>
#include <array>
#include <atomic>
#include <cwchar>
#include <map>
#include <mutex>
#include <vector>

namespace arrival_v1 {
namespace {
constexpr GUID Usb={0xa5dcbf10,0x6530,0x11d2,{0x90,0x1f,0x00,0xc0,0x4f,0xb9,0x51,0xed}};
constexpr GUID Hid={0x4d1e55b2,0xf16f,0x11cf,{0x88,0xcb,0x00,0x11,0x11,0x00,0x00,0x30}};
std::string Kind(const GUID& guid) {
    if (IsEqualGUID(guid,Usb)) return "usb";
    if (IsEqualGUID(guid,Hid)) return "hid";
    throw std::runtime_error("Unknown interface class");
}
struct Notice {std::int64_t received=0;unsigned action=0;GUID guid{};std::array<wchar_t,1024> path{};};
struct Queue {
    std::mutex mutex;
    std::array<Notice,256> notices{};
    std::size_t count=0;
    std::atomic<unsigned> failure{0};
};
DWORD CALLBACK Callback(HCMNOTIFICATION,void* opaque,CM_NOTIFY_ACTION action,
                        CM_NOTIFY_EVENT_DATA* data,DWORD bytes) noexcept {
    auto& queue=*static_cast<Queue*>(opaque);
    try {
        constexpr auto offset=offsetof(CM_NOTIFY_EVENT_DATA,u.DeviceInterface.SymbolicLink);
        if (!data || bytes<offset+sizeof(wchar_t) || bytes>offset+1024*sizeof(wchar_t) ||
            data->FilterType!=CM_NOTIFY_FILTER_TYPE_DEVICEINTERFACE ||
            (action!=CM_NOTIFY_ACTION_DEVICEINTERFACEARRIVAL && action!=CM_NOTIFY_ACTION_DEVICEINTERFACEREMOVAL))
            throw std::runtime_error("Malformed notification");
        const std::size_t available=(bytes-offset)/sizeof(wchar_t);
        const auto* path=data->u.DeviceInterface.SymbolicLink;
        std::size_t length=0;
        while (length<available && path[length]) ++length;
        if (length==available) throw std::runtime_error("Unterminated notification");
        if (!IntendedPath(std::wstring_view(path,length))) return ERROR_SUCCESS;
        const auto kind=Kind(data->u.DeviceInterface.ClassGuid);
        std::wstring prefix(path,8);
        for(auto& ch:prefix)if(ch>=L'a' && ch<=L'z')ch-=32;
        if ((kind=="usb")!=(prefix==L"\\\\?\\USB#")) throw std::runtime_error("Interface class/path conflict");
        // No I/O, enumeration, registration or device handles in the callback.
        std::lock_guard guard(queue.mutex);
        if (queue.count==queue.notices.size()) {unsigned clear=0;queue.failure.compare_exchange_strong(clear,2);return ERROR_SUCCESS;}
        auto& n=queue.notices[queue.count++];n.received=Ticks();n.action=static_cast<unsigned>(action);
        n.guid=data->u.DeviceInterface.ClassGuid;
        std::copy_n(path,length,n.path.begin());n.path[length]=0;
    } catch (...) {unsigned clear=0;queue.failure.compare_exchange_strong(clear,1);}
    return ERROR_SUCCESS; // Passive only; never veto a removal.
}
void Drain(Queue& queue,Trace& trace,std::map<std::wstring,unsigned>& tokens) {
    std::vector<Notice> pending;
    {std::lock_guard guard(queue.mutex);pending.assign(queue.notices.begin(),queue.notices.begin()+queue.count);queue.count=0;}
    if (queue.failure.load()) {
        trace.Emit("windows_callback_error",",\"code\":"+std::to_string(queue.failure.load()));
        throw std::runtime_error("Windows callback incomplete");
    }
    for (const auto& n:pending) {
        const std::wstring key(n.path.data());
        if (!tokens.contains(key) && tokens.size()==64) throw std::runtime_error("Interface identity budget exhausted");
        const auto token=tokens.try_emplace(key,static_cast<unsigned>(tokens.size()+1)).first->second;
        trace.Emit("windows_notification",",\"interface\":"+Quote(Kind(n.guid))+",\"action\":"+
            Quote(n.action==CM_NOTIFY_ACTION_DEVICEINTERFACEARRIVAL?"arrival":"removal")+
            ",\"token\":"+std::to_string(token)+",\"received_qpc\":"+std::to_string(n.received));
    }
}
} // namespace
struct WindowsArrival::Impl {
    Trace& trace;Queue queue;std::map<std::wstring,unsigned> tokens;
    std::array<HCMNOTIFICATION,2> handles{};
    std::int64_t last=0;
    bool started=false,close_called=false,close_ok=false;
    explicit Impl(Trace& t):trace(t) {}
    void Presence(GUID guid) {
        std::array<wchar_t,65536> list{};
        const auto before=Ticks();
        const auto code=CM_Get_Device_Interface_ListW(&guid,nullptr,list.data(),static_cast<ULONG>(list.size()),CM_GET_DEVICE_INTERFACE_LIST_PRESENT);
        const auto after=Ticks();
        if (code!=CR_SUCCESS) {
            trace.Emit("windows_enumeration_error",",\"interface\":"+Quote(Kind(guid))+",\"code\":"+std::to_string(code));
            throw std::runtime_error("Windows presence query failed; no retry");
        }
        std::string found="[";
        bool any=false;
        for (std::size_t at=0;at<list.size() && list[at];) {
            std::size_t end=at;while(end<list.size() && list[end]) ++end;
            if (end==list.size()) throw std::runtime_error("Unterminated interface list");
            const std::wstring key(list.data()+at,end-at);at=end+1;
            if (!IntendedPath(key)) continue;
            if (!tokens.contains(key) && tokens.size()==64) throw std::runtime_error("Interface identity budget exhausted");
            auto token=tokens.try_emplace(key,static_cast<unsigned>(tokens.size()+1)).first->second;
            if (any) found+=',';
            found+=std::to_string(token);any=true;
        }
        trace.Emit("windows_presence",",\"interface\":"+Quote(Kind(guid))+",\"tokens\":"+found+"],\"qpc_begin\":"+
                   std::to_string(before)+",\"qpc_end\":"+std::to_string(after));
    }
};
WindowsArrival::WindowsArrival(Trace& trace):state(std::make_unique<Impl>(trace)) {}
WindowsArrival::~WindowsArrival() {
    if (state && !Close() && std::any_of(state->handles.begin(),state->handles.end(),[](auto h){return h!=nullptr;}))
        static_cast<void>(state.release());
}
void WindowsArrival::Start() {
    if(state->started || state->close_called)throw std::runtime_error("Repeated notification lifecycle");
    state->started=true;
    for (unsigned i=0;i<2;++i) {
        CM_NOTIFY_FILTER filter{};filter.cbSize=sizeof(filter);filter.FilterType=CM_NOTIFY_FILTER_TYPE_DEVICEINTERFACE;
        filter.u.DeviceInterface.ClassGuid=i==0?Usb:Hid;
        const auto code=CM_Register_Notification(&filter,&state->queue,Callback,&state->handles[i]);
        state->trace.Emit("windows_registration",",\"interface\":"+Quote(i==0?"usb":"hid")+",\"code\":"+std::to_string(code));
        if (code!=CR_SUCCESS) throw std::runtime_error("Windows notification registration failed");
    }
    Poll(); // Register before presence; overlap is reported, never deduplicated into arrival.
}
void WindowsArrival::Poll() {
    Drain(state->queue,state->trace,state->tokens);
    if (Ticks()-state->last>=Frequency()) {state->Presence(Usb);state->Presence(Hid);state->last=Ticks();}
}
bool WindowsArrival::Close() {
    if(state->close_called)return state->close_ok;
    state->close_called=true;
    bool okay=true;
    for (unsigned i=0;i<state->handles.size();++i) if (auto& handle=state->handles[i];handle) {
        const auto code=CM_Unregister_Notification(handle);
        if (code==CR_SUCCESS) handle=nullptr;else okay=false;
        try {state->trace.Emit("windows_unregistration",",\"interface\":"+Quote(i==0?"usb":"hid")+",\"code\":"+std::to_string(code));}
        catch (...) {okay=false;} // Explicit failed cleanup; never retry a failed append.
    }
    // Never free callback context while failed unregistration could leave it live.
    if (okay) {try {Drain(state->queue,state->trace,state->tokens);} catch (...) {okay=false;}}
    state->close_ok=okay;return okay;
}
void WindowsCallbackHostTest(Trace& trace) {
    Queue queue;std::map<std::wstring,unsigned> tokens;
    const std::wstring fake=L"\\\\?\\USB#VID_054C&PID_0CE6#HOST_TEST_ONLY";
    std::vector<unsigned long long> storage((sizeof(CM_NOTIFY_EVENT_DATA)+fake.size()*sizeof(wchar_t)+15)/8);
    auto* data=reinterpret_cast<CM_NOTIFY_EVENT_DATA*>(storage.data());
    data->FilterType=CM_NOTIFY_FILTER_TYPE_DEVICEINTERFACE;data->u.DeviceInterface.ClassGuid=Usb;
    std::copy(fake.begin(),fake.end(),data->u.DeviceInterface.SymbolicLink);data->u.DeviceInterface.SymbolicLink[fake.size()]=0;
    const auto bytes=static_cast<DWORD>(offsetof(CM_NOTIFY_EVENT_DATA,u.DeviceInterface.SymbolicLink)+(fake.size()+1)*sizeof(wchar_t));
    Callback(nullptr,&queue,CM_NOTIFY_ACTION_DEVICEINTERFACEARRIVAL,data,bytes);Drain(queue,trace,tokens);
    Callback(nullptr,&queue,CM_NOTIFY_ACTION_DEVICEINTERFACEREMOVAL,data,bytes);Drain(queue,trace,tokens);
    Callback(nullptr,&queue,CM_NOTIFY_ACTION_DEVICEINTERFACEARRIVAL,data,1);
    if (queue.failure.load()!=1) throw std::runtime_error("Callback did not reject truncated payload");
    queue.failure.store(0);data->u.DeviceInterface.ClassGuid=Hid;
    Callback(nullptr,&queue,CM_NOTIFY_ACTION_DEVICEINTERFACEARRIVAL,data,bytes);
    if(queue.failure.load()!=1)throw std::runtime_error("Callback did not reject class/path conflict");
    queue.failure.store(0);data->u.DeviceInterface.ClassGuid=Usb;
    data->u.DeviceInterface.SymbolicLink[fake.size()]=L'x';
    Callback(nullptr,&queue,CM_NOTIFY_ACTION_DEVICEINTERFACEARRIVAL,data,bytes);
    if(queue.failure.load()!=1)throw std::runtime_error("Callback did not reject unterminated payload");
    queue.failure.store(0);data->u.DeviceInterface.SymbolicLink[fake.size()]=0;
    for(unsigned i=0;i<257;++i)Callback(nullptr,&queue,CM_NOTIFY_ACTION_DEVICEINTERFACEARRIVAL,data,bytes);
    if(queue.failure.load()!=2)throw std::runtime_error("Callback queue exhaustion was not explicit");
    trace.Emit("host_callback_checks",",\"passed\":true");
}
} // namespace arrival_v1
