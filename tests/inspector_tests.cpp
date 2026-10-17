#include "ps4/elf_inspector.h"

#include <cstdlib>
#include <iostream>
#include <limits>
#include <sstream>
#include <string>

namespace {
int checks = 0;
void check(bool condition, const std::string& label) {
    ++checks;
    if (!condition) { std::cerr << "FAIL: " << label << '\n'; std::exit(1); }
}
void put(std::string& data, std::size_t offset, std::uint64_t value, std::size_t width) {
    for (std::size_t i = 0; i < width; ++i) data.at(offset + i) = static_cast<char>((value >> (8 * i)) & 255);
}
std::string fixture() {
    std::string bytes(128, '\0');
    bytes.replace(0, 4, "\x7f" "ELF");
    put(bytes, 4, 2, 1); put(bytes, 5, 1, 1); put(bytes, 6, 1, 1);
    put(bytes, 16, 2, 2); put(bytes, 18, 62, 2); put(bytes, 20, 1, 4);
    put(bytes, 24, 0x1000, 8); put(bytes, 32, 64, 8);
    put(bytes, 52, 64, 2); put(bytes, 54, 56, 2); put(bytes, 56, 1, 2);
    put(bytes, 64, 1, 4); put(bytes, 68, 5, 4); put(bytes, 72, 120, 8);
    put(bytes, 80, 0x1000, 8); put(bytes, 96, 8, 8); put(bytes, 104, 16, 8);
    put(bytes, 112, 1, 8);
    return bytes;
}
ps4::Inspection inspect(const std::string& bytes) {
    std::istringstream stream(bytes, std::ios::binary);
    return ps4::inspect_elf(stream);
}
void reject(const std::string& bytes, const std::string& code) {
    try { (void)inspect(bytes); check(false, "expected " + code); }
    catch (const ps4::InspectionError& error) { check(error.code() == code, code + ": got " + error.code()); }
}
void mutation(std::size_t offset, std::uint64_t value, std::size_t width, const std::string& code) {
    auto bytes = fixture(); put(bytes, offset, value, width); reject(bytes, code);
}
}

int main() {
    const auto valid = inspect(fixture());
    check(valid.entry == 0x1000 && valid.entry_in_executable_segment, "entry inside RX load");
    check(valid.segments.size() == 1 && valid.segments[0].memory_size == 16, "BSS tail preserved");
    check(ps4::to_json(valid).find("\"execution_supported\":false") != std::string::npos, "honest execution status");
    check(ps4::to_text(valid).find("flags=R-X") != std::string::npos, "permissions rendered");
    for (const auto type : {2, 3, 0xfe00, 0xfe10, 0xfe18}) {
        auto bytes = fixture(); put(bytes, 16, type, 2);
        check(inspect(bytes).type == type, "supported ELF type");
    }
    for (std::size_t size = 0; size < 128; ++size) {
        try { (void)inspect(fixture().substr(0, size)); check(false, "accepted truncation " + std::to_string(size)); }
        catch (const ps4::InspectionError&) { check(true, "truncation rejected"); }
    }
    reject("O\x15=\x1d", "unsupported_self");
    reject("MZ!!", "bad_magic");
    mutation(4, 1, 1, "unsupported_class");
    mutation(5, 2, 1, "unsupported_endian");
    mutation(6, 0, 1, "unsupported_version");
    mutation(20, 0, 4, "unsupported_version");
    mutation(18, 183, 2, "unsupported_machine");
    mutation(16, 1, 2, "unsupported_type");
    mutation(52, 63, 2, "bad_header_size");
    mutation(54, 55, 2, "bad_segment_header_size");
    mutation(56, 0, 2, "missing_segments");
    mutation(56, 0xffff, 2, "unsupported_extended_count");
    mutation(32, 63, 8, "segment_table_out_of_bounds");
    mutation(32, std::numeric_limits<std::uint64_t>::max(), 8, "segment_table_out_of_bounds");
    mutation(72, std::numeric_limits<std::uint64_t>::max(), 8, "segment_out_of_bounds");
    mutation(96, std::numeric_limits<std::uint64_t>::max(), 8, "segment_out_of_bounds");
    mutation(104, 7, 8, "segment_size_mismatch");
    mutation(80, std::numeric_limits<std::uint64_t>::max() - 8, 8, "address_overflow");
    mutation(112, 3, 8, "bad_alignment");
    mutation(112, 4096, 8, "misaligned_segment");
    mutation(64, 4, 4, "missing_load_segment");
    for (auto alignment : {0, 1, 8}) {
        auto bytes = fixture(); put(bytes, 112, alignment, 8);
        check(inspect(bytes).segments[0].alignment == static_cast<unsigned>(alignment), "valid alignment");
    }
    auto bytes = fixture(); put(bytes, 24, 0x1010, 8);
    check(!inspect(bytes).entry_in_executable_segment, "entry at exclusive segment end");
    put(bytes, 24, 0xfff, 8);
    check(!inspect(bytes).entry_in_executable_segment, "entry before segment");
    bytes = fixture(); put(bytes, 68, 6, 4);
    check(!inspect(bytes).entry_in_executable_segment, "entry in non-executable segment");
    // PT_NULL contents are undefined; even garbage ranges must be ignored.
    bytes = fixture(); bytes.resize(184, '\xff'); put(bytes, 56, 2, 2); put(bytes, 120, 0, 4);
    check(inspect(bytes).segments.size() == 2, "PT_NULL ignored");
    // Exercise the same range checks for TLS and SCE_RELRO while retaining PT_LOAD.
    for (auto type : {7, 0x61000010}) {
        bytes = fixture(); bytes.resize(184, '\0'); put(bytes, 56, 2, 2);
        put(bytes, 120, type, 4); put(bytes, 152, 1, 8);
        reject(bytes, "segment_size_mismatch");
    }
    std::cout << checks << " ELF validation checks passed\n";
}
