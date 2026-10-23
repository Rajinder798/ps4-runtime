// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
#include "ledger_v1.h"
#include <algorithm>
#include <limits>
#include <stdexcept>

namespace stage_ledger_v1 {
namespace {
std::string N(std::string_view k, Tick n) { return ",\"" + std::string(k) + "\":" + std::to_string(n); }
std::string S(std::string_view k, std::string_view s) { return ",\"" + std::string(k) + "\":\"" + std::string(s) + "\""; }
std::string B(std::string_view k, bool b) { return ",\"" + std::string(k) + "\":" + (b ? "true" : "false"); }
constexpr Tick Budget = 250000; // exactly 25 ms at the explicit 10 MHz host clock
struct OptionalExpired {};
}
const char *Name(Stage s) {
    switch (s) {
    case Stage::PresentEnumeration: return "present_enumeration";
    case Stage::SystemRoot: return "system_root_lookup";
    case Stage::TargetDiscovery: return "qualified_root_discovery";
    case Stage::RawProperty: return "raw_property_acquisition";
    case Stage::AcquisitionCache: return "acquisition_cache_population";
    case Stage::Classification: return "rejection_classification";
    case Stage::Ancestry: return "bounded_ancestry";
    case Stage::Serialization: return "detail_serialization";
    case Stage::InterfaceEnumeration: return "interface_enumeration";
    case Stage::ScopeCompletion: return "scope_completion";
    case Stage::Cleanup: return "cleanup";
    case Stage::Publication: return "final_publication";
    }
    throw std::runtime_error("Invalid host stage");
}
Ledger::Ledger(const std::filesystem::path &path, Clock &c, unsigned rc, unsigned bc)
    : clock(c), row_cap(rc), byte_cap(bc) {
    if (rc < 16 || rc > LedgerRows || bc < 4096 || bc > LedgerBytes)
        throw std::runtime_error("Invalid ledger bounds");
#ifdef _WIN32
    if (::_wfopen_s(&file, path.c_str(), L"wbx") != 0) file = nullptr;
#else
    file = std::fopen(path.c_str(), "wbx");
#endif
    if (!file) throw std::runtime_error("Fresh ledger output required");
    Emit("header", N("frequency", 10000000) + N("diagnostic_ms", 25) + N("scan_ms", 250) +
        N("row_cap", rc) + N("byte_cap", bc) + N("detail_cap", 64) + N("token_cap", 128) +
        N("parent_cap", 8) + N("source_call_cap", SourceCalls), Stamp());
}
Ledger::~Ledger() { if (file) std::fclose(file); }
void Ledger::Emit(std::string_view event, const std::string &fields, Tick qpc) {
    if (!sink_ok) return;
    std::string row = "{\"schema\":\"diagnostic-stage-ledger-v1\",\"origin\":\"HOST TEST\",\"sequence\":" +
        std::to_string(rows) + N("qpc", qpc) + S("event", event) + fields + "}\n";
    if (rows == row_cap || row.size() > byte_cap - bytes ||
        std::fwrite(row.data(), 1, row.size(), file) != row.size() || std::fflush(file)) {
        sink_ok = false;
        if (first_diagnostic.empty()) { first_diagnostic = "writer_failure"; diagnostic_qpc = last; }
        return;
    }
    ++rows; bytes += static_cast<unsigned>(row.size());
}
Tick Ledger::Stamp() {
    if (!valid_clock) return last;
    try {
        auto v = clock.Now();
        if (v < 0 || v < last) throw std::runtime_error("Host clock reversal");
        last = v;
    } catch (...) {
        valid_clock = false;
        if (first_diagnostic.empty()) {
            first_diagnostic = "clock_error"; diagnostic_qpc = last;
            Emit("first_failure", S("domain", "diagnostic") + S("reason", first_diagnostic) +
                 N("failure_qpc", last), last);
        }
    }
    return last;
}
void Ledger::Check(Tick tick) {
    if (begun && valid_clock && deadline >= 0 && tick >= deadline && first_diagnostic.empty()) {
        first_diagnostic = "diagnostic_time_limit"; diagnostic_qpc = tick;
        Emit("first_failure", S("domain", "diagnostic") + S("reason", first_diagnostic) +
            N("failure_qpc", tick), tick);
    }
}
void Ledger::Start() {
    if (begun) throw std::runtime_error("Exactly one ledger scope");
    start = Stamp(); begun = true;
    if (valid_clock && start <= std::numeric_limits<Tick>::max() - Budget) deadline = start + Budget;
    else { valid_clock = false; Fail("clock_error"); }
    Emit("scope_start", N("begin", start) + N("deadline", deadline) + B("clock_valid", valid_clock), last);
}
bool Ledger::Allowed() {
    Check(Stamp());
    return valid_clock && sink_ok && first_diagnostic.empty() && !ended;
}
unsigned Ledger::Begin(Stage stage, bool optional) {
    auto tick = Stamp(); Check(tick);
    if (optional && (!valid_clock || !sink_ok || !first_diagnostic.empty() || ended)) return 0;
    if (!begun || ended || stack.size() == 32) throw std::runtime_error("Ledger stage lifecycle");
    const unsigned id = ++next_id, parent = stack.empty() ? 0U : stack.back().first;
    stack.push_back({id, tick});
    Emit("stage_begin", N("id", id) + N("parent", parent) + S("stage", Name(stage)) +
        B("optional", optional) + N("remaining_ticks", valid_clock ? std::max<Tick>(deadline - tick, 0) : -1), tick);
    return id;
}
void Ledger::End(unsigned id) {
    if (!id) return;
    if (stack.empty() || stack.back().first != id) throw std::runtime_error("Unbalanced ledger stage");
    auto tick = Stamp(); Check(tick);
    auto begin = stack.back().second; stack.pop_back();
    Emit("stage_end", N("id", id) + N("begin", begin) + N("end", tick) +
        N("elapsed_ticks", valid_clock ? tick - begin : -1) +
        N("remaining_ticks", valid_clock ? std::max<Tick>(deadline - tick, 0) : -1) +
        B("clock_valid", valid_clock), tick);
}
void Ledger::Fail(std::string_view reason) {
    if (!first_diagnostic.empty()) return;
    first_diagnostic = reason; diagnostic_qpc = last;
    Emit("first_failure", S("domain", "diagnostic") + S("reason", reason) + N("failure_qpc", last), last);
}
void Ledger::OriginalFailure(unsigned code, Tick native_qpc) {
    if (!code || original_reason) return;
    auto tick = Stamp(); Check(tick);
    original_reason = code; original_qpc = native_qpc;
    Emit("first_failure", S("domain", "original") + N("reason", code) + N("failure_qpc", native_qpc), tick);
}
void Ledger::BreakWriter() { sink_ok = false; if (first_diagnostic.empty()) Fail("writer_failure"); }
void Ledger::Anchors(const std::vector<unsigned> &targets, unsigned system_root, bool complete, bool present) {
    std::string values = "[";
    for (auto token : targets) { if (values.size() > 1) values += ','; values += std::to_string(token); }
    values += ']'; auto tick = Stamp(); Check(tick);
    Emit("anchors", ",\"targets\":" + values + N("system_root", system_root) +
         B("discovery_complete", complete) + B("present_complete", present), tick);
}
void Ledger::Publish(const std::vector<Detail> &details, const Totals &totals, bool ready, bool cleanup,
                     const std::function<void(Stage)> &cost) {
    if (ended || !stack.empty()) throw std::runtime_error("Invalid final ledger lifecycle");
    auto publication = Begin(Stage::Publication, false); cost(Stage::Publication);
    for (const auto &d : details) {
        auto tick = Stamp(); Check(tick);
        Emit("detail", d.encoded + N("collected_qpc", d.collected), tick);
    }
    End(publication);
    auto completion = Begin(Stage::ScopeCompletion, false); cost(Stage::ScopeCompletion); End(completion);
    auto tick = Stamp(); Check(tick); ended = true;
    Emit("scope_end", N("begin", start) + N("end", tick) +
        N("elapsed_ticks", valid_clock ? tick - start : -1) +
        N("remaining_ticks", valid_clock ? std::max<Tick>(deadline - tick, 0) : -1) +
        B("clock_valid", valid_clock), tick);
    std::string reasons = "[";
    for (const auto &[r, count] : totals.reasons) {
        if (reasons.size() > 1) reasons += ',';
        reasons += "{\"reason\":\"" + r + "\",\"count\":" + std::to_string(count) + '}';
    }
    reasons += ']';
    Emit("summary", N("total", totals.total) + N("node", totals.node) + N("interfaces", totals.interfaces) +
        N("retained", totals.retained) + N("omitted", totals.omitted) + N("target", totals.target) +
        N("other", totals.other) + N("unknown", totals.unknown) + ",\"reasons\":" + reasons +
        N("original_reason", original_reason) + N("original_qpc", original_qpc) +
        S("diagnostic_reason", first_diagnostic.empty() ? "none" : first_diagnostic) + N("diagnostic_qpc", diagnostic_qpc) +
        B("original_ready", ready) + B("cleanup_ok", cleanup) +
        B("detail_complete", first_diagnostic.empty() && valid_clock && sink_ok && totals.omitted == 0) +
        B("attribution_complete", totals.unknown == 0) +
        B("diagnostic_complete", first_diagnostic.empty() && valid_clock && sink_ok && cleanup && totals.omitted == 0 && totals.unknown == 0) +
        B("recovery_accepted", false), tick);
}

Prototype::Prototype(HostSource &s, Ledger &l) : bridge(*this), source(s), ledger(l), acquisition(bridge) {}
bool Prototype::Work(Stage stage, bool optional, const std::function<void()> &body) {
    auto id = ledger.Begin(stage, optional);
    if (!id) return false;
    auto previous = optional_mode; optional_mode = optional;
    try { source.Cost(stage); if (!optional || ledger.Allowed()) body(); }
    catch (const OptionalExpired &) { optional_mode = previous; ledger.End(id); return false; }
    catch (...) { optional_mode = previous; ledger.End(id); throw; }
    optional_mode = previous; ledger.End(id); return !optional || ledger.Allowed();
}
void Prototype::Bridge::Call() {
    if (p.optional_mode) {
        if (!p.ledger.Allowed()) throw OptionalExpired{};
        if (p.ledger.Last() >= p.ledger.Deadline()) ++optional_started_late;
    }
    if (++calls > SourceCalls) { p.ledger.Fail("resource_limit"); throw std::runtime_error("Host Source call cap"); }
}
Enumeration Prototype::Bridge::Devnodes() { Call(); return p.source.Devnodes(); }
Enumeration Prototype::Bridge::Interfaces(Bus b) { Call(); return p.source.Interfaces(b); }
Root Prototype::Bridge::TreeRoot() { Call(); return p.source.TreeRoot(); }
Key Prototype::Bridge::InstanceKey(Id id) { Call(); return p.source.InstanceKey(id); }
RawNode Prototype::Bridge::Read(Id id) {
    RawNode value; bool acquired = false;
    p.Work(Stage::RawProperty, p.optional_mode, [&] { Call(); value = p.source.Read(id); acquired = true; });
    // A skipped optional call must not populate the frozen cache with fake missing
    // metadata. A real late return may be cached for subsequent original work.
    if (!acquired) throw OptionalExpired{};
    return value;
}
Fact Prototype::FactFor(Id id, bool optional) {
    auto previous = optional_mode; optional_mode = optional;
    Fact result;
    try { Work(Stage::AcquisitionCache, optional, [&] { result = acquisition.Read(id); }); }
    catch (...) { optional_mode = previous; throw; }
    optional_mode = previous; return result;
}
unsigned Prototype::Token(Id id) {
    if (auto i = tokens.find(id); i != tokens.end()) return i->second;
    if (tokens.size() == 128) { ledger.Fail("resource_limit"); return 0; }
    unsigned t = static_cast<unsigned>(tokens.size() + 1); tokens[id] = t; return t;
}
Enumeration Prototype::Devnodes() {
    ledger.Start(); Enumeration e;
    Work(Stage::PresentEnumeration, false, [&] { e = acquisition.Devnodes(); });
    if (e.nodes.size() > NodeCap) { e.nodes.resize(NodeCap); e.limit_hit = true; e.complete = false; }
    present.insert(e.nodes.begin(), e.nodes.end());
    present_complete = e.complete && !e.code && !e.cleanup_code && !e.limit_hit;
    Work(Stage::SystemRoot, true, [&] { tree = acquisition.TreeRoot(); });
    anchor_complete = Work(Stage::TargetDiscovery, true, [&] {
        for (auto id : e.nodes) {
            if (!ledger.Allowed()) return;
            auto n = FactFor(id, true).node;
            if (!ledger.Allowed()) return;
            if (n.bus == Bus::Usb && n.hardware == Hardware::UsbParent && n.enum_code == 0 && n.hw_code == 0 &&
                n.enumerator_valid && n.hardware_valid && n.status_code == 0 && (n.status & 8U) && !(n.status & 0x400U)) targets.insert(id);
        }
    });
    std::vector<unsigned> anchors;
    for (auto id : targets) anchors.push_back(Token(id));
    ledger.Anchors(anchors, tree.code == 0 && tree.id ? Token(tree.id) : 0U, anchor_complete, present_complete);
    for (auto id : e.nodes) Attempt(id, "present_devnode");
    return e;
}
Enumeration Prototype::Interfaces(Bus b) {
    Enumeration e; Work(Stage::InterfaceEnumeration, false, [&] { e = acquisition.Interfaces(b); });
    if (e.interfaces.size() > InterfaceCap) { e.interfaces.resize(InterfaceCap); e.limit_hit = true; e.complete = false; }
    for (const auto &i : e.interfaces) {
        if (i.code) {
            ++totals.total; ++totals.interfaces; ++totals.omitted; ++totals.unknown; ++totals.reasons["interface_lookup_failed"];
        } else Attempt(i.node, b == Bus::Usb ? "usb_interface" : "hid_interface");
    }
    return e;
}
Lookup Prototype::InterfaceNode(std::wstring_view, Bus) { throw std::runtime_error("No notification entry point"); }
Node Prototype::Properties(Id id) { return FactFor(id, false).node; }
Key Prototype::InstanceKey(Id id) { return acquisition.InstanceKey(id); }
void Prototype::Attempt(Id id, std::string_view origin) {
    Resolution r;
    // Required frozen classification prefetch: same Resolver/facts the Collector
    // will consume. It continues after diagnostic expiry to conserve aggregates.
    Work(Stage::Classification, false, [&] { r = Resolve(*this, id); });
    if (r.outcome != Outcome::Indeterminate) return;
    ++totals.total;
    if (origin == "present_devnode") ++totals.node; else ++totals.interfaces;
    const auto reason = Name(r.resource_limited ? Reason::ResourceLimit : r.reason);
    ++totals.reasons[reason];
    auto omit = [&] { ++totals.omitted; ++totals.unknown; };
    if (!ledger.Allowed()) { omit(); return; }
    std::string relation = "unknown";
    std::vector<Id> chain{id}; std::set<Id> seen{id}; Id current = id;
    bool walked = Work(Stage::Ancestry, true, [&] {
        for (unsigned depth = 0; depth <= ParentCap; ++depth) {
            if (!ledger.Allowed()) return;
            if (targets.contains(current)) { relation = "target"; return; }
            if (tree.code == 0 && current == tree.id) {
                if (present_complete && anchor_complete && !targets.empty()) relation = "other";
                return;
            }
            if (depth == ParentCap) return;
            auto f = FactFor(current, true);
            if (!ledger.Allowed() || f.node.resource_limited || f.links.parent_code || !f.links.parent) return;
            if (!seen.insert(f.links.parent).second) return;
            current = f.links.parent; chain.push_back(current);
        }
    });
    if (!walked || !ledger.Allowed()) { omit(); return; }
    if (details.size() == 64) { ledger.Fail("resource_limit"); omit(); return; }
    Detail d; d.attempt = totals.total; d.source = origin; d.reason = reason; d.relation = relation;
    bool serialized = Work(Stage::Serialization, true, [&] {
        for (auto node : chain) { auto token = Token(node); if (!token) return; d.chain.push_back(token); }
        std::string encoded = "[";
        for (auto token : d.chain) { if (encoded.size() > 1) encoded += ','; encoded += std::to_string(token); }
        encoded += ']';
        d.encoded = N("attempt", d.attempt) + S("source", d.source) + S("reason", d.reason) +
                    S("relation", d.relation) + ",\"chain\":" + encoded;
    });
    if (!serialized || !ledger.Allowed() || d.chain.size() != chain.size()) { omit(); return; }
    d.collected = ledger.Last(); details.push_back(d); ++totals.retained;
    if (relation == "target") ++totals.target; else if (relation == "other") ++totals.other; else ++totals.unknown;
}
void Prototype::Complete(bool ready, const std::function<void()> &cleanup, bool cleanup_ok) {
    Work(Stage::Cleanup, false, cleanup);
    if (!cleanup_ok) ledger.Fail("cleanup_failure");
    ledger.Publish(details, totals, ready, cleanup_ok, [&](Stage s) { source.Cost(s); });
}
} // namespace stage_ledger_v1
