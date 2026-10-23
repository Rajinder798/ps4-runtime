// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
// Inert host-only worker: stdin gate, optional inherited-job child, file exit gate.
#define NOMINMAX
#include <windows.h>
#include <shellapi.h>
#include <filesystem>
#include <iostream>
#include <string>
#include <vector>

int WINAPI wWinMain(HINSTANCE, HINSTANCE, LPWSTR, int) {
    int argc = 0;
    auto argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    if (!argv)
        return 2;
    struct Arguments {
        wchar_t **value;
        ~Arguments() { LocalFree(value); }
    } cleanup{argv};
    if (argc != 3)
        return 2;
    if (std::wstring_view(argv[1]) == L"child") {
        auto end = GetTickCount64() + 15000;
        while (!std::filesystem::exists(argv[2]) && GetTickCount64() < end)
            Sleep(10);
        return 0;
    }
    if (std::wstring_view(argv[1]) != L"root")
        return 2;
    std::string command;
    char character = 0;
    DWORD received = 0;
    while (command.size() < 16 &&
           ReadFile(GetStdHandle(STD_INPUT_HANDLE), &character, 1, &received, nullptr) &&
           received) {
        if (character == '\n')
            break;
        if (character != '\r')
            command.push_back(character);
    }
    if (command == "stop")
        return 0;
    if (command != "tree")
        return 2;
    std::vector<wchar_t> path(32768);
    const auto length = GetModuleFileNameW(nullptr, path.data(), static_cast<DWORD>(path.size()));
    if (!length || length >= path.size())
        return 3;
    std::wstring args =
        L"\"" + std::wstring(path.data(), length) + L"\" child \"" + argv[2] + L"\"";
    STARTUPINFOW startup{};
    startup.cb = sizeof(startup);
    PROCESS_INFORMATION child{};
    if (!CreateProcessW(path.data(), args.data(), nullptr, nullptr, FALSE, CREATE_NO_WINDOW,
                        nullptr, nullptr, &startup, &child))
        return 3;
    CloseHandle(child.hThread);
    CloseHandle(child.hProcess);
    auto output = std::to_string(child.dwProcessId) + "\n";
    DWORD written = 0;
    if (!WriteFile(GetStdHandle(STD_OUTPUT_HANDLE), output.data(),
                   static_cast<DWORD>(output.size()), &written, nullptr) ||
        written != output.size())
        return 3;
    return 0;
}
