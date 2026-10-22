// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
// Owned inert test processes only: file gates and an optional inherited-job child.
#define NOMINMAX
#include <windows.h>
#include <shellapi.h>
#include <filesystem>
#include <fstream>
#include <string>
#include <vector>
int WINAPI wWinMain(HINSTANCE, HINSTANCE, LPWSTR, int) {
    int count = 0;
    auto args = CommandLineToArgvW(GetCommandLineW(), &count);
    if (!args)
        return 2;
    struct Cleanup {
        wchar_t **v;
        ~Cleanup() { LocalFree(v); }
    } cleanup{args};
    if (count != 4)
        return 2;
    std::wstring mode(args[1]);
    std::filesystem::path marker(args[2]), stop(args[3]);
    if (mode != L"worker" && mode != L"tree" && mode != L"child" && mode != L"exit")
        return 2;
    {
        std::ofstream file(marker);
        file << "inert host test entered\n";
        if (!file)
            return 3;
    }
    if (mode == L"exit")
        return 0;
    if (mode == L"tree") {
        std::vector<wchar_t> path(32768);
        auto length = GetModuleFileNameW(nullptr, path.data(), static_cast<DWORD>(path.size()));
        if (!length || length >= path.size())
            return 3;
        auto command = L"\"" + std::wstring(path.data(), length) + L"\" child \"" +
                       marker.wstring() + L".child\" \"" + stop.wstring() + L".child\"";
        STARTUPINFOW startup{};
        startup.cb = sizeof(startup);
        PROCESS_INFORMATION child{};
        if (!CreateProcessW(path.data(), command.data(), nullptr, nullptr, FALSE, CREATE_NO_WINDOW,
                            nullptr, nullptr, &startup, &child))
            return 3;
        CloseHandle(child.hThread);
        CloseHandle(child.hProcess);
        return 0;
    }
    auto end = GetTickCount64() + 15000;
    while (!std::filesystem::exists(stop) && GetTickCount64() < end)
        Sleep(5);
    return std::filesystem::exists(stop) ? 0 : 4;
}
