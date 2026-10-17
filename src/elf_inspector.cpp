// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
// See LICENSE in the project root for the full license text.

#include "ps4/elf_inspector.h"

#include <array>
#include <limits>
#include <sstream>

namespace ps4 {
namespace {
using Bytes = std::array<unsigned char, 64>;

[[noreturn]] void fail(const std::string& code, const std::string& message) {
    throw InspectionError(code, message);
}

std::uint64_t little(const Bytes& bytes, std::size_t offset, std::size_t count) {
    std::uint64_t value = 0;
    for (std::size_t i = 0; i < count; ++i)
        value |= static_cast<std::uint64_t>(bytes[offset + i]) << (i * 8);
    return value;
}

bool fits(std::uint64_t offset, std::uint64_t size, std::uint64_t limit) {
    return offset <= limit && size <= limit - offset;
}

Bytes read_at(std::istream& input, std::uint64_t offset, std::size_t size) {
    Bytes bytes{};
    input.seekg(static_cast<std::streamoff>(offset), std::ios::beg);
    if (!input.read(reinterpret_cast<char*>(bytes.data()), static_cast<std::streamsize>(size)))
        fail("read_failed", "Could not read the executable header or segment table.");
    return bytes;
}

bool supported_type(std::uint16_t type) {
    return type == 2 || type == 3 || type == 0xfe00 || type == 0xfe10 || type == 0xfe18;
}

const char* type_name(std::uint16_t type) {
    switch (type) {
    case 2: return "ET_EXEC";
    case 3: return "ET_DYN";
    case 0xfe00: return "ET_SCE_EXEC";
    case 0xfe10: return "ET_SCE_DYNEXEC";
    case 0xfe18: return "ET_SCE_DYNAMIC";
    default: return "unknown";
    }
}
} // namespace

Inspection inspect_elf(std::istream& input) {
    input.clear();
    input.seekg(0, std::ios::end);
    const auto end = input.tellg();
    if (end < 0) fail("read_failed", "Input must be a readable, seekable binary stream.");
    const auto size = static_cast<std::uint64_t>(end);
    if (size < 4) fail("truncated_header", "Input is too short for an executable signature.");
    const auto signature = read_at(input, 0, 4);
    if (little(signature, 0, 4) == 0x1d3d154f)
        fail("unsupported_self", "SELF containers are not supported. Supply an unpacked ELF file.");
    if (little(signature, 0, 4) != 0x464c457f)
        fail("bad_magic", "Input does not have an ELF signature.");
    if (size < 64) fail("truncated_header", "ELF64 requires a 64-byte header.");
    const auto header = read_at(input, 0, 64);
    if (header[4] != 2) fail("unsupported_class", "Only ELF64 is supported.");
    if (header[5] != 1) fail("unsupported_endian", "Only little-endian ELF is supported.");
    if (header[6] != 1 || little(header, 20, 4) != 1)
        fail("unsupported_version", "Expected ELF version 1 in both version fields.");
    if (little(header, 18, 2) != 62)
        fail("unsupported_machine", "Only x86-64 ELF is supported.");
    const auto type = static_cast<std::uint16_t>(little(header, 16, 2));
    if (!supported_type(type)) fail("unsupported_type", "Expected an executable or shared-object ELF type.");
    if (little(header, 52, 2) != 64)
        fail("bad_header_size", "Expected an ELF64 header size of 64.");
    const auto table = little(header, 32, 8);
    const auto count = little(header, 56, 2);
    if (count == 0xffff)
        fail("unsupported_extended_count", "Extended program-header counts are not supported.");
    if (count == 0) fail("missing_segments", "Executable has no program headers.");
    if (little(header, 54, 2) != 56)
        fail("bad_segment_header_size", "Expected 56-byte ELF64 program headers.");
    if (table < 64 || !fits(table, count * 56, size))
        fail("segment_table_out_of_bounds", "Program-header table is outside the file or overlaps the ELF header.");

    Inspection result{size, little(header, 24, 8), type, header[7], header[8], false, {}};
    result.segments.reserve(static_cast<std::size_t>(count));
    bool has_load = false;
    for (std::uint64_t i = 0; i < count; ++i) {
        const auto bytes = read_at(input, table + i * 56, 56);
        const Segment segment{
            static_cast<std::uint32_t>(little(bytes, 0, 4)),
            static_cast<std::uint32_t>(little(bytes, 4, 4)),
            little(bytes, 8, 8), little(bytes, 16, 8),
            little(bytes, 32, 8), little(bytes, 40, 8), little(bytes, 48, 8)};
        // PT_NULL fields are undefined and must not be interpreted.
        if (segment.type != 0) {
            if (!fits(segment.offset, segment.file_size, size))
                fail("segment_out_of_bounds", "Segment " + std::to_string(i) + " file range is outside the file.");
            const bool memory_image = segment.type == 1 || segment.type == 7 || segment.type == 0x61000010;
            if (memory_image) {
                if (segment.file_size > segment.memory_size)
                    fail("segment_size_mismatch", "Segment file size exceeds its memory size.");
                if (!fits(segment.address, segment.memory_size, std::numeric_limits<std::uint64_t>::max()))
                    fail("address_overflow", "Segment virtual address range overflows 64 bits.");
                const auto alignment = segment.alignment;
                if (alignment > 1 && (alignment & (alignment - 1)) != 0)
                    fail("bad_alignment", "Segment alignment must be zero, one, or a power of two.");
                if (alignment > 1 && segment.address % alignment != segment.offset % alignment)
                    fail("misaligned_segment", "Segment file offset and virtual address are incongruent.");
            }
            if (segment.type == 1) has_load = true;
            if ((segment.type == 1 || segment.type == 0x61000010) && (segment.flags & 1) != 0 &&
                result.entry >= segment.address && result.entry - segment.address < segment.memory_size)
                result.entry_in_executable_segment = true;
        }
        result.segments.push_back(segment);
    }
    if (!has_load) fail("missing_load_segment", "Executable has no PT_LOAD segment.");
    return result;
}

std::string to_json(const Inspection& result) {
    std::ostringstream out;
    out << "{\"schema_version\":1,\"format\":\"ELF64\",\"machine\":\"x86-64\",\"type\":\""
        << type_name(result.type) << "\",\"type_id\":" << result.type
        << ",\"os_abi\":" << static_cast<unsigned>(result.os_abi)
        << ",\"abi_version\":" << static_cast<unsigned>(result.abi_version)
        << ",\"file_size\":" << result.file_size << ",\"entry\":" << result.entry
        << ",\"entry_in_executable_segment\":" << (result.entry_in_executable_segment ? "true" : "false")
        << ",\"execution_supported\":false,\"segments\":[";
    for (std::size_t i = 0; i < result.segments.size(); ++i) {
        if (i != 0) out << ',';
        const auto& s = result.segments[i];
        out << "{\"type\":" << s.type << ",\"flags\":" << s.flags << ",\"offset\":" << s.offset
            << ",\"address\":" << s.address << ",\"file_size\":" << s.file_size
            << ",\"memory_size\":" << s.memory_size << ",\"alignment\":" << s.alignment << '}';
    }
    out << "]}\n";
    return out.str();
}

std::string to_text(const Inspection& result) {
    std::ostringstream out;
    out << "ELF64 little-endian x86-64 | " << type_name(result.type)
        << "\nFile size: " << result.file_size << " bytes\nOS ABI: " << static_cast<unsigned>(result.os_abi)
        << " | ABI version: " << static_cast<unsigned>(result.abi_version)
        << "\nEntry: 0x" << std::hex << result.entry << std::dec
        << " | inside executable segment: " << (result.entry_in_executable_segment ? "yes" : "no")
        << "\nSegments: " << result.segments.size() << '\n';
    for (std::size_t i = 0; i < result.segments.size(); ++i) {
        const auto& s = result.segments[i];
        out << "  [" << i << "] type=0x" << std::hex << s.type << " address=0x" << s.address
            << " offset=0x" << s.offset << std::dec << " file=" << s.file_size << " memory=" << s.memory_size
            << " flags=" << ((s.flags & 4) ? 'R' : '-') << ((s.flags & 2) ? 'W' : '-')
            << ((s.flags & 1) ? 'X' : '-') << '\n';
    }
    out << "Inspection only; general PS4 process execution is not implemented.\n";
    return out.str();
}
} // namespace ps4
