// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
// See LICENSE in the project root for the full license text.

#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <shobjidl.h>
#include <shlguid.h>

#include <filesystem>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
void Check(HRESULT result) {
    if (FAILED(result)) throw std::runtime_error("Windows shortcut COM operation failed.");
}
struct Apartment {
    Apartment() { Check(CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED)); }
    ~Apartment() { CoUninitialize(); }
};
template <typename T> struct Object {
    T* value = nullptr;
    ~Object() { if (value) value->Release(); }
    Object() = default;
    Object(const Object&) = delete;
    Object& operator=(const Object&) = delete;
};
std::string Json(const std::wstring& value) {
    if (value.empty()) return "\"\"";
    const int size = WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, value.data(),
        static_cast<int>(value.size()), nullptr, 0, nullptr, nullptr);
    if (!size) throw std::runtime_error("Invalid shortcut text.");
    std::string utf8(static_cast<size_t>(size), '\0');
    if (!WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, value.data(),
        static_cast<int>(value.size()), utf8.data(), size, nullptr, nullptr)) {
        throw std::runtime_error("Invalid shortcut text.");
    }
    std::string result = "\"";
    constexpr char hex[] = "0123456789abcdef";
    for (unsigned char c : utf8) {
        if (c == '"' || c == '\\') { result += '\\'; result += static_cast<char>(c); }
        else if (c < 32) { result += "\\u00"; result += hex[c >> 4]; result += hex[c & 15]; }
        else result += static_cast<char>(c);
    }
    return result + "\"";
}
template <typename Reader> std::wstring Read(Reader reader) {
    std::vector<wchar_t> buffer(32768, L'\0');
    Check(reader(buffer.data(), static_cast<int>(buffer.size())));
    return buffer.data();
}
} // namespace

// Internal COM adapter only. No shell execution, guest inspection or guest code.
// create new-link target arguments cwd description | inspect existing-link
int wmain(int argc, wchar_t** argv) {
    if (!((argc == 7 && std::wstring(argv[1]) == L"create") ||
          (argc == 3 && std::wstring(argv[1]) == L"inspect"))) return 2;
    try {
        const std::filesystem::path path(argv[2]);
        if (!path.is_absolute() || path.extension() != L".lnk") throw std::runtime_error("Absolute .lnk path required.");
        Apartment apartment;
        Object<IShellLinkW> link;
        Check(CoCreateInstance(CLSID_ShellLink, nullptr, CLSCTX_INPROC_SERVER,
                               IID_IShellLinkW, reinterpret_cast<void**>(&link.value)));
        Object<IPersistFile> file;
        Check(link.value->QueryInterface(IID_IPersistFile, reinterpret_cast<void**>(&file.value)));
        if (argc == 7) {
            if (std::filesystem::exists(path) || !std::filesystem::path(argv[3]).is_absolute() ||
                !std::filesystem::path(argv[5]).is_absolute()) throw std::runtime_error("New link and absolute target/cwd required.");
            Check(link.value->SetPath(argv[3]));
            Check(link.value->SetArguments(argv[4]));
            Check(link.value->SetWorkingDirectory(argv[5]));
            Check(link.value->SetDescription(argv[6]));
            Check(link.value->SetShowCmd(SW_SHOWNORMAL));
            Check(file.value->Save(path.c_str(), TRUE));
        } else {
            // Read stored properties without Resolve: inspection must never
            // search for/move to another target or trigger network/UI behavior.
            Check(file.value->Load(path.c_str(), STGM_READ));
        }
        const auto target = Read([&](wchar_t* text, int size) { return link.value->GetPath(text, size, nullptr, SLGP_RAWPATH); });
        const auto arguments = Read([&](wchar_t* text, int size) { return link.value->GetArguments(text, size); });
        const auto cwd = Read([&](wchar_t* text, int size) { return link.value->GetWorkingDirectory(text, size); });
        const auto description = Read([&](wchar_t* text, int size) { return link.value->GetDescription(text, size); });
        std::cout << "{\"schema_version\":1,\"target\":" << Json(target)
                  << ",\"arguments\":" << Json(arguments) << ",\"working_directory\":" << Json(cwd)
                  << ",\"description\":" << Json(description) << "}\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "shortcut-helper: " << error.what() << '\n';
        return 1;
    }
}
