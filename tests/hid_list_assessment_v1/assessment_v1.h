// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once
#include <cstdint>
#include <span>
#include <string>

// Offline candidate policy only. No Windows provider or live readiness consumer.
namespace hid_list_v1 {
constexpr unsigned PropertyBytes = 16384, EntryCap = 64, StringCap = 1023;
enum class Kind {
    Complete, CompleteWithContext, PartialContext, GenericOnly, Unsupported,
    Conflict, Unrecognized, Malformed, Empty, ApiFailure, InvalidType,
    InvalidLength, InvalidEncoding, InvalidTermination, Limit
};
enum class Identity { None, TargetHid, TargetUsbParent, TargetUsbFunction, Other };
struct Property {
    std::uint32_t code = 0, type = 0x2012, bytes = 0;
    std::span<const char16_t> data; // explicit UTF-16 code units on both host platforms
};
struct Assessment {
    Kind kind = Kind::Empty;
    Identity identity = Identity::None;
    unsigned entries = 0;
    int first_issue = -1, first_context = -1;
    bool OwnTargetHid() const {
        return identity == Identity::TargetHid &&
               (kind == Kind::Complete || kind == Kind::CompleteWithContext);
    }
};
Assessment Assess(const Property &);
const char *Name(Kind);
const char *Name(Identity);
// Fixed categories/counts only; no raw strings, identity values or fingerprints.
std::string Json(const Assessment &);
} // namespace hid_list_v1
