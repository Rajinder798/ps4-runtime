// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
// See LICENSE in the project root for the full license text.

#include "ps4/elf_inspector.h"

#include <algorithm>
#include <array>
#include <limits>
#include <map>
#include <optional>
#include <sstream>
#include <string_view>

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

// Inspector limits, not PS4 limits: keep untrusted table reads bounded.
constexpr std::uint64_t max_dynamic_bytes = 1u << 20;
constexpr std::uint64_t max_table_bytes = 16u << 20;
constexpr std::string_view id_codes = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+-";

std::uint64_t little(const std::string& bytes, std::size_t offset, std::size_t count) {
    std::uint64_t value = 0;
    for (std::size_t i = 0; i < count; ++i)
        value |= static_cast<std::uint64_t>(static_cast<unsigned char>(bytes[offset + i])) << (i * 8);
    return value;
}

std::string read_range(std::istream& input, std::uint64_t offset, std::uint64_t size) {
    std::string bytes(static_cast<std::size_t>(size), '\0');
    input.clear();
    input.seekg(static_cast<std::streamoff>(offset), std::ios::beg);
    if (size != 0 && !input.read(bytes.data(), static_cast<std::streamsize>(size)))
        fail("read_failed", "Could not read SCE dynamic metadata.");
    return bytes;
}

// Most significant six-bit group first; 1-3 characters for a 16-bit ID.
std::string encode_id(std::uint16_t id) {
    std::string encoded;
    if (id >= 0x1000) encoded += id_codes[(id >> 12) & 0x3f];
    if (id >= 0x40) encoded += id_codes[(id >> 6) & 0x3f];
    encoded += id_codes[id & 0x3f];
    return encoded;
}

const char* symbol_type_name(std::uint8_t type) {
    switch (type) {
    case 0: return "notype";
    case 1: return "object";
    case 2: return "function";
    case 6: return "tls";
    default: return "other";
    }
}

std::string json_string(const std::string& text) {
    // Inventory strings are already restricted to printable ASCII.
    std::string quoted = "\"";
    for (const char c : text) {
        if (c == '"' || c == '\\') quoted += '\\';
        quoted += c;
    }
    return quoted + '"';
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

namespace {
// Bounded view of PT_DYNAMIC and the PT_SCE_DYNLIBDATA string/symbol tables it names.
struct DynamicMetadata {
    Inspection elf;
    Segment dynlib{};
    std::vector<std::uint64_t> needed, module_values, library_values;
    std::map<std::uint64_t, std::uint64_t> single;
    std::string strings, symbols;
};

// DT_SCE_JMPREL, PLTREL, PLTRELSZ, RELA, RELASZ, RELAENT, STRTAB, STRSZ, SYMTAB, SYMENT and SYMTABSZ.
constexpr std::array<std::uint64_t, 11> singular_tags{0x61000029, 0x6100002b, 0x6100002d, 0x6100002f,
                                                      0x61000031, 0x61000033, 0x61000035, 0x61000037,
                                                      0x61000039, 0x6100003b, 0x6100003f};

// Table offsets are relative to PT_SCE_DYNLIBDATA's file bytes. An optional
// table may omit both tags; declaring only one of them is an error.
std::string read_table(std::istream& input, const DynamicMetadata& meta, std::uint64_t offset_tag,
                       std::uint64_t size_tag, const std::string& name, bool required) {
    const auto offset = meta.single.find(offset_tag);
    const auto size = meta.single.find(size_tag);
    if (!required && offset == meta.single.end() && size == meta.single.end()) return {};
    if (offset == meta.single.end() || size == meta.single.end())
        fail("missing_" + name, "PT_DYNAMIC does not declare the SCE " + name + " offset and size.");
    if (!fits(offset->second, size->second, meta.dynlib.file_size))
        fail(name + "_out_of_bounds", "The SCE " + name + " is outside PT_SCE_DYNLIBDATA.");
    if (size->second > max_table_bytes)
        fail("table_too_large", "The SCE " + name + " exceeds the inspector's 16 MiB limit.");
    return read_range(input, meta.dynlib.offset + offset->second, size->second);
}

DynamicMetadata read_dynamic(std::istream& input) {
    DynamicMetadata meta{inspect_elf(input), {}, {}, {}, {}, {}, {}, {}};
    const Segment* dynamic = nullptr;
    const Segment* dynlib = nullptr;
    for (const auto& segment : meta.elf.segments) {
        const Segment** slot = segment.type == 2 ? &dynamic : segment.type == 0x61000000 ? &dynlib : nullptr;
        if (!slot) continue;
        if (*slot) fail("duplicate_dynamic_segment", "Expected one PT_DYNAMIC and one PT_SCE_DYNLIBDATA segment.");
        *slot = &segment;
    }
    if (!dynamic) fail("missing_dynamic", "Executable has no PT_DYNAMIC segment.");
    if (!dynlib) fail("missing_dynlibdata", "Executable has no PT_SCE_DYNLIBDATA segment.");
    if (dynamic->file_size > max_dynamic_bytes)
        fail("table_too_large", "PT_DYNAMIC exceeds the inspector's 1 MiB limit.");
    meta.dynlib = *dynlib;

    const auto entries = read_range(input, dynamic->offset, dynamic->file_size);
    bool terminated = false;
    for (std::size_t at = 0; at + 16 <= entries.size(); at += 16) {
        const auto tag = little(entries, at, 8);
        const auto value = little(entries, at + 8, 8);
        if (tag == 0) { terminated = true; break; }
        if (tag == 1) meta.needed.push_back(value);                       // DT_NEEDED
        else if (tag == 0x6100000f) meta.module_values.push_back(value);  // DT_SCE_NEEDED_MODULE
        else if (tag == 0x61000015) meta.library_values.push_back(value); // DT_SCE_IMPORT_LIB
        else if (std::find(singular_tags.begin(), singular_tags.end(), tag) != singular_tags.end() &&
                 !meta.single.emplace(tag, value).second)
            fail("duplicate_dynamic_tag", "A singular SCE dynamic tag appears more than once.");
    }
    if (!terminated) fail("missing_dynamic_terminator", "PT_DYNAMIC has no DT_NULL entry.");

    meta.strings = read_table(input, meta, 0x61000035, 0x61000037, "string_table", true);
    meta.symbols = read_table(input, meta, 0x61000039, 0x6100003f, "symbol_table", true);
    const auto entry_size = meta.single.find(0x6100003b);
    if ((entry_size != meta.single.end() && entry_size->second != 24) || meta.symbols.size() % 24 != 0)
        fail("bad_symbol_entry_size", "SCE symbol entries must be 24 bytes.");
    return meta;
}

std::string name_at(const std::string& strings, std::uint64_t offset) {
    if (offset >= strings.size())
        fail("string_out_of_bounds", "A name offset is outside the SCE string table.");
    const auto end = strings.find('\0', static_cast<std::size_t>(offset));
    if (end == std::string::npos) fail("unterminated_string", "An SCE name is not NUL-terminated.");
    auto text = strings.substr(static_cast<std::size_t>(offset), end - static_cast<std::size_t>(offset));
    for (const char c : text)
        if (c < 0x20 || c > 0x7e) fail("bad_string", "SCE names must be printable ASCII.");
    return text;
}

const char* relocation_type_name(std::uint32_t type) {
    switch (type) {
    case 0: return "R_X86_64_NONE";
    case 1: return "R_X86_64_64";
    case 2: return "R_X86_64_PC32";
    case 6: return "R_X86_64_GLOB_DAT";
    case 7: return "R_X86_64_JUMP_SLOT";
    case 8: return "R_X86_64_RELATIVE";
    case 10: return "R_X86_64_32";
    case 11: return "R_X86_64_32S";
    case 16: return "R_X86_64_DTPMOD64";
    case 17: return "R_X86_64_DTPOFF64";
    case 18: return "R_X86_64_TPOFF64";
    default: return "unknown";
    }
}

// Bytes written at the target; unknown types are only required to start inside a segment.
std::uint64_t relocation_width(std::uint32_t type) {
    if (type == 2 || type == 10 || type == 11) return 4;
    return std::string_view(relocation_type_name(type)) == "unknown" ? 1 : 8;
}
} // namespace

ImportInventory inspect_imports(std::istream& input) {
    const auto meta = read_dynamic(input);
    const auto& elf = meta.elf;
    const auto& symbols = meta.symbols;
    const auto& needed = meta.needed;
    const auto& module_values = meta.module_values;
    const auto& library_values = meta.library_values;
    const auto string_at = [&](std::uint64_t offset) { return name_at(meta.strings, offset); };

    ImportInventory result{elf.file_size, elf.type, 0, {}, {}, {}, {}, {}};
    for (const auto value : needed) result.needed.push_back(string_at(value));
    std::map<std::string, std::string> module_names, library_names;
    for (const auto value : module_values) {
        // name offset:32, minor:8, major:8, id:16
        const auto id = static_cast<std::uint16_t>(value >> 48);
        result.modules.push_back({string_at(value & 0xffffffff), encode_id(id), id,
                                  static_cast<std::uint8_t>(value >> 40), static_cast<std::uint8_t>(value >> 32)});
        if (!module_names.emplace(result.modules.back().encoded_id, result.modules.back().name).second)
            fail("duplicate_module_id", "Two needed SCE modules use the same ID.");
    }
    for (const auto value : library_values) {
        // name offset:32, version:16, id:16
        const auto id = static_cast<std::uint16_t>(value >> 48);
        result.libraries.push_back({string_at(value & 0xffffffff), encode_id(id), id,
                                    static_cast<std::uint16_t>(value >> 32)});
        if (!library_names.emplace(result.libraries.back().encoded_id, result.libraries.back().name).second)
            fail("duplicate_library_id", "Two imported SCE libraries use the same ID.");
    }

    for (std::size_t at = 0; at < symbols.size(); at += 24) {
        ++result.symbol_entries;
        const auto info = static_cast<std::uint8_t>(symbols[at + 4]);
        const auto bind = static_cast<std::uint8_t>(info >> 4);
        // Imports are undefined (zero-valued) global or weak symbols.
        if (little(symbols, at + 8, 8) != 0 || (bind != 1 && bind != 2)) continue;
        const auto name = string_at(little(symbols, at, 4));
        const auto first = name.find('#');
        const auto second = first == std::string::npos ? first : name.find('#', first + 1);
        if (second == std::string::npos || name.find('#', second + 1) != std::string::npos) {
            result.other_undefined.push_back(name);
            continue;
        }
        const auto nid = name.substr(0, first);
        if (nid.empty() || nid.find_first_not_of(id_codes) != std::string::npos)
            fail("bad_nid", "An SCE import has an empty or malformed NID.");
        const auto library = library_names.find(name.substr(first + 1, second - first - 1));
        if (library == library_names.end())
            fail("unknown_library_id", "An SCE import names an undeclared library ID.");
        const auto module = module_names.find(name.substr(second + 1));
        if (module == module_names.end())
            fail("unknown_module_id", "An SCE import names an undeclared module ID.");
        result.imports.push_back({nid, library->second, module->second,
                                  static_cast<std::uint8_t>(info & 0xf), bind});
    }
    return result;
}

std::string to_json(const ImportInventory& result) {
    std::ostringstream out;
    out << "{\"schema_version\":1,\"operation\":\"imports\",\"format\":\"ELF64\",\"type\":\""
        << type_name(result.type) << "\",\"type_id\":" << result.type << ",\"file_size\":" << result.file_size
        << ",\"needed\":[";
    for (std::size_t i = 0; i < result.needed.size(); ++i)
        out << (i ? "," : "") << json_string(result.needed[i]);
    out << "],\"modules\":[";
    for (std::size_t i = 0; i < result.modules.size(); ++i) {
        const auto& m = result.modules[i];
        out << (i ? "," : "") << "{\"name\":" << json_string(m.name) << ",\"id\":" << m.id
            << ",\"encoded_id\":" << json_string(m.encoded_id) << ",\"version_major\":"
            << static_cast<unsigned>(m.version_major) << ",\"version_minor\":"
            << static_cast<unsigned>(m.version_minor) << '}';
    }
    out << "],\"libraries\":[";
    for (std::size_t i = 0; i < result.libraries.size(); ++i) {
        const auto& l = result.libraries[i];
        out << (i ? "," : "") << "{\"name\":" << json_string(l.name) << ",\"id\":" << l.id
            << ",\"encoded_id\":" << json_string(l.encoded_id) << ",\"version\":" << l.version << '}';
    }
    out << "],\"symbol_entries\":" << result.symbol_entries << ",\"imports\":[";
    for (std::size_t i = 0; i < result.imports.size(); ++i) {
        const auto& s = result.imports[i];
        out << (i ? "," : "") << "{\"nid\":" << json_string(s.nid) << ",\"library\":" << json_string(s.library)
            << ",\"module\":" << json_string(s.module) << ",\"type\":\"" << symbol_type_name(s.type)
            << "\",\"bind\":\"" << (s.bind == 2 ? "weak" : "global") << "\"}";
    }
    out << "],\"other_undefined\":[";
    for (std::size_t i = 0; i < result.other_undefined.size(); ++i)
        out << (i ? "," : "") << json_string(result.other_undefined[i]);
    out << "],\"resolution_performed\":false,\"execution_supported\":false}\n";
    return out.str();
}

std::string to_text(const ImportInventory& result) {
    std::ostringstream out;
    out << "SCE import inventory | " << type_name(result.type) << "\nNeeded files:";
    for (const auto& name : result.needed) out << ' ' << name;
    out << (result.needed.empty() ? " none" : "") << "\nModules: " << result.modules.size() << '\n';
    for (const auto& m : result.modules)
        out << "  " << m.name << " id=" << m.id << " (" << m.encoded_id << ") version "
            << static_cast<unsigned>(m.version_major) << '.' << static_cast<unsigned>(m.version_minor) << '\n';
    out << "Libraries: " << result.libraries.size() << '\n';
    for (const auto& l : result.libraries)
        out << "  " << l.name << " id=" << l.id << " (" << l.encoded_id << ") version " << l.version << '\n';
    out << "Imports: " << result.imports.size() << " of " << result.symbol_entries << " symbol entries\n";
    for (const auto& s : result.imports)
        out << "  " << s.nid << ' ' << s.library << ' ' << s.module << ' ' << symbol_type_name(s.type)
            << (s.bind == 2 ? " weak" : "") << '\n';
    if (!result.other_undefined.empty()) {
        out << "Other undefined symbols: " << result.other_undefined.size() << '\n';
        for (const auto& name : result.other_undefined) out << "  " << name << '\n';
    }
    out << "Declared imports only; nothing was resolved, relocated or executed.\n";
    return out.str();
}

RelocationInventory inspect_relocations(std::istream& input) {
    const auto meta = read_dynamic(input);
    const auto plt_format = meta.single.find(0x6100002b);
    if (plt_format != meta.single.end() && plt_format->second != 7)
        fail("unsupported_plt_relocation_format", "DT_SCE_PLTREL must declare DT_RELA entries.");
    const auto entry_size = meta.single.find(0x61000033);
    RelocationInventory result{meta.elf.file_size, meta.elf.type, meta.symbols.size() / 24, {}};
    const std::array<std::pair<const char*, std::string>, 2> tables{{
        {"rela", read_table(input, meta, 0x6100002f, 0x61000031, "relocation_table", false)},
        {"jmprel", read_table(input, meta, 0x61000029, 0x6100002d, "plt_relocation_table", false)}}};
    for (const auto& [name, bytes] : tables) {
        if ((entry_size != meta.single.end() && entry_size->second != 24) || bytes.size() % 24 != 0)
            fail("bad_relocation_entry_size", "SCE relocation entries must be 24 bytes.");
        for (std::size_t at = 0; at < bytes.size(); at += 24) {
            const auto offset = little(bytes, at, 8);
            const auto info = little(bytes, at + 8, 8);
            const auto type = static_cast<std::uint32_t>(info & 0xffffffff);
            const auto index = static_cast<std::uint32_t>(info >> 32);
            if (index >= result.symbol_entries)
                fail("symbol_index_out_of_bounds", "A relocation names a symbol outside the SCE symbol table.");
            Relocation relocation{name, index == 0 ? std::string{} :
                                  name_at(meta.strings, little(meta.symbols, static_cast<std::size_t>(index) * 24, 4)),
                                  offset, static_cast<std::int64_t>(little(bytes, at + 16, 8)), type, index, {}};
            // Offsets are guest addresses relative to the module base; the whole write must fit one segment.
            const auto width = relocation_width(type);
            for (std::size_t i = 0; type != 0 && i < meta.elf.segments.size() && !relocation.segment; ++i) {
                const auto& s = meta.elf.segments[i];
                if ((s.type == 1 || s.type == 0x61000010) && offset >= s.address &&
                    offset - s.address < s.memory_size && width <= s.memory_size - (offset - s.address))
                    relocation.segment = i;
            }
            if (type != 0 && !relocation.segment)
                fail("relocation_target_out_of_bounds", "A relocation target is outside every loadable segment.");
            result.relocations.push_back(std::move(relocation));
        }
    }
    return result;
}

std::string to_json(const RelocationInventory& result) {
    std::uint64_t rela = 0;
    for (const auto& r : result.relocations) rela += r.table == "rela";
    std::ostringstream out;
    out << "{\"schema_version\":1,\"operation\":\"relocations\",\"format\":\"ELF64\",\"type\":\""
        << type_name(result.type) << "\",\"type_id\":" << result.type << ",\"file_size\":" << result.file_size
        << ",\"symbol_entries\":" << result.symbol_entries << ",\"tables\":[{\"name\":\"rela\",\"entries\":" << rela
        << "},{\"name\":\"jmprel\",\"entries\":" << result.relocations.size() - rela << "}],\"relocations\":[";
    for (std::size_t i = 0; i < result.relocations.size(); ++i) {
        const auto& r = result.relocations[i];
        out << (i ? "," : "") << "{\"table\":\"" << r.table << "\",\"offset\":" << r.offset << ",\"type\":\""
            << relocation_type_name(r.type) << "\",\"type_id\":" << r.type << ",\"symbol_index\":" << r.symbol_index
            << ",\"symbol\":" << json_string(r.symbol) << ",\"addend\":" << r.addend << ",\"segment\":";
        if (r.segment) out << *r.segment; else out << "null";
        out << '}';
    }
    out << "],\"relocation_performed\":false,\"execution_supported\":false}\n";
    return out.str();
}

std::string to_text(const RelocationInventory& result) {
    std::map<std::uint32_t, std::uint64_t> types;
    std::uint64_t rela = 0, with_symbol = 0;
    for (const auto& r : result.relocations) {
        ++types[r.type];
        rela += r.table == "rela";
        with_symbol += r.symbol_index != 0;
    }
    std::ostringstream out;
    out << "SCE relocation inventory | " << type_name(result.type) << "\nTables: rela=" << rela
        << " jmprel=" << result.relocations.size() - rela << "\nTypes:\n";
    for (const auto& [type, count] : types)
        out << "  " << relocation_type_name(type) << " (" << type << "): " << count << '\n';
    out << "Symbol-referencing relocations: " << with_symbol << " of " << result.relocations.size()
        << "\nUse --json for every entry. Declared relocations only; nothing was applied, resolved or executed.\n";
    return out.str();
}
} // namespace ps4
