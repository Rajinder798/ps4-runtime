// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
// See LICENSE in the project root for the full license text.

#pragma once

#include <cstdint>
#include <istream>
#include <optional>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace ps4 {

class InspectionError : public std::runtime_error {
public:
    InspectionError(std::string code, const std::string& message)
        : std::runtime_error(message), code_(std::move(code)) {}
    const std::string& code() const noexcept { return code_; }
private:
    std::string code_;
};

struct Segment {
    std::uint32_t type, flags;
    std::uint64_t offset, address, file_size, memory_size, alignment;
};

struct Inspection {
    std::uint64_t file_size, entry;
    std::uint16_t type;
    std::uint8_t os_abi, abi_version;
    bool entry_in_executable_segment = false;
    std::vector<Segment> segments;
};

struct ImportModule {
    std::string name, encoded_id;
    std::uint16_t id;
    std::uint8_t version_major, version_minor;
};

struct ImportLibrary {
    std::string name, encoded_id;
    std::uint16_t id, version;
};

struct ImportSymbol {
    std::string nid, library, module;
    std::uint8_t type, bind;
};

struct ImportInventory {
    std::uint64_t file_size;
    std::uint16_t type;
    std::uint64_t symbol_entries = 0;
    std::vector<std::string> needed;
    std::vector<ImportModule> modules;
    std::vector<ImportLibrary> libraries;
    std::vector<ImportSymbol> imports;
    std::vector<std::string> other_undefined; // undefined global/weak names without SCE IDs
};

struct Relocation {
    std::string table, symbol; // table is "rela" or "jmprel"; symbol is empty for index 0
    std::uint64_t offset;
    std::int64_t addend;
    std::uint32_t type, symbol_index;
    std::optional<std::size_t> segment; // containing PT_LOAD/PT_SCE_RELRO; none for R_X86_64_NONE
};

struct RelocationInventory {
    std::uint64_t file_size;
    std::uint16_t type;
    std::uint64_t symbol_entries = 0;
    std::vector<Relocation> relocations;
};

struct TlsTemplate {
    std::size_t segment;
    std::uint64_t address, init_size, memory_size, alignment, aligned_size;
    std::optional<std::size_t> init_segment; // file-backed segment holding a nonempty init image
};

struct ProcessParam {
    std::size_t segment, load_segment;
    std::uint64_t address, size, sdk_version;
    std::uint32_t magic, entry_count;
};

struct StartupMetadata {
    std::uint64_t file_size;
    std::uint16_t type;
    std::optional<TlsTemplate> tls;
    std::optional<ProcessParam> process_param;
    bool relocations_checked = false;
    std::uint64_t dtpmod64 = 0, dtpoff64 = 0, tpoff64 = 0;
};

// Structural inspection only. Does not map memory or execute guest instructions.
Inspection inspect_elf(std::istream& input);
std::string to_json(const Inspection& result);
std::string to_text(const Inspection& result);

// Reads declared SCE import metadata only. Nothing is resolved, relocated,
// mapped or executed; a listed import is not evidence that it is implemented.
ImportInventory inspect_imports(std::istream& input);
std::string to_json(const ImportInventory& result);
std::string to_text(const ImportInventory& result);

// Reads declared SCE relocations only. Nothing is applied, resolved or executed;
// each target is checked to lie inside a loadable segment of the guest image.
RelocationInventory inspect_relocations(std::istream& input);
std::string to_json(const RelocationInventory& result);
std::string to_text(const RelocationInventory& result);

// Reads the TLS template, TLS relocation counts and process-parameter header.
// No TLS block is allocated, no module ID is assigned and nothing is executed.
StartupMetadata inspect_startup(std::istream& input);
std::string to_json(const StartupMetadata& result);
std::string to_text(const StartupMetadata& result);

} // namespace ps4
