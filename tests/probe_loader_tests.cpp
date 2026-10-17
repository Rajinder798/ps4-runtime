// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
// See LICENSE in the project root for the full license text.

#include "ps4/probe_loader.h"

#include <algorithm>
#include <cerrno>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>

#ifdef _WIN32
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#else
#include <sys/mman.h>
#endif

namespace {
int checks = 0;
void check(bool condition, const std::string& label) {
    ++checks;
    if (!condition) { std::cerr << "FAIL: " << label << '\n'; std::exit(1); }
}
void put(std::string& data, std::size_t offset, std::uint64_t value, std::size_t width) {
    for (std::size_t i = 0; i < width; ++i) data.at(offset + i) = static_cast<char>((value >> (8 * i)) & 255);
}
// Independently encode the loader fixture to cross-check the Python generator.
std::string fixture() {
    std::string data(8200, '\0');
    data.replace(0, 4, "\x7f" "ELF");
    put(data, 4, 2, 1); put(data, 5, 1, 1); put(data, 6, 1, 1); put(data, 7, 9, 1);
    put(data, 16, 0xfe10, 2); put(data, 18, 62, 2); put(data, 20, 1, 4);
    put(data, 24, 0x1000, 8); put(data, 32, 64, 8);
    put(data, 52, 64, 2); put(data, 54, 56, 2); put(data, 56, 2, 2);
    put(data, 64, 1, 4); put(data, 68, 5, 4); put(data, 72, 0x1000, 8);
    put(data, 80, 0x1000, 8); put(data, 96, 6, 8); put(data, 104, 6, 8); put(data, 112, 4096, 8);
    put(data, 120, 1, 4); put(data, 124, 6, 4); put(data, 128, 0x2000, 8);
    put(data, 136, 0x4000, 8); put(data, 152, 8, 8); put(data, 160, 4096, 8); put(data, 168, 4096, 8);
    data.replace(0x1000, 6, "\xb8\x2a\0\0\0\xc3", 6);
    data.replace(0x2000, 8, "PS4PROBE");
    return data;
}
void rejected(const std::string& data, const std::string& code, bool call = false) {
    try {
        std::istringstream input(data, std::ios::binary);
        const ps4::MappedImage image(input);
        if (call) (void)image.call_probe();
        check(false, "expected " + code);
    } catch (const ps4::InspectionError& error) {
        check(error.code() == code, code + ": got " + error.code());
    }
}
void mutation(std::size_t offset, std::uint64_t value, std::size_t width, const std::string& code, bool call = false) {
    auto data = fixture(); put(data, offset, value, width); rejected(data, code, call);
}

std::string permissions(const void* address) {
#ifdef _WIN32
    MEMORY_BASIC_INFORMATION info{};
    if (VirtualQuery(address, &info, sizeof(info)) == 0) return "query-failed";
    if (info.State != MEM_COMMIT) return "---";
    switch (info.Protect & 0xff) {
    case PAGE_READONLY: return "r--";
    case PAGE_READWRITE: return "rw-";
    case PAGE_EXECUTE_READ: return "r-x";
    default: return "unexpected";
    }
#else
    std::ifstream maps("/proc/self/maps");
    for (std::string line; std::getline(maps, line);) {
        std::istringstream fields(line);
        std::string range, flags;
        fields >> range >> flags;
        const auto dash = range.find('-');
        const auto begin = std::stoull(range.substr(0, dash), nullptr, 16);
        const auto end = std::stoull(range.substr(dash + 1), nullptr, 16);
        const auto value = reinterpret_cast<std::uintptr_t>(address);
        if (value >= begin && value < end) return flags.substr(0, 3);
    }
    return "---";
#endif
}

// Fail a data read after the first segment is committed/protected. This exercises
// cleanup when construction cannot finish, rather than only parser rejection.
class FailedPayload : public std::stringbuf {
public:
    explicit FailedPayload(const std::string& data) : std::stringbuf(data, std::ios::in) {}
protected:
    std::streamsize xsgetn(char* target, std::streamsize count) override {
        if (gptr() - eback() == 0x2000) return 0;
        return std::stringbuf::xsgetn(target, count);
    }
};
} // namespace

int main() {
    std::uintptr_t released_address = 0;
    std::size_t page_size = 0;
    {
        std::istringstream input(fixture(), std::ios::binary);
        const ps4::MappedImage image(input);
        page_size = image.page_size();
        check(page_size == 4096, "tested x86-64 page size");
        check(image.mapped_size() == 0x4000, "rebased image includes gaps");
        const auto code = image.bytes(0x1000, 6);
        const auto data = image.bytes(0x4000, 4096);
        released_address = reinterpret_cast<std::uintptr_t>(code.data());
        check(reinterpret_cast<std::uintptr_t>(data.data()) - released_address == 0x3000, "guest address spacing preserved");
        check(code[0] == 0xb8 && code[1] == 42 && code[5] == 0xc3, "instructions copied");
        check(std::string(reinterpret_cast<const char*>(data.data()), 8) == "PS4PROBE", "data copied");
        check(std::all_of(data.begin() + 8, data.end(), [](unsigned char b) { return b == 0; }), "complete BSS tail is zero");
        check(permissions(code.data()) == "r-x", "OS reports RX code");
        check(permissions(data.data()) == "rw-", "OS reports RW data");
        check(permissions(reinterpret_cast<const void*>(released_address + page_size)) == "---", "OS reports inaccessible gap");
        check(image.call_probe() == 42, "native probe returns 42");
        check(ps4::probe_json(image, 42).find("\"general_execution_supported\":false") != std::string::npos, "limited execution status");
        for (const auto address : {0x0fff, 0x1006, 0x2000, 0x4fff}) {
            try { (void)image.bytes(address, 2); check(false, "range should fail"); }
            catch (const ps4::InspectionError& error) { check(error.code() == "unmapped_range", "range API rejects gap/boundary"); }
        }
        // Writable data really is writable; the execution guard detects damaged BSS.
        auto* writable_data = const_cast<unsigned char*>(data.data());
        writable_data[4095] = 1;
        check(writable_data[4095] == 1, "RW segment accepts writes");
        try { (void)image.call_probe(); check(false, "modified BSS accepted"); }
        catch (const ps4::InspectionError& error) { check(error.code() == "probe_zero_fill_failed", "BSS checked before call"); }
    }
#ifdef _WIN32
    MEMORY_BASIC_INFORMATION info{};
    check(VirtualQuery(reinterpret_cast<void*>(released_address), &info, sizeof(info)) != 0 && info.State == MEM_FREE,
          "destructor releases reserved address range");
#else
    unsigned char residency = 0;
    errno = 0;
    check(mincore(reinterpret_cast<void*>(released_address), page_size, &residency) == -1 && errno == ENOMEM,
          "destructor unmaps image");
#endif
    mutation(16, 2, 2, "unsupported_mapping_type");
    mutation(120, 2, 4, "unsupported_mapping_segment");
    mutation(120, 7, 4, "unsupported_mapping_segment");
    mutation(104, 0, 8, "segment_size_mismatch");
    auto data = fixture(); put(data, 96, 0, 8); put(data, 104, 0, 8); rejected(data, "empty_load_segment");
    mutation(68, 7, 4, "writable_executable_segment");
    mutation(68, 1, 4, "unsupported_segment_permissions");
    mutation(168, 8192, 8, "unsupported_mapping_alignment");
    mutation(136, 0x1000, 8, "overlapping_segment_pages");
    data = fixture(); put(data, 168, 1, 8); put(data, 136, 0x1008, 8);
    rejected(data, "overlapping_segment_pages");
    mutation(160, 64 * 1024 * 1024, 8, "image_too_large");
    data = fixture(); put(data, 112, 1, 8); put(data, 80, UINT64_MAX - 7, 8);
    rejected(data, "mapping_address_overflow");
    mutation(0x1001, 43, 1, "unsupported_probe", true);
    mutation(0x1000, 0xcc, 1, "unsupported_probe", true); // must never execute INT3
    mutation(0x2000, 'X', 1, "unsupported_probe", true);
    mutation(24, 0x1001, 8, "unsupported_probe", true);
    mutation(7, 0, 1, "unsupported_probe", true);
    mutation(124, 4, 4, "unsupported_probe", true);
    {
        data = fixture(); put(data, 16, 3, 2); put(data, 124, 4, 4); put(data, 152, 0, 8);
        std::istringstream input(data, std::ios::binary);
        const ps4::MappedImage image(input);
        const auto bss = image.bytes(0x4000, 4096);
        check(std::all_of(bss.begin(), bss.end(), [](unsigned char byte) { return byte == 0; }), "BSS-only segment");
        check(permissions(bss.data()) == "r--", "OS reports read-only data");
        check(image.inspection().type == 3, "ET_DYN can map without executing");
    }
    {
        data = fixture(); put(data, 56, 3, 2);
        // The unused third entry is all zeros in the original fixture.
        std::istringstream input(data, std::ios::binary);
        const ps4::MappedImage image(input);
        check(image.inspection().segments.size() == 3, "PT_NULL accepted during mapping");
    }
    data = fixture(); data.resize(64 + 129 * 56, '\0'); put(data, 56, 129, 2);
    // Program headers now overwrite original payload, but remain structurally valid.
    std::fill(data.begin() + 176, data.end(), '\0');
    put(data, 128, 0, 8); put(data, 72, 0, 8);
    rejected(data, "too_many_segments");
    FailedPayload buffer(fixture());
    std::istream broken(&buffer);
    try { const ps4::MappedImage image(broken); check(false, "failed payload accepted"); }
    catch (const ps4::InspectionError& error) { check(error.code() == "segment_read_failed", "late read failure reported"); }
    for (int i = 0; i < 16; ++i) {
        std::istringstream input(fixture(), std::ios::binary);
        const ps4::MappedImage image(input);
        check(image.call_probe() == 42, "repeat map/call/release");
    }
    std::cout << checks << " loader checks passed\n";
}
