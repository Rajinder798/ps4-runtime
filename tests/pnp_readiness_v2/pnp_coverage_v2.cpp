// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
#include "pnp_coverage_v2.h"
#include <algorithm>
#include <chrono>
#include <cstdio>
#include <set>
#include <stdexcept>
#ifdef _WIN32
#define NOMINMAX
#include <windows.h>
#else
#include <unistd.h>
#endif

namespace pnp_v2 {
namespace {
std::string N(std::string_view k, std::int64_t n) {
    return ",\"" + std::string(k) + "\":" + std::to_string(n);
}
std::string S(std::string_view k, std::string_view v) {
    return ",\"" + std::string(k) + "\":\"" + std::string(v) + "\"";
}
std::string B(std::string_view k, bool v) {
    return ",\"" + std::string(k) + "\":" + (v ? "true" : "false");
}
} // namespace
Tick Ticks() {
#ifdef _WIN32
    LARGE_INTEGER v{};
    if (!QueryPerformanceCounter(&v))
        throw std::runtime_error("QPC unavailable");
    return v.QuadPart;
#else
    return std::chrono::duration_cast<std::chrono::nanoseconds>(
               std::chrono::steady_clock::now().time_since_epoch())
        .count();
#endif
}
Tick Frequency() {
#ifdef _WIN32
    LARGE_INTEGER v{};
    if (!QueryPerformanceFrequency(&v))
        throw std::runtime_error("QPC frequency unavailable");
    return v.QuadPart;
#else
    return 1000000000;
#endif
}
const char *Name(Bus b) {
    switch (b) {
    case Bus::Usb:
        return "usb";
    case Bus::Hid:
        return "hid";
    case Bus::Other:
        return "other";
    default:
        return "unknown";
    }
}
const char *Name(Hardware h) {
    switch (h) {
    case Hardware::UsbParent:
        return "target_usb_parent";
    case Hardware::UsbFunction:
        return "target_usb_function";
    case Hardware::Hid:
        return "target_hid";
    case Hardware::Other:
        return "unmatched";
    case Hardware::Missing:
        return "missing";
    default:
        return "malformed";
    }
}
const char *Name(Outcome o) {
    switch (o) {
    case Outcome::Intended:
        return "intended";
    case Outcome::Unmatched:
        return "unmatched";
    default:
        return "indeterminate";
    }
}
const char *Name(Role r) {
    switch (r) {
    case Role::UsbParent:
        return "usb_parent";
    case Role::UsbFunction:
        return "usb_function";
    case Role::HidChild:
        return "hid_child";
    case Role::RelatedHid:
        return "related_hid";
    case Role::Unresolved:
        return "unresolved";
    default:
        return "none";
    }
}
bool DecodeMultiSz(const wchar_t *d, std::size_t n, std::vector<std::wstring> &out) {
    out.clear();
    if (!d || n < 1 || n > PropertyBytes / 2)
        return false;
    if (!d[0])
        return std::all_of(d, d + n, [](wchar_t c) { return c == 0; });
    if (n < 2 || d[n - 1] != 0 || d[n - 2] != 0)
        return false;
    std::size_t at = 0;
    while (at < n && d[at]) {
        std::size_t end = at;
        while (end < n && d[end])
            ++end;
        if (end == n || out.size() == 64 || end - at > 1023)
            return false;
        out.emplace_back(d + at, end - at);
        at = end + 1;
    }
    return std::all_of(d + at, d + n, [](wchar_t c) { return c == 0; });
}
Resolution Resolve(Provider &p, Id id) {
    Resolution r;
    r.node = p.Properties(id);
    auto n = r.node;
    r.resource_limited = n.resource_limited;
    if (n.enum_code || !n.enumerator_valid || n.bus == Bus::Unknown) {
        r.ancestry_code = n.enum_code;
        r.reason = n.enum_code ? Reason::EnumeratorUnavailable : Reason::EnumeratorMalformed;
        return r;
    }
    if (n.bus == Bus::Other) {
        r.reason = Reason::None;
        r.outcome = Outcome::Unmatched;
        r.role = Role::None;
        r.ancestry_complete = true;
        r.ancestry_code = 0;
        return r;
    }
    const bool bad = n.hw_code || !n.hardware_valid || n.hardware == Hardware::Missing ||
                     n.hardware == Hardware::Malformed;
    if (bad) {
        r.ancestry_code = n.hw_code;
        r.reason = n.hw_code                           ? Reason::PropertyApiFailure
                   : n.hardware_reason != Reason::None ? n.hardware_reason
                   : n.hardware == Hardware::Missing   ? Reason::MissingHardwareId
                                                       : Reason::InvalidHardwareSyntax;
        return r;
    }
    if ((n.bus == Bus::Usb && n.hardware == Hardware::Hid) ||
        (n.bus == Bus::Hid &&
         (n.hardware == Hardware::UsbParent || n.hardware == Hardware::UsbFunction))) {
        r.reason = Reason::IdentityBusConflict;
        return r;
    }
    if (n.bus == Bus::Usb && n.hardware == Hardware::UsbParent) {
        r.reason = Reason::None;
        r.outcome = Outcome::Intended;
        r.role = Role::UsbParent;
        r.root = id;
        r.root_node = n;
        r.ancestry_complete = true;
        r.ancestry_code = 0;
        return r;
    }
    if (n.hardware_reason == Reason::UnrecognizedForm ||
        (n.bus == Bus::Usb && n.hardware_reason == Reason::UnsupportedDocumentedForm)) {
        r.reason = n.hardware_reason;
        return r;
    }
    if (n.bus == Bus::Hid && n.hardware == Hardware::Other && n.hardware_reason == Reason::None) {
        r.reason = Reason::None;
        r.outcome = Outcome::Unmatched;
        r.role = Role::None;
        r.ancestry_complete = true;
        r.ancestry_code = 0;
        return r;
    }
    if (n.bus == Bus::Usb && n.hardware != Hardware::UsbFunction) {
        r.reason = Reason::None;
        r.outcome = Outcome::Unmatched;
        r.role = Role::None;
        r.ancestry_complete = true;
        r.ancestry_code = 0;
        return r;
    }
    const bool own_target = n.hardware == Hardware::UsbFunction || n.hardware == Hardware::Hid;
    std::set<Id> seen{id};
    for (unsigned depth = 0; depth < ParentCap; ++depth) {
        r.depth = depth + 1;
        r.ancestry_code = n.parent_code;
        if (n.parent_code || !n.parent) {
            // A documented root termination is complete for unrelated HID, but
            // cannot establish a USB parent for a target HID/function.
            if (n.parent_code == 13 && !own_target) {
                r.reason = Reason::None;
                r.outcome = Outcome::Unmatched;
                r.role = Role::None;
                r.ancestry_complete = true;
            }
            return r;
        }
        if (!seen.insert(n.parent).second) {
            r.reason = Reason::ParentCycle;
            return r;
        }
        n = p.Properties(n.parent);
        r.resource_limited |= n.resource_limited;
        if (n.bus == Bus::Other && n.enum_code == 0 && n.enumerator_valid) {
            if (!own_target) {
                r.reason = Reason::None;
                r.outcome = Outcome::Unmatched;
                r.role = Role::None;
                r.ancestry_complete = true;
                r.ancestry_code = 0;
            }
            return r;
        }
        if (n.enum_code || !n.enumerator_valid || n.hw_code || !n.hardware_valid ||
            n.hardware == Hardware::Missing || n.hardware == Hardware::Malformed) {
            r.ancestry_code = n.enum_code ? n.enum_code : n.hw_code;
            r.reason = Reason::ParentUnresolved;
            r.ancestry_property_reason = n.enum_code           ? Reason::EnumeratorUnavailable
                                         : !n.enumerator_valid ? Reason::EnumeratorMalformed
                                         : n.hw_code           ? Reason::PropertyApiFailure
                                                               : n.hardware_reason;
            return r;
        }
        if (n.bus == Bus::Usb && n.hardware == Hardware::Other &&
            n.hardware_reason == Reason::None) {
            r.reason = Reason::ParentUnresolved;
            r.ancestry_property_reason = Reason::ConflictingIdentities;
            return r;
        }
        if (n.bus == Bus::Usb && n.hardware == Hardware::UsbParent) {
            r.reason = Reason::None;
            r.outcome = Outcome::Intended;
            r.root = n.id;
            r.root_node = n;
            r.ancestry_complete = true;
            r.ancestry_code = 0;
            r.role = r.node.bus == Bus::Usb ? Role::UsbFunction
                                            : (own_target ? Role::HidChild : Role::RelatedHid);
            return r;
        }
    }
    r.reason = Reason::ParentLimit;
    return r; // Bounded chain exhausted; never invent a parent.
}
void Queue::Receive(Bus bus, unsigned action, const wchar_t *path, std::size_t n, Tick received,
                    bool valid) noexcept {
    const auto index = (bus == Bus::Usb   ? 0U
                        : bus == Bus::Hid ? 1U
                                          : 2U) *
                           3 +
                       std::min(action, 2U);
    counts[index].fetch_add(1);
    const auto serial = ordinal.fetch_add(1) + 1;
    std::unique_lock lock(mutex, std::try_to_lock);
    if (!lock || count == QueueCap) {
        dropped.fetch_add(1);
        return;
    }
    auto &entry = pending[count++];
    entry = Notice{};
    entry.received = received;
    entry.ordinal = serial;
    entry.bus = bus;
    entry.action = std::min(action, 2U);
    valid = valid && path && n > 0 && n <= PathCap && action <= 1 &&
            (bus == Bus::Usb || bus == Bus::Hid);
    std::size_t size = 0;
    if (valid) {
        while (size < n && path[size])
            ++size;
        valid = size < n && size > 0;
    }
    entry.valid = valid;
    if (valid)
        std::copy_n(path, size, entry.opaque.begin());
    else
        malformed.fetch_add(1);
}
std::vector<Notice> Queue::Drain() {
    std::lock_guard lock(mutex);
    std::vector<Notice> out(pending.begin(), pending.begin() + count);
    for (std::size_t i = 0; i < count; ++i)
        pending[i] = Notice{};
    count = 0;
    return out;
}
QueueStats Queue::Stats() const {
    QueueStats s;
    for (unsigned i = 0; i < 9; ++i)
        s.counts[i] = counts[i].load();
    s.dropped = dropped.load();
    s.malformed = malformed.load();
    return s;
}
Trace::Trace(const std::filesystem::path &p, bool host, std::uint64_t cap, std::uint64_t count)
    : byte_cap(cap), row_cap(count) {
    if (cap < 4096 || count < 8)
        throw std::runtime_error("Invalid evidence limits");
#ifdef _WIN32
    file = CreateFileW(p.c_str(), FILE_APPEND_DATA, FILE_SHARE_READ, nullptr, CREATE_NEW,
                       FILE_ATTRIBUTE_NORMAL, nullptr);
    if (file == INVALID_HANDLE_VALUE) {
        file = nullptr;
        throw std::runtime_error("Cannot create fresh PnP evidence");
    }
#else
    file = std::fopen(p.c_str(), "wbx");
    if (!file)
        throw std::runtime_error("Cannot create fresh PnP evidence");
#endif
    try {
        Append("header", S("origin", host ? "host-test" : "live") +
#ifdef _WIN32
                             S("clock", "qpc") + N("process_id", GetCurrentProcessId()) +
#else
                             S("clock", "steady") + N("process_id", getpid()) +
#endif
                             N("qpc_frequency", Frequency()) +
                             N("byte_cap", static_cast<Tick>(cap)) +
                             N("row_cap", static_cast<Tick>(count)) + N("period_ms", PeriodMs) +
                             N("scan_budget_ms", ScanBudgetMs) + N("node_cap", NodeCap) +
                             N("interface_cap", InterfaceCap) + N("relevant_cap", RelevantCap) +
                             N("token_cap", TokenCap) + N("parent_cap", ParentCap) +
                             N("queue_cap", QueueCap) + N("property_bytes", PropertyBytes) +
                             N("max_duration_ms", MaxDurationMs));
    } catch (...) {
#ifdef _WIN32
        CloseHandle(file);
#else
        std::fclose(static_cast<FILE *>(file));
#endif
        file = nullptr;
        throw;
    }
}
Trace::~Trace() {
    if (file) {
#ifdef _WIN32
        CloseHandle(file);
#else
        std::fclose(static_cast<FILE *>(file));
#endif
    }
}
void Trace::Append(std::string_view event, const std::string &fields, bool reserve) {
    if (!file || broken || finished)
        throw std::runtime_error("PnP evidence not writable");
    auto now = Ticks();
    if (now < last)
        throw std::runtime_error("PnP publication clock reversed");
    last = now;
    auto line = "{\"schema\":\"pnp-coverage-v2\",\"sequence\":" + std::to_string(rows) +
                N("qpc", now) + S("event", event) + fields + "}\n";
    if (bytes + line.size() + (reserve ? 0 : 2048) > byte_cap ||
        rows + 1 + (reserve ? 0 : 3) > row_cap)
        throw std::runtime_error("PnP evidence capacity exhausted");
#ifdef _WIN32
    DWORD written = 0;
    if (!WriteFile(file, line.data(), static_cast<DWORD>(line.size()), &written, nullptr) ||
        written != line.size()) {
        broken = true;
        throw std::runtime_error("PnP append failed");
    }
#else
    auto *f = static_cast<FILE *>(file);
    if (std::fwrite(line.data(), 1, line.size(), f) != line.size() || std::fflush(f)) {
        broken = true;
        throw std::runtime_error("PnP append failed");
    }
#endif
    bytes += line.size();
    ++rows;
}
void Trace::Registration(Bus bus, std::uint32_t code, bool unreg) {
    Append(unreg ? "unregistration" : "registration", S("interface", Name(bus)) + N("code", code));
    if (code)
        Fail(unreg ? Failure::Cleanup : Failure::Registration);
}
void Trace::Session(unsigned duration, Tick begin) {
    Append("session", N("duration_ms", duration) + N("qpc_begin", begin));
}
void Trace::Stopped(Tick begin, Tick end, bool requested) {
    Append("stopped", N("qpc_begin", begin) + N("qpc_end", end) + B("stop_requested", requested));
}
void Trace::Fail(Failure reason) {
    if (failed)
        return;
    failed = true;
    Append("first_failure", N("reason", static_cast<int>(reason)), true);
#ifdef _WIN32
    if (!FlushFileBuffers(file)) {
        broken = true;
        throw std::runtime_error("PnP first failure flush failed");
    }
#endif
}
void Trace::Cleanup(std::uint32_t code) { Append("cleanup", N("code", code), true); }
void Trace::Finish(bool coverage, bool cleanup) {
    coverage = coverage && !Failed();
    Append("summary",
           B("collection_complete", coverage && cleanup && !Failed()) +
               B("coverage_complete", coverage) + B("cleanup_ok", cleanup) +
               B("recovery_accepted", false),
           true);
#ifdef _WIN32
    if (!FlushFileBuffers(file)) {
        broken = true;
        throw std::runtime_error("PnP final flush failed");
    }
#endif
    finished = true;
}
void Collector::Incomplete(Failure why) {
    coverage = false;
    trace.Fail(why);
}
unsigned Collector::Token(Id id, std::uint32_t &code) {
    const auto key = provider.InstanceKey(id);
    code = key.code;
    if (code || key.value.empty() || key.value.size() > 4095) {
        detail_complete = false;
        Incomplete();
        return 0;
    }
    const auto old = tokens.find(key.value);
    if (old != tokens.end())
        return old->second;
    if (tokens.size() == TokenCap) {
        code = NotQueried;
        detail_complete = false;
        Incomplete(Failure::Resources);
        return 0;
    }
    auto token = static_cast<unsigned>(tokens.size() + 1);
    tokens.emplace(key.value, token);
    return token;
}
std::string Collector::Fields(const Resolution &r, int present, int root_present) {
    std::uint32_t code = NotQueried, root_code = NotQueried;
    unsigned token = 0, root = 0;
    if (r.outcome == Outcome::Intended) {
        token = Token(r.node.id, code);
        root = Token(r.root, root_code);
    }
    const auto &n = r.node;
    const int started = n.status_code ? -1 : ((n.status & 8U) ? 1 : 0); // documented DN_STARTED
    const Tick problem =
        n.status_code ? -1 : ((n.status & 0x400U) ? static_cast<Tick>(n.problem) : 0);
    return S("subreason", Name(r.reason)) +
           S("ancestry_property_subreason", Name(r.ancestry_property_reason)) +
           S("hardware_subreason", Name(n.hardware_reason)) + N("hardware_type", n.hardware_type) +
           N("hardware_bytes", n.hardware_bytes) + N("root_status_code", r.root_node.status_code) +
           N("root_started", r.root_node.status_code ? -1 : ((r.root_node.status & 8U) ? 1 : 0)) +
           N("root_problem", r.root_node.status_code
                                 ? -1
                                 : ((r.root_node.status & 0x400U) ? r.root_node.problem : 0)) +
           S("outcome", Name(r.outcome)) + S("role", Name(r.role)) + N("token", token) +
           N("root_token", root) + N("key_code", code) + N("root_key_code", root_code) +
           S("root_hardware", Name(r.root_node.hardware)) +
           N("root_hardware_code", r.root_node.hw_code) +
           N("root_enumerator_code", r.root_node.enum_code) + S("bus", Name(n.bus)) +
           S("hardware", Name(n.hardware)) + B("enumerator_valid", n.enumerator_valid) +
           B("hardware_valid", n.hardware_valid) + B("compatible_valid", n.compatible_valid) +
           B("resource_limited", r.resource_limited) + N("hardware_code", n.hw_code) +
           N("compatible_code", n.compatible_code) + B("composite", n.composite) +
           N("enumerator_code", n.enum_code) + N("parent_code", n.parent_code) +
           N("ancestry_code", r.ancestry_code) + N("depth", r.depth) +
           B("ancestry_complete", r.ancestry_complete) + N("present", present) +
           N("root_present", root_present) + N("status_code", n.status_code) +
           N("started", r.outcome == Outcome::Intended ? started : -1) +
           N("status", r.outcome == Outcome::Intended ? n.status : 0) +
           N("problem", r.outcome == Outcome::Intended ? problem : -1);
}
void Collector::Notifications(Queue &q) try {
    const auto begin_drain = Ticks();
    auto batch = q.Drain();
    for (const auto &n : batch) {
        ++processed;
        trace.Append("receipt", N("receipt", static_cast<Tick>(n.ordinal)) +
                                    N("received_qpc", n.received) + S("interface", Name(n.bus)) +
                                    N("action", n.action) + B("payload_valid", n.valid));
        if (n.received <= 0 || n.received < last_received || n.received > Ticks()) {
            Incomplete(Failure::Clock);
        }
        last_received = n.received;
        const auto begin = Ticks();
        Lookup lookup{};
        lookup.code = NotQueried;
        Resolution r;
        if (n.valid) {
            lookup = provider.InterfaceNode(n.opaque.data(), n.bus);
            if (!lookup.code && !lookup.iface.code)
                r = Resolve(provider, lookup.iface.node);
            else
                r.reason = Reason::InterfaceLookupFailed;
        } else {
            r.reason = Reason::InterfaceLookupFailed;
        }
        const auto fields = Fields(r, -1, -1);
        const auto end = Ticks();
        trace.Append(
            "classification",
            N("receipt", static_cast<Tick>(n.ordinal)) + N("qpc_begin", begin) + N("qpc_end", end) +
                B("lookup_attempted", n.valid) + N("lookup_code", lookup.code) +
                N("detail_code", lookup.iface.detail_code) +
                N("interface_code", lookup.iface.code) + N("cleanup_code", lookup.cleanup_code) +
                N("interface_flags", lookup.iface.flags) + fields);
        if (r.outcome == Outcome::Indeterminate || lookup.code || lookup.cleanup_code ||
            lookup.iface.code)
            Incomplete(r.resource_limited ? Failure::Resources : Failure::Coverage);
        if (end - begin > Frequency() * ScanBudgetMs / 1000)
            Incomplete(Failure::Overhead);
    }
    if (!batch.empty()) {
        const auto end = Ticks();
        const bool overhead = end - begin_drain > Frequency() * ScanBudgetMs / 1000;
        trace.Append("drain", N("qpc_begin", begin_drain) + N("qpc_end", end) +
                                  N("processed", static_cast<Tick>(batch.size())) +
                                  B("over_budget", overhead));
        if (overhead)
            Incomplete(Failure::Overhead);
    }
    const auto s = q.Stats();
    if (s.dropped || s.malformed)
        Incomplete(Failure::Queue);
} catch (...) {
    coverage = false;
    trace.Fail(Failure::Resources);
    throw;
}
void Collector::Snapshot() try {
    const auto begin = Ticks();
    ++sample;
    detail_complete = true;
    const bool late = last_snapshot &&
                      begin - last_snapshot > Frequency() * (PeriodMs + ScanBudgetMs + 100) / 1000;
    last_snapshot = begin;
    trace.Append("snapshot_begin", N("sample", sample) + N("qpc_begin", begin));
    auto nodes = provider.Devnodes();
    const bool node_limit = nodes.limit_hit || nodes.nodes.size() > NodeCap;
    bool complete = nodes.complete && nodes.code == 0 && nodes.cleanup_code == 0 && !node_limit;
    const bool present_complete =
        nodes.complete && !nodes.code && !nodes.cleanup_code && !node_limit;
    std::set<Id> present(nodes.nodes.begin(), nodes.nodes.end()), roots, qualified, installed,
        unresolved;
    unsigned qualified_hid = 0;
    ready = false;
    unsigned intended = 0, unmatched = 0, unknown = 0, emitted = 0, root_count = 0, hid_count = 0,
             not_started = 0, resources = node_limit ? 1U : 0U;
    std::map<std::string, unsigned> reasons;
    // Non-identifying error histograms. Fixed API names, at most 32 distinct pairs.
    std::map<std::pair<std::string, std::uint32_t>, unsigned> errors;
    auto error = [&](const char *api, std::uint32_t code) {
        if (code && code != NotQueried) {
            auto key = std::make_pair(std::string(api), code);
            if (errors.contains(key) || errors.size() < 32)
                ++errors[key];
            else
                complete = false;
        }
    };
    auto record = [&](const Resolution &r, bool from_nodes, Bus interface_bus,
                      const Interface &iface) {
        if (r.outcome == Outcome::Unmatched)
            return;
        if (r.resource_limited) {
            ++resources;
            complete = false;
        }
        error("hardware", r.node.hw_code);
        error("enumerator", r.node.enum_code);
        error("ancestry", r.ancestry_code);
        if (r.outcome == Outcome::Indeterminate) {
            const char *reason = Name(r.resource_limited ? Reason::ResourceLimit : r.reason);
            unresolved.insert(r.node.id);
            ++reasons[reason];
            complete = false;
            return;
        }
        const int own = present.contains(r.node.id) ? 1 : (present_complete ? 0 : -1);
        const int parent = present.contains(r.root) ? 1 : (present_complete ? 0 : -1);
        const bool historical = !from_nodes && !(iface.flags & 1U) && own == 0 && parent == 0;
        if (parent == 1) {
            roots.insert(r.root);
            if (!r.root_node.status_code && (r.root_node.status & 8U) &&
                !(r.root_node.status & 0x400U))
                qualified.insert(r.root);
            else
                unresolved.insert(r.root);
        } else if (historical)
            installed.insert(r.root);
        else {
            unresolved.insert(r.root);
            complete = false;
        }
        if (from_nodes && r.role == Role::HidChild && own == 1 && parent == 1 &&
            !r.node.status_code && (r.node.status & 8U) && !(r.node.status & 0x400U))
            ++qualified_hid;
        if (emitted == RelevantCap) {
            ++resources;
            complete = false;
            return;
        }
        ++emitted;
        if (r.node.status_code && !(historical && r.node.status_code == 13))
            complete = false;
        // Historical CR_NO_SUCH_DEVNODE is retained in the row, not a live status failure.
        if (!(historical && r.node.status_code == 13))
            error("status", r.node.status_code);
        trace.Append(from_nodes ? "devnode" : "interface",
                     N("sample", sample) + S("interface", Name(interface_bus)) +
                         N("interface_flags", iface.flags) + N("detail_code", iface.detail_code) +
                         B("installed_inactive", historical) + Fields(r, own, parent));
    };
    for (std::size_t i = 0; i < std::min<std::size_t>(nodes.nodes.size(), NodeCap); ++i) {
        const auto r = Resolve(provider, nodes.nodes[i]);
        if (r.outcome == Outcome::Intended) {
            ++intended;
            if (r.role == Role::UsbParent)
                ++root_count;
            if (r.role == Role::HidChild || r.role == Role::RelatedHid)
                ++hid_count;
            if (!r.node.status_code && !(r.node.status & 8U))
                ++not_started;
        } else if (r.outcome == Outcome::Unmatched)
            ++unmatched;
        else
            ++unknown;
        record(r, true, Bus::Other, Interface{});
    }
    unsigned active_usb = 0, active_hid = 0, inactive = 0, interface_unknown = 0,
             interface_unmatched = 0;
    std::string scans;
    for (auto bus : {Bus::Usb, Bus::Hid}) {
        const auto scan = provider.Interfaces(bus);
        const bool interface_limit = scan.limit_hit || scan.interfaces.size() > InterfaceCap;
        if (interface_limit)
            ++resources;
        if (!scan.complete || scan.code || scan.cleanup_code || interface_limit)
            complete = false;
        if (!scans.empty())
            scans += ',';
        scans += "{\"interface\":\"" + std::string(Name(bus)) + "\"" + N("code", scan.code) +
                 N("cleanup_code", scan.cleanup_code) + N("terminal_code", scan.terminal_code) +
                 B("limit_hit", interface_limit) +
                 B("complete", scan.complete && !interface_limit) +
                 N("visited",
                   static_cast<Tick>(std::min<std::size_t>(scan.interfaces.size(), InterfaceCap))) +
                 "}";
        for (std::size_t i = 0; i < std::min<std::size_t>(scan.interfaces.size(), InterfaceCap);
             ++i) {
            const auto &iface = scan.interfaces[i];
            if (iface.code) {
                error("interface_detail", iface.code);
                ++interface_unknown;
                ++reasons["interface_lookup_failed"];
                complete = false;
                continue;
            }
            const auto r = Resolve(provider, iface.node);
            if (r.outcome == Outcome::Indeterminate) {
                ++interface_unknown;
                complete = false;
            }
            if (r.outcome == Outcome::Unmatched)
                ++interface_unmatched;
            if (r.outcome == Outcome::Intended) {
                if (iface.flags & 1U) {
                    if (bus == Bus::Usb)
                        ++active_usb;
                    else
                        ++active_hid;
                } else
                    ++inactive;
            }
            record(r, false, bus, iface);
        }
    }
    if (roots.size() > 1)
        complete = false; // Report every candidate; never select one.
    std::string failures;
    for (const auto &[key, count] : errors) {
        if (!failures.empty())
            failures += ',';
        failures +=
            "{\"api\":\"" + key.first + "\"" + N("code", key.second) + N("count", count) + "}";
    }
    std::string classifications;
    for (const auto &[reason, count] : reasons) {
        if (!classifications.empty())
            classifications += ',';
        classifications += "{\"reason\":\"" + reason + "\"" + N("count", count) + "}";
    }
    const auto end = Ticks();
    const bool overhead = end - begin > Frequency() * ScanBudgetMs / 1000;
    if (overhead || late || !detail_complete)
        complete = false;
    const bool identity_gap =
        unknown || interface_unknown || !unresolved.empty() || !present_complete;
    ready = complete && qualified.size() == 1 && qualified_hid > 0 && active_usb > 0 &&
            active_hid > 0 && !identity_gap;
    trace.Append(
        "snapshot",
        N("sample", sample) + N("qpc_begin", begin) + N("qpc_end", end) +
            N("devnode_code", nodes.code) + N("devnode_cleanup_code", nodes.cleanup_code) +
            N("devnode_terminal_code", nodes.terminal_code) + B("devnode_limit_hit", node_limit) +
            B("devnode_enumeration_complete", nodes.complete && !node_limit) +
            N("visited", static_cast<Tick>(std::min<std::size_t>(nodes.nodes.size(), NodeCap))) +
            N("intended", intended) + N("unmatched", unmatched) + N("indeterminate", unknown) +
            N("usb_parents", root_count) + N("hid_children", hid_count) +
            N("present_qualified_roots", static_cast<Tick>(qualified.size())) +
            N("installed_inactive_roots", static_cast<Tick>(installed.size())) +
            N("unresolved_roots", static_cast<Tick>(unresolved.size())) +
            N("multiple_present_candidates",
              roots.size() > 1 ? static_cast<Tick>(roots.size()) : 0) +
            B("incomplete_identity_coverage", identity_gap) + B("initial_ready", ready) +
            N("not_started", not_started) + N("roots", static_cast<Tick>(roots.size())) +
            N("active_usb", active_usb) + N("active_hid", active_hid) +
            N("inactive_interfaces", inactive) + N("interface_indeterminate", interface_unknown) +
            N("interface_unmatched", interface_unmatched) + N("resource_failures", resources) +
            B("ambiguous", roots.size() > 1) + B("over_budget", overhead) +
            B("cadence_late", late) + B("coverage_complete", complete) +
            S("presence", intended   ? "qualifying_nodes"
                          : complete ? "no_qualifying_node"
                                     : "unknown") +
            ",\"interface_scans\":[" + scans + "],\"errors\":[" + failures +
            "],\"classification_failures\":[" + classifications + "]");
    if (!complete)
        Incomplete(overhead || late ? Failure::Overhead
                   : resources      ? Failure::Resources
                                    : Failure::Coverage);
} catch (...) {
    coverage = false;
    trace.Fail(Failure::Resources);
    throw;
}
void Collector::QueueSummary(const Queue &q) {
    auto s = q.Stats();
    std::string counts;
    for (auto n : s.counts) {
        if (!counts.empty())
            counts += ',';
        counts += std::to_string(n);
    }
    trace.Append("queue", N("processed", static_cast<Tick>(processed)) +
                              N("dropped", static_cast<Tick>(s.dropped)) +
                              N("malformed", static_cast<Tick>(s.malformed)) + ",\"counts\":[" +
                              counts + "]");
    if (s.dropped || s.malformed)
        Incomplete(Failure::Queue);
}
} // namespace pnp_v2
