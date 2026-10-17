// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
// See LICENSE in the project root for the full license text.

#pragma once

#include "ps4/elf_inspector.h"

#include <cstddef>
#include <memory>
#include <span>

namespace ps4 {

// A bounded, rebased mapping experiment, not a PS4 process loader.
// Only PT_LOAD/PT_NULL and ET_DYN/ET_SCE_DYNEXEC are supported.
class MappedImage {
public:
    explicit MappedImage(std::istream& input);
    ~MappedImage();
    MappedImage(const MappedImage&) = delete;
    MappedImage& operator=(const MappedImage&) = delete;

    const Inspection& inspection() const noexcept;
    std::size_t page_size() const noexcept;
    std::size_t mapped_size() const noexcept;
    // Read a range wholly inside one readable segment; gaps are never exposed.
    std::span<const unsigned char> bytes(std::uint64_t guest_address, std::size_t size) const;
    // Calls only the canonical six-byte return stub after validating the probe.
    int call_probe() const;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

std::string probe_json(const MappedImage& image, int return_value);
std::string probe_text(const MappedImage& image, int return_value);

} // namespace ps4
