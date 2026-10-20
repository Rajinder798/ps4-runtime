// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later

// Opt-in physical-device observer linked to the existing pinned research SDL.
// No synthetic devices/events, keyboard injection, audio/video initialization,
// explicit rumble/LED/sensor setters, serial numbers, MACs or device paths.
#include <SDL3/SDL.h>
#include <windows.h>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>

static void Check(bool value) { if (!value) throw std::runtime_error(SDL_GetError()); }
static std::string Quoted(const char* value) {
    std::string result = "\"";
    for (const unsigned char ch : std::string(value ? value : "")) {
        if (ch == '\\' || ch == '"') result += '\\';
        if (ch >= 32) result += static_cast<char>(ch);
    }
    return result + '"';
}
static long long Counter() { LARGE_INTEGER q{}; QueryPerformanceCounter(&q); return q.QuadPart; }

int main(int argc, char** argv) {
    SDL_Gamepad* selected = nullptr;
    try {
        const bool discover = argc == 2 && std::string(argv[1]) == "--discover";
        const bool axes = argc == 6 && std::string(argv[1]) == "--watch-axes";
        const bool watch = argc == 6 && (std::string(argv[1]) == "--watch" || axes);
        if (!discover && !watch) throw std::runtime_error("Use --discover, --watch or --watch-axes report stop ready timeout-ms");
        unsigned timeout = 0;
        std::filesystem::path report, stop, ready;
        if (watch) {
            const std::string number(argv[5]);
            if (number.empty() || number.find_first_not_of("0123456789") != std::string::npos)
                throw std::runtime_error("Invalid timeout");
            timeout = static_cast<unsigned>(std::stoul(number));
            if (timeout < 100 || timeout > 1800000) throw std::runtime_error("Bounded timeout required");
            report = argv[2]; stop = argv[3]; ready = argv[4];
            if (report == stop || report == ready || stop == ready || std::filesystem::exists(report) ||
                    std::filesystem::exists(stop) || std::filesystem::exists(ready))
                throw std::runtime_error("Distinct fresh outputs required");
        }
        // Applies only to this observer, which deliberately has no foreground window.
        Check(SDL_SetHint(SDL_HINT_JOYSTICK_ALLOW_BACKGROUND_EVENTS, "1"));
        Check(SDL_Init(SDL_INIT_GAMEPAD));
        int count = 0;
        SDL_JoystickID* ids = SDL_GetGamepads(&count);
        if (!ids) throw std::runtime_error(SDL_GetError());
        std::cout << "{\"sdl_version\":" << SDL_GetVersion() << ",\"gamepads\":[";
        SDL_JoystickID chosen = 0;
        for (int i = 0; i < count; ++i) {
            const auto id = ids[i];
            const bool dualsense = SDL_GetGamepadVendorForID(id) == 0x054c &&
                SDL_GetGamepadProductForID(id) == 0x0ce6 && SDL_GetRealGamepadTypeForID(id) == SDL_GAMEPAD_TYPE_PS5 &&
                !SDL_IsJoystickVirtual(id);
            if (dualsense) chosen = id;
            if (i) std::cout << ',';
            std::cout << "{\"instance_id\":" << id << ",\"name\":" << Quoted(SDL_GetGamepadNameForID(id))
                << ",\"vendor\":" << SDL_GetGamepadVendorForID(id) << ",\"product\":" << SDL_GetGamepadProductForID(id)
                << ",\"real_type\":" << SDL_GetRealGamepadTypeForID(id) << ",\"virtual\":"
                << (SDL_IsJoystickVirtual(id) ? "true" : "false") << ",\"dualsense_candidate\":"
                << (dualsense ? "true" : "false") << '}';
        }
        std::cout << "]}" << std::endl;
        SDL_free(ids);
        if (discover) { SDL_Quit(); return chosen && count == 1 ? 0 : 2; }
        if (!chosen || count != 1) throw std::runtime_error("Exactly one nonvirtual Sony DualSense must be recognized");
        selected = SDL_OpenGamepad(chosen);
        if (!selected) throw std::runtime_error(SDL_GetError());
        if (SDL_GetGamepadConnectionState(selected) != SDL_JOYSTICK_CONNECTION_WIRED)
            throw std::runtime_error("USB wired connection was not confirmed by SDL");
        std::ofstream stream(report);
        stream.exceptions(std::ios::failbit | std::ios::badbit);
        LARGE_INTEGER frequency{}; QueryPerformanceFrequency(&frequency);
        stream << "{\"event\":\"opened\",\"instance_id\":" << chosen
            << ",\"qpc\":" << Counter() << ",\"qpc_frequency\":" << frequency.QuadPart
            << ",\"connection\":\"wired\",\"vendor\":1356,\"product\":3302,\"virtual\":false}\n" << std::flush;
        std::ofstream(ready) << "wired DualSense ready\n";
        const auto began = SDL_GetTicks();
        unsigned previous_buttons = ~0u;
        bool previous_connected = true;
        Uint64 last_axes = 0;
        for (;;) {
            SDL_Event event{};
            while (SDL_PollEvent(&event)) {
                if ((event.type == SDL_EVENT_GAMEPAD_BUTTON_DOWN || event.type == SDL_EVENT_GAMEPAD_BUTTON_UP) &&
                        event.gbutton.which == chosen)
                    stream << "{\"event\":\"physical_button\",\"qpc\":" << Counter()
                        << ",\"instance_id\":" << chosen << ",\"button\":" << unsigned(event.gbutton.button)
                        << ",\"down\":" << (event.gbutton.down ? "true" : "false") << "}\n" << std::flush;
                if (event.type == SDL_EVENT_GAMEPAD_REMOVED && event.gdevice.which == chosen)
                    stream << "{\"event\":\"removed\",\"qpc\":" << Counter() << "}\n" << std::flush;
                if (axes && event.type == SDL_EVENT_GAMEPAD_AXIS_MOTION && event.gaxis.which == chosen && event.gaxis.axis < 4)
                    stream << "{\"event\":\"physical_axis\",\"qpc\":" << Counter()
                        << ",\"instance_id\":" << chosen << ",\"axis\":" << unsigned(event.gaxis.axis)
                        << ",\"value\":" << event.gaxis.value << "}\n" << std::flush;
            }
            const bool connected = SDL_GamepadConnected(selected);
            unsigned buttons = 0;
            for (int b = 0; connected && b < SDL_GAMEPAD_BUTTON_COUNT; ++b)
                if (SDL_GetGamepadButton(selected, static_cast<SDL_GamepadButton>(b))) buttons |= 1u << b;
            if (buttons != previous_buttons || connected != previous_connected) {
                stream << "{\"event\":\"state\",\"qpc\":" << Counter() << ",\"connected\":"
                    << (connected ? "true" : "false") << ",\"buttons\":" << buttons << "}\n" << std::flush;
                previous_buttons = buttons; previous_connected = connected;
            }
            if (axes && SDL_GetTicks() >= last_axes) {
                stream << "{\"event\":\"axis_state\",\"qpc\":" << Counter()
                    << ",\"connected\":" << (connected ? "true" : "false") << ",\"buttons\":" << buttons << ",\"axes\":[";
                for (int axis = 0; axis < 4; ++axis) {
                    if (axis) stream << ',';
                    stream << SDL_GetGamepadAxis(selected, static_cast<SDL_GamepadAxis>(axis));
                }
                stream << "]}\n" << std::flush;
                last_axes = SDL_GetTicks() + 100;
            }
            if (std::filesystem::exists(stop)) break;
            if (SDL_GetTicks() - began > timeout) throw std::runtime_error("Observer budget expired; no automatic retry");
            SDL_Delay(10);
        }
        stream << "{\"event\":\"stopped\",\"qpc\":" << Counter() << "}\n" << std::flush;
        SDL_CloseGamepad(selected); selected = nullptr;
        SDL_Quit(); return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        if (selected) SDL_CloseGamepad(selected);
        SDL_Quit(); return 1;
    }
}
