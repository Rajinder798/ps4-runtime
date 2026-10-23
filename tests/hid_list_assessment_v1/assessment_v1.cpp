// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
#include "assessment_v1.h"
#include <algorithm>
#include <optional>
#include <tuple>
#include <vector>

namespace hid_list_v1 {
namespace {
using Text = std::u16string;
using View = std::u16string_view;
bool Hex(View s, std::size_t width) {
    return s.size() == width && std::all_of(s.begin(), s.end(), [](char16_t c) {
        return (c >= u'0' && c <= u'9') || (c >= u'A' && c <= u'F');
    });
}
bool Field(View s, View prefix, std::size_t width) {
    return s.starts_with(prefix) && Hex(s.substr(prefix.size()), width);
}
Text Upper(View input) {
    Text s(input);
    for (auto &c : s)
        if (c >= u'a' && c <= u'z') c = static_cast<char16_t>(c - u'a' + u'A');
    return s;
}
bool Usage(View s) {
    return s.size() == 14 && s.starts_with(u"UP:") && Hex(s.substr(3, 4), 4) &&
           s.substr(7, 3) == u"_U:" && Hex(s.substr(10), 4);
}
struct Full {
    bool hid = false;
    Text vid, pid, rev, mi, col;
};
std::optional<Full> ParseFull(View s) {
    if (!s.starts_with(u"HID\\") && !s.starts_with(u"USB\\")) return {};
    Full f; f.hid = s.starts_with(u"HID\\");
    s.remove_prefix(4);
    std::vector<View> p;
    while (p.size() < 6) {
        auto at = s.find(u'&'); p.push_back(s.substr(0, at));
        if (at == s.npos) break;
        s.remove_prefix(at + 1);
    }
    if (p.size() < 2 || !Field(p[0], u"VID_", 4) || !Field(p[1], u"PID_", 4)) return {};
    f.vid = p[0]; f.pid = p[1];
    std::size_t i = 2;
    if (i < p.size() && Field(p[i], u"REV_", 4)) f.rev = p[i++];
    if (i < p.size() && Field(p[i], u"MI_", 2)) f.mi = p[i++];
    if (f.hid && i < p.size() && Field(p[i], u"COL", 2)) f.col = p[i++];
    // USB parent REV and interface MI are distinct documented forms in this policy.
    if (i != p.size() || (!f.hid && !f.rev.empty() && !f.mi.empty())) return {};
    return f;
}
Assessment Lists(const std::vector<Text> &ids) {
    Assessment out; out.entries = static_cast<unsigned>(ids.size());
    if (ids.empty()) return out;
    std::optional<Full> identity;
    Text revision, partial_vendor, usage;
    bool partial = false, generic = false, unsupported = false, malformed = false;
    bool unknown = false, conflict = false;
    auto issue = [&](std::size_t i) { if (out.first_issue < 0) out.first_issue = static_cast<int>(i); };
    auto context = [&](std::size_t i) { if (out.first_context < 0) out.first_context = static_cast<int>(i); };
    auto add_usage = [&](View value, std::size_t i) {
        if (!usage.empty() && usage != value) { conflict = true; issue(i); }
        usage = value;
    };
    for (std::size_t i = 0; i < ids.size(); ++i) {
        auto s = Upper(ids[i]);
        if (auto f = ParseFull(s)) {
            if (identity && std::tie(identity->hid, identity->vid, identity->pid, identity->mi, identity->col) !=
                            std::tie(f->hid, f->vid, f->pid, f->mi, f->col)) { conflict = true; issue(i); }
            if (!revision.empty() && !f->rev.empty() && revision != f->rev) { conflict = true; issue(i); }
            if (!f->rev.empty()) revision = f->rev;
            identity = f;
        } else if (s.size() == 27 && s.starts_with(u"HID\\") &&
                   Field(View(s).substr(4, 8), u"VID_", 4) && s[12] == u'&' && Usage(View(s).substr(13))) {
            partial = true; context(i);
            auto vendor = s.substr(4, 8);
            if (!partial_vendor.empty() && partial_vendor != vendor) { conflict = true; issue(i); }
            partial_vendor = vendor; add_usage(View(s).substr(13), i);
        } else if (s == u"HID_DEVICE") {
            generic = true; context(i);
        } else if (s.starts_with(u"HID_DEVICE_") && Usage(View(s).substr(11))) {
            generic = true; context(i); add_usage(View(s).substr(11), i);
        } else if (s.starts_with(u"HID_DEVICE_SYSTEM_") || s.starts_with(u"USB\\CLASS_") || s == u"USB\\COMPOSITE") {
            // Documented but outside this deliberately narrow hardware-list policy.
            unsupported = true; issue(i);
        } else if (s.starts_with(u"HID\\VID_") || s.starts_with(u"USB\\VID_") || s.starts_with(u"HID_DEVICE_UP:")) {
            malformed = true; issue(i);
        } else {
            unknown = true; issue(i);
        }
    }
    if (identity && ((partial && (!identity->hid || identity->vid != partial_vendor)) ||
                     (generic && !identity->hid))) { conflict = true; if (out.first_issue < 0) out.first_issue = out.first_context; }
    if (conflict) out.kind = Kind::Conflict;
    else if (malformed) out.kind = Kind::Malformed;
    else if (unsupported || (unknown && identity)) out.kind = Kind::Unsupported;
    else if (unknown) out.kind = Kind::Unrecognized;
    else if (identity) {
        out.kind = partial || generic ? Kind::CompleteWithContext : Kind::Complete;
        out.identity = identity->vid == u"VID_054C" && identity->pid == u"PID_0CE6"
            ? (identity->hid ? Identity::TargetHid : identity->mi.empty() ? Identity::TargetUsbParent : Identity::TargetUsbFunction)
            : Identity::Other;
    } else out.kind = partial ? Kind::PartialContext : Kind::GenericOnly;
    // A rejected list never retains a usable identity from an otherwise good entry.
    return out;
}
} // namespace

Assessment Assess(const Property &p) {
    auto fail = [](Kind k) { Assessment a; a.kind = k; return a; };
    if (p.code) return fail(Kind::ApiFailure);
    if (p.type != 0x2012) return fail(Kind::InvalidType);
    if (p.bytes > PropertyBytes) return fail(Kind::Limit);
    if (!p.bytes || p.bytes % 2 || p.bytes / 2 > p.data.size()) return fail(Kind::InvalidLength);
    const auto n = p.bytes / 2;
    auto data = p.data.first(n);
    // Validate UTF-16 structurally before grammar; wchar_t size is never involved.
    for (std::size_t i = 0; i < n; ++i) {
        auto x = data[i];
        if (x >= 0xD800 && x <= 0xDBFF) {
            if (++i >= n || data[i] < 0xDC00 || data[i] > 0xDFFF) return fail(Kind::InvalidEncoding);
        } else if (x >= 0xDC00 && x <= 0xDFFF) return fail(Kind::InvalidEncoding);
    }
    if ((n == 1 || n == 2) && std::all_of(data.begin(), data.end(), [](char16_t x) { return x == 0; })) return {};
    if (n < 2 || data[n - 1] || data[n - 2]) return fail(Kind::InvalidTermination);
    std::vector<Text> ids;
    std::size_t at = 0;
    while (at < n - 1) {
        std::size_t end = at;
        while (end < n && data[end]) ++end;
        if (end == at || end >= n - 1) return fail(Kind::InvalidTermination);
        if (ids.size() == EntryCap || end - at > StringCap) return fail(Kind::Limit);
        ids.emplace_back(data.data() + at, end - at); at = end + 1;
    }
    if (at != n - 1) return fail(Kind::InvalidTermination);
    return Lists(ids);
}
const char *Name(Kind k) {
    switch (k) {
    case Kind::Complete: return "complete";
    case Kind::CompleteWithContext: return "complete_with_consistent_context";
    case Kind::PartialContext: return "partial_context_without_product";
    case Kind::GenericOnly: return "generic_only";
    case Kind::Unsupported: return "unsupported";
    case Kind::Conflict: return "conflicting";
    case Kind::Unrecognized: return "unrecognized";
    case Kind::Malformed: return "malformed";
    case Kind::Empty: return "empty";
    case Kind::ApiFailure: return "property_api_failure";
    case Kind::InvalidType: return "invalid_property_type";
    case Kind::InvalidLength: return "invalid_property_length";
    case Kind::InvalidEncoding: return "invalid_utf16";
    case Kind::InvalidTermination: return "invalid_multisz_termination";
    case Kind::Limit: return "property_limit";
    }
    return "unsupported";
}
const char *Name(Identity i) {
    switch (i) {
    case Identity::TargetHid: return "target_hid";
    case Identity::TargetUsbParent: return "target_usb_parent";
    case Identity::TargetUsbFunction: return "target_usb_function";
    case Identity::Other: return "other";
    default: return "none";
    }
}
std::string Json(const Assessment &a) {
    return "{\"schema\":\"hid-list-assessment-v1\",\"origin\":\"HOST TEST\",\"assessment\":\"" +
        std::string(Name(a.kind)) + "\",\"identity\":\"" + Name(a.identity) +
        "\",\"entries\":" + std::to_string(a.entries) + ",\"first_issue\":" + std::to_string(a.first_issue) +
        ",\"first_context\":" + std::to_string(a.first_context) + ",\"own_target_hid\":" +
        (a.OwnTargetHid() ? "true" : "false") + ",\"readiness_granted\":false,\"recovery_accepted\":false}";
}
} // namespace hid_list_v1
