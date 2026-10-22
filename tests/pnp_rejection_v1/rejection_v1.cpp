// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
#include "rejection_v1.h"
#include <algorithm>
#include <cstdio>
#include <stdexcept>
#include <tuple>
#ifdef _WIN32
#define NOMINMAX
#include <windows.h>
#endif

namespace rejection_v1 {
namespace {
std::string N(std::string_view k, std::int64_t v) {
    return ",\"" + std::string(k) + "\":" + std::to_string(v);
}
std::string S(std::string_view k, std::string_view v) {
    return ",\"" + std::string(k) + "\":\"" + std::string(v) + "\"";
}
std::string B(std::string_view k, bool v) {
    return ",\"" + std::string(k) + "\":" + (v ? "true" : "false");
}
std::wstring Upper(std::wstring s) {
    for (auto &c : s)
        if (c >= L'a' && c <= L'z')
            c -= 32;
    return s;
}
bool Field(std::wstring_view s, std::wstring_view prefix, unsigned width) {
    return s.starts_with(prefix) && s.size() == prefix.size() + width &&
           std::all_of(
               s.begin() + static_cast<std::ptrdiff_t>(prefix.size()), s.end(),
               [](wchar_t c) { return (c >= L'0' && c <= L'9') || (c >= L'A' && c <= L'F'); });
}
std::vector<std::wstring> Parts(std::wstring_view s) {
    std::vector<std::wstring> p;
    while (p.size() < 64) {
        auto at = s.find(L'&');
        p.emplace_back(s.substr(0, at));
        if (at == s.npos)
            break;
        s.remove_prefix(at + 1);
    }
    return p;
}
bool Partial(const std::wstring &s) {
    return s.size() == 27 && s.starts_with(L"HID\\") &&
           Field(std::wstring_view(s).substr(4, 8), L"VID_", 4) && s[12] == L'&' &&
           Field(std::wstring_view(s).substr(13, 7), L"UP:", 4) && s.substr(20, 3) == L"_U:" &&
           Field(std::wstring_view(s).substr(23), L"", 4);
}
std::string Order(const std::vector<std::wstring> &p) {
    std::string out;
    if (p.size() > 5)
        return "other";
    for (const auto &x : p) {
        auto t = x.starts_with(L"VID_")   ? "vid"
                 : x.starts_with(L"PID_") ? "pid"
                 : x.starts_with(L"REV_") ? "rev"
                 : x.starts_with(L"MI_")  ? "mi"
                 : x.starts_with(L"COL")  ? "col"
                 : x.starts_with(L"UP:")  ? "usage"
                                          : "other";
        if (!out.empty())
            out += '_';
        out += t;
    }
    static const std::set<std::string> known = {
        "vid_pid",         "vid_pid_rev",    "vid_pid_mi",         "vid_pid_col", "vid_pid_rev_mi",
        "vid_pid_rev_col", "vid_pid_mi_col", "vid_pid_rev_mi_col", "vid_usage"};
    return known.contains(out) ? out : "other";
}
std::string Length(std::uint32_t n) {
    return n == 0               ? "zero"
           : n <= 4             ? "empty_size"
           : n <= 128           ? "small"
           : n <= 1024          ? "medium"
           : n <= PropertyBytes ? "bounded"
                                : "over_cap";
}
bool String(const Property &p, std::wstring &s) {
    if (p.code || p.type != 0x12 || p.bytes < 2 || p.bytes > PropertyBytes || p.bytes % 2 ||
        p.bytes / 2 > p.data.size())
        return false;
    const auto n = p.bytes / 2;
    if (p.data[n - 1] ||
        std::find(p.data.begin(), p.data.begin() + n - 1, L'\0') != p.data.begin() + n - 1)
        return false;
    s.assign(p.data.data(), n - 1);
    return true;
}
std::string ShapeFields(const Shape &s) {
    return N("property_code", s.code) + S("code_domain", "configret") + N("property_type", s.type) +
           S("byte_length_class", s.length) + N("strings", s.strings) +
           B("count_known", s.count_known) + S("decoding", s.decoding) +
           N("first_rejected_entry", s.first) + S("shape", s.shape) +
           S("component_order", s.order) + S("list_relationship", s.relationship) +
           S("complete_pair", s.pair) + B("has_complete_pair", s.complete_pair) +
           S("original_property_reason", Name(s.original));
}
} // namespace

Shape Inspect(const Property &p) {
    Shape out;
    out.code = p.code;
    out.type = p.type;
    out.length = Length(p.bytes);
    auto a = AssessProperty(p.code, p.type, p.bytes, p.data.empty() ? nullptr : p.data.data(),
                            p.data.size());
    out.original = a.reason;
    if (p.code) {
        out.decoding = "api_failure";
        return out;
    }
    if (p.type != 0x2012) {
        out.decoding = "unexpected_type";
        return out;
    }
    if (p.bytes > PropertyBytes) {
        out.decoding = "limit";
        return out;
    }
    if (p.bytes % 2 || p.bytes / 2 > p.data.size() || p.data.empty()) {
        out.decoding = "invalid_length";
        return out;
    }
    std::vector<std::wstring> ids;
    if (!DecodeMultiSz(p.data.data(), p.bytes / 2, ids)) {
        out.decoding = (a.reason == Reason::PropertyLimit) ? "limit" : "invalid_termination";
        return out;
    }
    out.count_known = true;
    out.strings = static_cast<unsigned>(ids.size());
    out.decoding = "valid";
    if (ids.empty()) {
        out.relationship = "empty";
        return out;
    }
    std::optional<std::tuple<bool, std::wstring, std::wstring, std::wstring, std::wstring>>
        identity;
    std::wstring revision, full_vid;
    std::vector<std::wstring> partial_vids;
    bool generic = false, unsupported = false, invalid = false, conflict = false;
    bool saw_target = false, saw_other = false;
    for (unsigned i = 0; i < ids.size(); ++i) {
        auto s = Upper(ids[i]);
        auto single = AssessIds({s});
        auto parts = Parts(s.size() >= 4 ? std::wstring_view(s).substr(4) : std::wstring_view(s));
        bool full = (s.starts_with(L"USB\\") || s.starts_with(L"HID\\")) && parts.size() >= 2 &&
                    Field(parts[0], L"VID_", 4) && Field(parts[1], L"PID_", 4) &&
                    single.reason == Reason::None;
        bool partial = Partial(s);
        bool entry_conflict = false;
        if (full) {
            out.complete_pair = true;
            bool t = parts[0] == L"VID_054C" && parts[1] == L"PID_0CE6";
            saw_target |= t;
            saw_other |= !t;
            std::wstring mi, col, rev;
            for (const auto &v : parts) {
                if (v.starts_with(L"MI_"))
                    mi = v;
                if (v.starts_with(L"COL"))
                    col = v;
                if (v.starts_with(L"REV_"))
                    rev = v;
            }
            auto key = std::make_tuple(s.starts_with(L"HID\\"), parts[0], parts[1], mi, col);
            entry_conflict = (identity && *identity != key) ||
                             (!rev.empty() && !revision.empty() && rev != revision);
            conflict |= entry_conflict;
            identity = key;
            full_vid = parts[0];
            if (!rev.empty())
                revision = rev;
        } else if (partial)
            partial_vids.push_back(s.substr(4, 8));
        else if (single.reason == Reason::UnsupportedDocumentedForm)
            generic = true;
        else if (single.reason == Reason::UnrecognizedForm)
            unsupported = true;
        else
            invalid = true;
        if (out.first < 0 &&
            (entry_conflict || (single.reason != Reason::None &&
                                single.reason != Reason::UnsupportedDocumentedForm))) {
            out.first = static_cast<int>(i);
            out.shape = partial                                     ? "documented_vendor_usage"
                        : full                                      ? "full_vendor"
                        : single.reason == Reason::UnrecognizedForm ? "unrecognized"
                                                                    : "invalid_component";
            out.order = Order(parts);
        }
    }
    out.pair = saw_target ? (saw_other ? "mixed" : "target") : (saw_other ? "other" : "none");
    for (const auto &v : partial_vids)
        if (!full_vid.empty() && v != full_vid)
            conflict = true;
    if (!partial_vids.empty() && identity && !std::get<0>(*identity))
        conflict = true; // HID usage context cannot describe a USB hardware-ID list.
    out.relationship = conflict      ? "conflicting"
                       : unsupported ? "unsupported"
                       : invalid     ? "invalid_syntax"
                       : !partial_vids.empty()
                           ? (out.complete_pair ? "full_with_partial_context" : "partial_only")
                       : out.complete_pair ? "full_consistent"
                       : generic           ? "generic_only"
                                           : "unsupported";
    return out;
}

void Acquisition::Reset() { facts.clear(); }
const Fact &Acquisition::Read(Id id) {
    if (auto i = facts.find(id); i != facts.end())
        return i->second;
    if (facts.size() == CacheCap) {
        limited = Fact{};
        limited.node.id = id;
        limited.node.resource_limited = true;
        return limited;
    }
    auto raw = source.Read(id);
    // An adversarial/faulty source must not retain an unbounded property.
    for (auto *p : {&raw.enumerator, &raw.hardware, &raw.compatible})
        if (p->data.size() > PropertyBytes / 2) {
            p->data.resize(PropertyBytes / 2);
            p->bytes = PropertyBytes + 2;
        }
    Fact f;
    auto &n = f.node;
    n.id = id;
    n.enum_code = raw.enumerator.code;
    std::wstring e;
    n.enumerator_valid = String(raw.enumerator, e) && !e.empty();
    f.enumerator_shape.code = raw.enumerator.code;
    f.enumerator_shape.type = raw.enumerator.type;
    f.enumerator_shape.length = Length(raw.enumerator.bytes);
    f.enumerator_shape.decoding = n.enumerator_valid                  ? "valid_string"
                                  : raw.enumerator.code == NotQueried ? "not_queried"
                                  : raw.enumerator.code               ? "api_failure"
                                                                      : "invalid_string";
    f.enumerator_shape.original = raw.enumerator.code  ? Reason::EnumeratorUnavailable
                                  : n.enumerator_valid ? Reason::None
                                                       : Reason::EnumeratorMalformed;
    if (n.enumerator_valid) {
        e = Upper(e);
        n.bus = e == L"USB" ? Bus::Usb : e == L"HID" ? Bus::Hid : Bus::Other;
    }
    f.links.parent = raw.parent;
    f.links.parent_code = raw.parent_code;
    f.links.status_code = raw.status_code;
    f.links.status = raw.status;
    f.links.problem = raw.problem;
    if (n.bus == Bus::Usb || n.bus == Bus::Hid) {
        f.shape = Inspect(raw.hardware);
        n.hw_code = raw.hardware.code;
        n.hardware_type = raw.hardware.type;
        n.hardware_bytes = raw.hardware.bytes;
        auto a = AssessProperty(raw.hardware.code, raw.hardware.type, raw.hardware.bytes,
                                raw.hardware.data.empty() ? nullptr : raw.hardware.data.data(),
                                raw.hardware.data.size());
        n.hardware = a.hardware;
        n.hardware_reason = a.reason;
        n.hardware_valid =
            a.reason == Reason::None || a.reason == Reason::UnsupportedDocumentedForm;
        n.compatible_code = raw.compatible.code;
        std::vector<std::wstring> ids;
        n.compatible_valid =
            !raw.compatible.code && raw.compatible.type == 0x2012 &&
            raw.compatible.bytes <= PropertyBytes && raw.compatible.bytes % 2 == 0 &&
            raw.compatible.bytes / 2 <= raw.compatible.data.size() &&
            DecodeMultiSz(raw.compatible.data.data(), raw.compatible.bytes / 2, ids);
        if (n.compatible_valid)
            for (const auto &s : ids)
                n.composite |= Upper(s) == L"USB\\COMPOSITE";
        n.parent = raw.parent;
        n.parent_code = raw.parent_code;
        n.status_code = raw.status_code;
        n.status = raw.status;
        n.problem = raw.problem;
    }
    // Only fixed shape metadata and links survive acquisition; no raw strings cached.
    return facts.emplace(id, std::move(f)).first->second;
}
Enumeration Acquisition::Devnodes() { return source.Devnodes(); }
Enumeration Acquisition::Interfaces(Bus b) { return source.Interfaces(b); }
Lookup Acquisition::InterfaceNode(std::wstring_view, Bus) {
    Lookup l;
    l.code = NotQueried;
    return l;
}
Node Acquisition::Properties(Id id) { return Read(id).node; }
Key Acquisition::InstanceKey(Id id) { return source.InstanceKey(id); }

Writer::Writer(const std::filesystem::path &path, bool host, unsigned c, unsigned rc,
               unsigned fault)
    : cap(c), row_cap(rc), fault_after(fault) {
    if (c < 4096 || c > ByteCap || rc < 8 || rc > RowCap || (!host && fault))
        throw std::runtime_error("Invalid diagnostic budget");
#ifdef _WIN32
    file = CreateFileW(path.c_str(), GENERIC_WRITE, FILE_SHARE_READ, nullptr, CREATE_NEW,
                       FILE_ATTRIBUTE_NORMAL, nullptr);
    if (file == INVALID_HANDLE_VALUE)
        file = nullptr;
#else
    file = std::fopen(path.c_str(), "wbx");
#endif
    if (!file)
        throw std::runtime_error("Cannot create fresh companion evidence");
    Append("header", S("origin", host ? "host-test" : "live") + N("frequency", Frequency()) +
                         N("byte_cap", c) + N("row_cap", rc) + N("detail_cap", DetailCap) +
                         N("token_cap", RelationshipCap) + N("entry_cap", EntryCap) +
                         N("depth_cap", ParentCap) + N("diagnostic_ms", DiagnosticMs) +
                         N("scan_ms", ScanBudgetMs) + N("raw_notification_cap", 0));
}
Writer::~Writer() {
    if (!file)
        return;
#ifdef _WIN32
    CloseHandle(file);
#else
    std::fclose(static_cast<FILE *>(file));
#endif
}
bool Writer::Append(std::string_view event, const std::string &fields, bool reserve) {
    if (broken || finished)
        return false;
    if (fault_after && rows >= fault_after) {
        broken = true;
        return false;
    }
    const auto tick = Ticks();
    if (tick < last) {
        broken = true;
        return false;
    }
    std::string line = "{\"schema\":\"pnp-rejection-v1\",\"sequence\":" + std::to_string(rows) +
                       ",\"qpc\":" + std::to_string(tick) + ",\"event\":\"" + std::string(event) +
                       "\"" + fields + "}\n";
    if (line.size() > cap - bytes || rows >= row_cap) {
        broken = true;
        return false;
    }
    if (!reserve && (line.size() + 2048 > cap - bytes || rows + 4 >= row_cap)) {
        Fail("evidence_limit");
        return false;
    }
    bool okay = false;
#ifdef _WIN32
    DWORD written = 0;
    okay = WriteFile(file, line.data(), static_cast<DWORD>(line.size()), &written, nullptr) &&
           written == line.size();
    if (reserve)
        okay = okay && FlushFileBuffers(file);
#else
    auto *f = static_cast<FILE *>(file);
    okay = std::fwrite(line.data(), 1, line.size(), f) == line.size();
    if (reserve)
        okay = okay && std::fflush(f) == 0;
#endif
    if (!okay) {
        broken = true;
        return false;
    }
    bytes += line.size();
    ++rows;
    last = tick;
    return true;
}
void Writer::Fail(std::string_view reason) {
    if (failed || broken)
        return;
    failed = true;
    Append("first_failure", S("reason", reason), true);
}
void Writer::Finish(unsigned original, bool cleanup) {
    Append("cleanup", N("original_first_failure", original) + B("original_cleanup_ok", cleanup),
           true);
    Append("summary",
           B("writer_ok", !broken) + B("diagnostic_failure", failed) +
               B("recovery_accepted", false),
           true);
    finished = true;
}

unsigned Companion::Token(Id id) {
    if (!id)
        return 0;
    if (auto i = tokens.find(id); i != tokens.end())
        return i->second;
    if (tokens.size() == RelationshipCap) {
        details_complete = false;
        writer.Fail("token_limit");
        return 0;
    }
    auto t = static_cast<unsigned>(tokens.size() + 1);
    tokens[id] = t;
    return t;
}
Enumeration Companion::Devnodes() {
    begin = Ticks();
    diagnostic_deadline = begin + Frequency() * DiagnosticMs / 1000;
    ++sample;
    details = omitted = total = target = other = unknown = inactive = hid_own = node_unknown =
        interface_unknown = 0;
    contexts = context_unknown = 0;
    details_complete = true;
    present.clear();
    targets.clear();
    tokens.clear();
    reasons.clear();
    acquisition.Reset();
    auto e = acquisition.Devnodes();
    if (e.nodes.size() > NodeCap) {
        e.nodes.resize(NodeCap);
        e.limit_hit = true;
        e.complete = false;
    }
    present.insert(e.nodes.begin(), e.nodes.end());
    present_complete = e.complete && !e.code && !e.cleanup_code && !e.limit_hit;
    tree_root = acquisition.TreeRoot();
    // Roots come only from unchanged own-ID assessment, successful state and PRESENT.
    for (auto id : e.nodes) {
        auto n = acquisition.Properties(id);
        if (n.bus == Bus::Usb && n.hardware == Hardware::UsbParent && !n.hw_code &&
            n.hardware_valid && n.enumerator_valid && !n.enum_code && !n.status_code &&
            (n.status & 8U) && !(n.status & 0x400U))
            targets.insert(id);
    }
    writer.Append("snapshot_begin", N("sample", sample) + N("begin", begin) +
                                        B("present_set_complete", present_complete) +
                                        N("target_roots", targets.size()));
    for (auto id : targets) {
        auto t = Token(id);
        if (!t)
            continue;
        writer.Append("target_anchor", N("sample", sample) + N("token", t) + S("bus", "usb") +
                                           S("hardware", "target_usb_parent") +
                                           N("enumerator_code", 0) + N("hardware_code", 0) +
                                           N("status_code", 0) + B("present", true) +
                                           B("started", true) + B("has_problem", false));
    }
    if (tree_root.code == 0 && tree_root.id) {
        auto t = Token(tree_root.id);
        if (t)
            writer.Append("tree_anchor", N("sample", sample) + N("token", t) + N("lookup_code", 0));
    }
    for (auto id : e.nodes)
        Attempt(id, "present_devnode", 0);
    return e;
}
Enumeration Companion::Interfaces(Bus b) {
    auto e = acquisition.Interfaces(b);
    if (e.interfaces.size() > InterfaceCap) {
        e.interfaces.resize(InterfaceCap);
        e.limit_hit = true;
        e.complete = false;
    }
    for (const auto &i : e.interfaces)
        if (!i.code)
            Attempt(i.node, b == Bus::Usb ? "usb_interface" : "hid_interface", i.flags);
        else {
            ++total;
            ++interface_unknown;
            ++unknown;
            ++omitted;
            details_complete = false;
            ++reasons["interface_lookup_failed"];
        }
    return e;
}
Lookup Companion::InterfaceNode(std::wstring_view, Bus) {
    writer.Fail("raw_notifications_unsupported");
    Lookup l;
    l.code = NotQueried;
    return l;
}
Node Companion::Properties(Id id) { return acquisition.Properties(id); }
Key Companion::InstanceKey(Id id) { return acquisition.InstanceKey(id); }

void Companion::Attempt(Id id, std::string_view source, unsigned flags) {
    auto r = Resolve(acquisition, id);
    const bool rejected = r.outcome == Outcome::Indeterminate;
    const bool context = r.outcome != Outcome::Indeterminate && r.node.bus == Bus::Hid &&
                         r.node.hardware == Hardware::Other &&
                         r.node.hardware_reason == Reason::UnsupportedDocumentedForm;
    if (!rejected && !context)
        return;
    const auto reason = r.resource_limited ? Reason::ResourceLimit : r.reason;
    if (rejected) {
        ++total;
        if (source == "present_devnode")
            ++node_unknown;
        else
            ++interface_unknown;
        ++reasons[Name(reason)];
    } else
        ++contexts;
    const int presence = present.contains(id) ? 1 : (present_complete ? 0 : -1);
    bool historical = source != "present_devnode" && !(flags & 1U) && presence == 0;
    inactive += historical;
    const auto own =
        acquisition.Read(id); // fixed metadata copy, survives cache-limit sentinel changes
    std::string relation = "unknown", outcome = "parent_unavailable";
    std::vector<Id> chain{id};
    std::set<Id> seen{id};
    Id current = id, root = 0, property = id;
    bool ancestor = false;
    std::uint32_t parent_code = NotQueried;
    for (unsigned depth = 0; depth <= ParentCap; ++depth) {
        if (Ticks() > diagnostic_deadline) {
            outcome = "time_limit";
            details_complete = false;
            writer.Fail("diagnostic_time_limit");
            break;
        }
        if (depth == r.depth && depth > 0 && r.ancestry_property_reason != Reason::None) {
            property = current;
            ancestor = true;
        }
        if (targets.contains(current)) {
            relation = "target";
            outcome = "target_reached";
            root = current;
            break;
        }
        if (tree_root.code == 0 && tree_root.id && current == tree_root.id) {
            if (!targets.empty() && present_complete) {
                relation = "other_branch";
                outcome = "tree_root_reached";
            } else
                outcome = "no_target_anchor";
            root = current;
            break;
        }
        if (depth == ParentCap) {
            outcome = "depth_limit";
            break;
        }
        const auto &f = acquisition.Read(current);
        if (f.node.resource_limited) {
            outcome = "acquisition_limit";
            details_complete = false;
            break;
        }
        parent_code = f.links.parent_code;
        if (parent_code || !f.links.parent)
            break; // code 13 is NOT normal-root proof
        if (!seen.insert(f.links.parent).second) {
            outcome = "cycle";
            break;
        }
        current = f.links.parent;
        chain.push_back(current);
    }
    // Own property rejection takes precedence over any additional diagnostic ancestor failure.
    bool own_bad = own.node.enum_code || !own.node.enumerator_valid || own.node.hw_code ||
                   !own.node.hardware_valid || own.node.hardware == Hardware::Missing ||
                   own.node.hardware == Hardware::Malformed;
    if (own_bad) {
        property = id;
        ancestor = false;
    }
    if (rejected) {
        if (relation == "target")
            ++target;
        else if (relation == "other_branch")
            ++other;
        else
            ++unknown;
    } else if (relation == "unknown")
        ++context_unknown;
    bool hid_failure = relation == "target" && own.node.bus == Bus::Hid && (own_bad || context);
    hid_own += hid_failure;
    if (details == DetailCap) {
        ++omitted;
        details_complete = false;
        writer.Fail("detail_limit");
        return;
    }
    if (outcome == "time_limit") {
        ++omitted;
        return;
    }
    std::vector<unsigned> chain_tokens;
    for (auto item : chain)
        chain_tokens.push_back(Token(item));
    unsigned pt = Token(property);
    if (!pt || std::find(chain_tokens.begin(), chain_tokens.end(), 0) != chain_tokens.end()) {
        ++omitted;
        details_complete = false;
        return;
    }
    const auto &f = acquisition.Read(property);
    Shape shape = f.shape;
    std::string key = "hardware_ids";
    if (f.node.enum_code || !f.node.enumerator_valid) {
        key = "enumerator_name";
        shape = f.enumerator_shape;
    }
    const bool property_failure = own_bad || ancestor || context;
    if (!property_failure) {
        key = "none";
        shape = Shape{};
    }
    std::string encoded = "[";
    for (auto t : chain_tokens) {
        if (encoded.size() > 1)
            encoded += ',';
        encoded += std::to_string(t);
    }
    encoded += ']';
    std::string fields =
        N("sample", sample) + N("attempt", total + contexts) + S("source", source) +
        S("enumerator", Name(own.node.bus)) + N("node_token", chain_tokens[0]) +
        N("property_token", pt) + S("property_key", key) +
        S("property_api", property_failure ? "CM_Get_DevNode_PropertyW" : "none") +
        S("property_owner", property_failure ? (ancestor ? "ancestor" : "own") : "relationship") +
        ShapeFields(shape) + S("original_reason", Name(reason)) +
        S("original_ancestry_property_reason", Name(r.ancestry_property_reason)) +
        N("present", presence) + N("interface_flags", flags) +
        B("inactive_nonpresent", historical) + S("relation", relation) +
        S("parent_outcome", outcome) + N("parent_code", parent_code) +
        N("depth", chain.size() - 1) + ",\"chain\":" + encoded +
        N("root_token", root ? Token(root) : 0) + B("possible_target", relation != "other_branch") +
        B("target_related_hid_own_failure", hid_failure);
    if (writer.Append(rejected ? "rejection" : "context", fields))
        ++details;
    else {
        ++omitted;
        details_complete = false;
    }
}
void Companion::EndSnapshot(bool ready) {
    std::string histogram = "[";
    for (const auto &[reason, count] : reasons) {
        if (histogram.size() > 1)
            histogram += ',';
        histogram += "{\"reason\":\"" + reason + "\",\"count\":" + std::to_string(count) + "}";
    }
    histogram += ']';
    const auto end = Ticks();
    bool over = end - begin > Frequency() * ScanBudgetMs / 1000;
    if (over) {
        details_complete = false;
        writer.Fail("scan_budget_exceeded");
    }
    writer.Append(
        "snapshot",
        N("sample", sample) + N("begin", begin) + N("end", end) + N("indeterminate", total) +
            N("contexts", contexts) + N("context_unknown_ancestry", context_unknown) +
            N("node_indeterminate", node_unknown) +
            N("interface_indeterminate", interface_unknown) + N("target_related", target) +
            N("other_branch", other) + N("unknown_ancestry", unknown) +
            N("inactive_nonpresent", inactive) + N("target_related_hid_own_failure", hid_own) +
            N("details", details) + N("omitted", omitted) + N("tokens", tokens.size()) +
            B("detail_complete", details_complete && omitted == 0) +
            B("attribution_complete", unknown == 0 && context_unknown == 0) +
            B("over_budget", over) + B("original_ready", ready) + ",\"reasons\":" + histogram,
        true);
}
} // namespace rejection_v1
