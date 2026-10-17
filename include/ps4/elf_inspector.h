#pragma once

#include <cstdint>
#include <istream>
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

// Structural inspection only. Does not map memory or execute guest instructions.
Inspection inspect_elf(std::istream& input);
std::string to_json(const Inspection& result);
std::string to_text(const Inspection& result);

} // namespace ps4
