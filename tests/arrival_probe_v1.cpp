// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
// A separate opt-in binary. The frozen historical observer is included unchanged;
// wrappers add diagnostics around real SDL calls, never substitute their results.
#include <SDL3/SDL.h>
#include "arrival_windows_v1.h"
#include <iostream>
#include <memory>
#include <vector>
static_assert(SDL_EVENT_JOYSTICK_ADDED==0x605 && SDL_EVENT_JOYSTICK_REMOVED==0x606 &&
              SDL_EVENT_GAMEPAD_ADDED==0x653 && SDL_EVENT_GAMEPAD_REMOVED==0x654 && SDL_EVENT_GAMEPAD_REMAPPED==0x655);

namespace {
arrival_v1::Trace* trace=nullptr;
arrival_v1::WindowsArrival* notifications=nullptr;
std::int64_t last_inventory=0;
unsigned original_id=0;
bool removed=false;
unsigned open_count=0;
SDL_JoystickID added_event=0;
std::string first_failure;
void Fail(const char* text) {
    if (first_failure.empty()) first_failure=text;
    try {trace->Fail(first_failure);} catch (...) {} // stderr/failed exit still preserve I/O failure.
}
std::string DeviceFields(SDL_JoystickID id) {
    const unsigned vendor=SDL_GetJoystickVendorForID(id),product=SDL_GetJoystickProductForID(id);
    const bool intended=vendor==1356 && product==3302;
    const bool mapped=SDL_IsGamepad(id);
    return "\"instance_id\":"+std::to_string(id)+",\"vendor\":"+std::to_string(intended?vendor:0)+
        ",\"product\":"+std::to_string(intended?product:0)+",\"identity_redacted\":"+(intended?"false":"true")+
        ",\"real_type\":"+std::to_string(mapped?static_cast<int>(SDL_GetRealGamepadTypeForID(id)):0)+
        ",\"virtual\":"+(SDL_IsJoystickVirtual(id)?"true":"false")+
        ",\"is_gamepad\":"+(mapped?"true":"false");
}
std::string Inventory(SDL_JoystickID* ids,int count) {
    if (!ids || count<0 || count>16) throw std::runtime_error("SDL enumeration unavailable or exceeds bound");
    std::string result="[";
    for (int i=0;i<count;++i) {if(i)result+=',';result+='{'+DeviceFields(ids[i])+'}';}
    return result+']';
}
void Snapshot() {
    const auto begin=arrival_v1::Ticks();int jc=0,gc=0;
    std::unique_ptr<SDL_JoystickID,decltype(&SDL_free)> joysticks(SDL_GetJoysticks(&jc),SDL_free);
    std::unique_ptr<SDL_JoystickID,decltype(&SDL_free)> gamepads(SDL_GetGamepads(&gc),SDL_free);
    const auto fields=",\"qpc_begin\":"+std::to_string(begin)+",\"joysticks\":"+Inventory(joysticks.get(),jc)+
        ",\"gamepads\":"+Inventory(gamepads.get(),gc)+",\"qpc_end\":"+std::to_string(arrival_v1::Ticks());
    trace->Emit("sdl_inventory",fields);
}
bool ArrivalInit(SDL_InitFlags flags) {
    try {
        notifications->Start();
        const bool okay=SDL_Init(flags);
        trace->Emit("sdl_init",std::string(",\"ok\":")+(okay?"true":"false"));
        if (!okay) {Fail("sdl_init_failed");return false;}
        const auto before=arrival_v1::Ticks();const auto ns=SDL_GetTicksNS();const auto after=arrival_v1::Ticks();
        trace->Emit("sdl_clock_anchor",",\"qpc_begin\":"+std::to_string(before)+",\"sdl_ns\":"+
                    std::to_string(ns)+",\"qpc_end\":"+std::to_string(after));
        return true;
    } catch (...) {Fail("initial_diagnostics_failed");throw;}
}
SDL_JoystickID* ArrivalGamepads(int* count) {
    auto* ids=SDL_GetGamepads(count);
    try {
        trace->Emit("sdl_gamepads_query",",\"devices\":"+Inventory(ids,*count));
        const auto id=(ids && *count==1)?ids[0]:0;
        std::string reason=arrival_v1::Candidate(*count,SDL_GetGamepadVendorForID(id),SDL_GetGamepadProductForID(id),
            static_cast<int>(SDL_GetRealGamepadTypeForID(id)),SDL_IsJoystickVirtual(id),id,removed?original_id:0);
        if (reason=="candidate" && added_event && id!=added_event) reason="event_instance_mismatch";
        trace->Emit("candidate_assessment",",\"instance_id\":"+std::to_string(id)+",\"reason\":"+arrival_v1::Quote(reason));
        if(reason!="candidate")Fail("strict_candidate_rejected");
        return ids;
    } catch (...) {SDL_free(ids);Fail("enumeration_diagnostics_failed");throw;}
}
SDL_Gamepad* ArrivalOpen(SDL_JoystickID id) {
    SDL_Gamepad* pad=nullptr;
    try {
        trace->Emit("sdl_open_attempt",",\"instance_id\":"+std::to_string(id));
        pad=SDL_OpenGamepad(id);
        const bool wired=pad && SDL_GetGamepadConnectionState(pad)==SDL_JOYSTICK_CONNECTION_WIRED;
        trace->Emit("sdl_open_result",",\"instance_id\":"+std::to_string(id)+",\"ok\":"+(pad?"true":"false")+
            ",\"wired\":"+(wired?"true":"false"));
        if (pad) {if (!original_id) original_id=id;++open_count;}
        if(!pad)Fail("sdl_open_failed");else if(!wired)Fail("wired_verification_failed");
        return pad;
    } catch (...) {if(pad)SDL_CloseGamepad(pad);Fail("open_diagnostics_failed");throw;}
}
bool ArrivalPoll(SDL_Event* event) {
    try {
        notifications->Poll();
        const bool found=SDL_PollEvent(event);
        const auto now=arrival_v1::Ticks();
        if (found && (event->type==SDL_EVENT_JOYSTICK_ADDED || event->type==SDL_EVENT_JOYSTICK_REMOVED ||
                      event->type==SDL_EVENT_GAMEPAD_ADDED || event->type==SDL_EVENT_GAMEPAD_REMOVED ||
                      event->type==SDL_EVENT_GAMEPAD_REMAPPED)) {
            const auto id=event->jdevice.which;
            trace->Emit("raw_sdl_event",",\"type\":"+std::to_string(event->type)+",\"instance_id\":"+
                std::to_string(id)+",\"sdl_timestamp_ns\":"+std::to_string(event->common.timestamp));
            const auto reason=arrival_v1::RawAssessment(event->type,id,original_id,removed,open_count);
            trace->Emit("sdl_event_assessment",",\"instance_id\":"+std::to_string(id)+",\"reason\":"+arrival_v1::Quote(reason));
            if(reason=="unexpected_addition" || reason=="unexpected_removal" || reason=="remap_rejected")
                Fail("strict_event_rejected");
            if (event->type==SDL_EVENT_GAMEPAD_ADDED) added_event=id;
            if (event->type==SDL_EVENT_GAMEPAD_REMOVED && id==original_id) removed=true;
            Snapshot(); // Diagnostic only; the historical handler still makes its own query.
        }
        if (now-last_inventory>=arrival_v1::Frequency()) {
            Snapshot();trace->Emit("poll_heartbeat");last_inventory=now;
        }
        return found;
    } catch (...) {Fail("poll_diagnostics_failed");throw;}
}
} // namespace

// These intercept only real API calls inside the unmodified historical source.
#define SDL_Init ArrivalInit
#define SDL_GetGamepads ArrivalGamepads
#define SDL_OpenGamepad ArrivalOpen
#define SDL_PollEvent ArrivalPoll
#define main HistoricalObserverMain
#include "dualsense_sdl_probe.cpp"
#undef main
#undef SDL_Init
#undef SDL_GetGamepads
#undef SDL_OpenGamepad
#undef SDL_PollEvent

int main(int argc,char** argv) {
    if (argc!=10 || std::string(argv[1])!="--watch-arrival-v1" ||
        std::string(argv[7])!="--disconnect-authorized" || std::string(argv[8])!="--reconnect-authorized" ||
        std::string(argv[9])!="--arrival-diagnostics-authorized") {
        std::cerr<<"Separate authorized watch-arrival-v1 mode required; nothing initialized\n";return 2;
    }
    std::unique_ptr<arrival_v1::Trace> output;
    std::unique_ptr<arrival_v1::WindowsArrival> windows;
    try {
        const auto diag=std::filesystem::absolute(argv[6]).lexically_normal();
        for (int i=2;i<=4;++i) if(diag==std::filesystem::absolute(argv[i]).lexically_normal())
            throw std::runtime_error("Diagnostic path aliases strict transport");
        output=std::make_unique<arrival_v1::Trace>(diag);trace=output.get();
        windows=std::make_unique<arrival_v1::WindowsArrival>(*trace);notifications=windows.get();
        char mode[]="--watch-hotplug";
        char* legacy[]={argv[0],mode,argv[2],argv[3],argv[4],argv[5],argv[7],argv[8]};
        const int code=HistoricalObserverMain(8,legacy);
        if (code) Fail("strict_observer_failed");
        const bool cleanup=windows->Close();output->Finish(cleanup);
        return code || !cleanup || output->Failed()?1:0;
    } catch (const std::exception& error) {
        if (output) {
            Fail("diagnostic_exception");
            const bool cleanup=!windows || windows->Close();
            try {output->Finish(cleanup);} catch (...) {}
        }
        std::cerr<<"Arrival v1 failure: "<<(first_failure.empty()?error.what():first_failure)<<'\n';return 1;
    }
}
