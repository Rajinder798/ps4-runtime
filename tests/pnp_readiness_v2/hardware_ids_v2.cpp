// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
#include "pnp_coverage_v2.h"
#include <algorithm>
#include <optional>
#include <tuple>

namespace pnp_v2 {
const char *Name(Reason r) {
    switch (r) {
    case Reason::None:
        return "none";
    case Reason::PropertyApiFailure:
        return "property_api_failure";
    case Reason::UnexpectedPropertyType:
        return "unexpected_property_type";
    case Reason::InvalidPropertyLength:
        return "invalid_property_length";
    case Reason::InvalidMultiSzTermination:
        return "invalid_multisz_termination";
    case Reason::PropertyLimit:
        return "property_limit";
    case Reason::UnsupportedDocumentedForm:
        return "unsupported_documented_form";
    case Reason::UnrecognizedForm:
        return "unrecognized_form";
    case Reason::InvalidHardwareSyntax:
        return "invalid_hardware_syntax";
    case Reason::MissingHardwareId:
        return "missing_hardware_id";
    case Reason::ConflictingIdentities:
        return "conflicting_identities";
    case Reason::EnumeratorUnavailable:
        return "enumerator_unavailable";
    case Reason::EnumeratorMalformed:
        return "enumerator_malformed";
    case Reason::IdentityBusConflict:
        return "identity_bus_conflict";
    case Reason::ParentUnresolved:
        return "parent_unresolved";
    case Reason::ParentCycle:
        return "parent_cycle";
    case Reason::ParentLimit:
        return "parent_limit";
    case Reason::ResourceLimit:
        return "resource_limit";
    case Reason::InterfaceLookupFailed:
        return "interface_lookup_failed";
    }
    return "unrecognized_form";
}
namespace {
bool Hex(std::wstring_view s, std::size_t n) {
    return s.size() == n && std::all_of(s.begin(), s.end(), [](wchar_t c) {
               return (c >= L'0' && c <= L'9') || (c >= L'A' && c <= L'F');
           });
}
bool Field(std::wstring_view s, std::wstring_view prefix, std::size_t n) {
    return s.starts_with(prefix) && Hex(s.substr(prefix.size()), n);
}
bool Generic(const std::wstring &s) {
    if (s == L"HID_DEVICE" || s == L"USB\\COMPOSITE")
        return true;
    for (auto x : {L"MOUSE", L"GAME", L"KEYBOARD", L"CONTROL", L"CONSUMER"})
        if (s == std::wstring(L"HID_DEVICE_SYSTEM_") + x)
            return true;
    if (s.size() == 25 && s.starts_with(L"HID_DEVICE_UP:") &&
        Hex(std::wstring_view(s).substr(14, 4), 4) && s.substr(18, 3) == L"_U:" &&
        Hex(std::wstring_view(s).substr(21), 4))
        return true;
    if (s.starts_with(L"USB\\CLASS_")) {
        auto v = std::wstring_view(s).substr(4);
        if (v.size() == 8 && Field(v, L"CLASS_", 2))
            return true;
        if ((v.size() == 20 || v.size() == 28) && Field(v.substr(0, 8), L"CLASS_", 2) &&
            v[8] == L'&' && Field(v.substr(9, 11), L"SUBCLASS_", 2) &&
            (v.size() == 20 || (v[20] == L'&' && Field(v.substr(21), L"PROT_", 2))))
            return true;
    }
    return false;
}
} // namespace
Assessment AssessIds(const std::vector<std::wstring> &ids) {
    if (ids.size() > 64)
        return {Hardware::Malformed, Reason::PropertyLimit};
    if (ids.empty())
        return {};
    // All vendor IDs in a MULTI_SZ must describe the same bus, VID/PID and role.
    // Revision-specific and revision-free variants may coexist.
    std::optional<std::tuple<bool, std::wstring, std::wstring, std::wstring, std::wstring>>
        identity;
    std::wstring revision;
    Hardware result = Hardware::Other;
    bool generic = false;
    for (auto s : ids) {
        if (s.empty())
            return {Hardware::Malformed, Reason::InvalidHardwareSyntax};
        if (s.size() > 1023)
            return {Hardware::Malformed, Reason::PropertyLimit};
        for (auto &c : s)
            if (c >= L'a' && c <= L'z')
                c -= 32;
        if (Generic(s)) {
            generic = true;
            continue;
        }
        if (!s.starts_with(L"USB\\VID_") && !s.starts_with(L"HID\\VID_"))
            return {Hardware::Malformed, Reason::UnrecognizedForm};
        const bool hid = s.starts_with(L"HID\\");
        auto rest = std::wstring_view(s).substr(4);
        std::vector<std::wstring_view> p;
        while (true) {
            auto at = rest.find(L'&');
            p.push_back(rest.substr(0, at));
            if (at == rest.npos)
                break;
            rest.remove_prefix(at + 1);
        }
        if (p.size() < 2 || !Field(p[0], L"VID_", 4) || !Field(p[1], L"PID_", 4))
            return {Hardware::Malformed, Reason::InvalidHardwareSyntax};
        std::wstring mi, col, rev;
        std::size_t i = 2;
        if (i < p.size() && Field(p[i], L"REV_", 4))
            rev = p[i++];
        if (i < p.size() && Field(p[i], L"MI_", 2))
            mi = p[i++];
        if (hid && i < p.size() && Field(p[i], L"COL", 2))
            col = p[i++];
        if (i != p.size())
            return {Hardware::Malformed, Reason::InvalidHardwareSyntax};
        auto key = std::make_tuple(hid, std::wstring(p[0]), std::wstring(p[1]), mi, col);
        if ((identity && *identity != key) ||
            (!rev.empty() && !revision.empty() && revision != rev))
            return {Hardware::Malformed, Reason::ConflictingIdentities};
        identity = key;
        if (!rev.empty())
            revision = rev;
        if (p[0] == L"VID_054C" && p[1] == L"PID_0CE6")
            result =
                hid ? Hardware::Hid : (mi.empty() ? Hardware::UsbParent : Hardware::UsbFunction);
    }
    return {result, identity  ? Reason::None
                    : generic ? Reason::UnsupportedDocumentedForm
                              : Reason::MissingHardwareId};
}
Hardware HardwareIds(const std::vector<std::wstring> &ids, bool valid) {
    return valid ? AssessIds(ids).hardware : Hardware::Malformed;
}
Assessment AssessProperty(std::uint32_t code, std::uint32_t type, std::uint32_t bytes,
                          const wchar_t *data, std::size_t capacity) {
    if (code)
        return {Hardware::Missing, Reason::PropertyApiFailure};
    // DEVPROP_TYPE_STRING_LIST = STRING (0x12) | TYPEMOD_LIST (0x2000).
    if (type != 0x2012)
        return {Hardware::Malformed, Reason::UnexpectedPropertyType};
    if (bytes > PropertyBytes)
        return {Hardware::Malformed, Reason::PropertyLimit};
    if (bytes % 2 || !data || bytes / 2 > capacity)
        return {Hardware::Malformed, Reason::InvalidPropertyLength};
    const auto n = bytes / 2; // Windows UTF-16 byte count, including both terminators.
    // A documented empty REG_MULTI_SZ sequence is one NUL, not two strings.
    if (n == 1 && !data[0])
        return {Hardware::Missing, Reason::MissingHardwareId};
    if (n < 2 || data[n - 1] || data[n - 2])
        return {Hardware::Malformed, Reason::InvalidMultiSzTermination};
    std::vector<std::wstring> ids;
    std::size_t at = 0;
    while (at < n && data[at]) {
        std::size_t end = at;
        while (end < n && data[end])
            ++end;
        if (ids.size() == 64 || end - at > 1023)
            return {Hardware::Malformed, Reason::PropertyLimit};
        ids.emplace_back(data + at, end - at);
        at = end + 1;
    }
    if (!std::all_of(data + at, data + n, [](wchar_t c) { return !c; }))
        return {Hardware::Malformed, Reason::InvalidMultiSzTermination};
    return AssessIds(ids);
}
} // namespace pnp_v2
