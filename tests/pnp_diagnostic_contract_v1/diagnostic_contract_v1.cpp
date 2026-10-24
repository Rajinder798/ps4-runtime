// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
#include "diagnostic_contract_v1.h"
#include <fstream>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <type_traits>

namespace diagnostic_v1 {
const char *Name(Kind k) {
    switch (k) {
    case Kind::Devnodes: return "devnodes";
    case Kind::Interfaces: return "interfaces";
    case Kind::Lookup: return "lookup";
    case Kind::Properties: return "properties";
    case Kind::Key: return "key";
    }
    return "invalid";
}
const char *Name(Error e) {
    switch (e) {
    case Error::None: return "none";
    case Error::Clock: return "clock";
    case Error::Time: return "time";
    case Error::Records: return "records";
    case Error::Payload: return "payload";
    case Error::Events: return "events";
    case Error::Capture: return "capture";
    case Error::Replay: return "replay";
    case Error::Unknown: return "unknown";
    case Error::Cleanup: return "cleanup";
    case Error::Writer: return "writer";
    }
    return "invalid";
}
void Recorder::Fail(Error e) noexcept { if (capture.first == Error::None) capture.first = e; }
Tick Recorder::Stamp() noexcept {
    if (!capture.clock_valid) return capture.last;
    try {
        const Tick t = clock.Now();
        if (t < capture.last || t < 0) throw std::runtime_error("clock");
        capture.last = t;
        if (capture.deadline >= 0 && t >= capture.deadline) Fail(Error::Time);
    } catch (...) { capture.clock_valid = false; Fail(Error::Clock); }
    return capture.last;
}
Recorder::Recorder(Provider &p, Clock &c, Limits limits, unsigned fault) noexcept
    : provider(p), clock(c), copy_fault_at(fault) {
    capture.limits = limits;
    if (limits.records > RecordCap || limits.payload > PayloadCap || limits.events > RowCap ||
        limits.rows < 16 || limits.rows > RowCap || limits.bytes < 4096 || limits.bytes > ByteCap) {
        capture.limits = {}; Fail(Error::Capture);
    }
    try {
        capture.frequency = clock.Frequency();
        if (capture.frequency <= 0 || capture.frequency > 1000000000 || capture.frequency % 40)
            throw std::runtime_error("frequency");
        capture.start = clock.Now(); capture.last = capture.start;
        if (capture.start < 0 || capture.start > std::numeric_limits<Tick>::max() - capture.frequency/40)
            throw std::runtime_error("deadline");
        capture.deadline = capture.start + capture.frequency/40;
    } catch (...) { capture.clock_valid = false; capture.start = capture.last = 0; Fail(Error::Clock); }
    try {
        capture.records.reserve(capture.limits.records);
        capture.events.reserve(capture.limits.events);
    } catch (...) { Fail(Error::Capture); }
}
namespace {
std::size_t Payload(Borrowed v) {
    std::size_t bytes = sizeof(Record);
    if (auto e = std::get_if<const Enumeration *>(&v)) {
        if ((*e)->nodes.size() > NodeCap || (*e)->interfaces.size() > InterfaceCap) return PayloadCap + 1;
        bytes += (*e)->nodes.size()*sizeof(Id) + (*e)->interfaces.size()*sizeof(Interface);
    } else if (auto k = std::get_if<const Key *>(&v)) {
        if ((*k)->value.size() > 4095) return PayloadCap + 1;
        bytes += (*k)->value.size()*sizeof(wchar_t);
    }
    return bytes;
}
bool Known(const Value &v) {
    if (auto n = std::get_if<Node>(&v))
        return !n->enum_code && !n->hw_code && !n->status_code && n->enumerator_valid && n->hardware_valid &&
               n->hardware != Hardware::Missing && n->hardware != Hardware::Malformed;
    if (auto e = std::get_if<Enumeration>(&v)) return e->complete && !e->code && !e->cleanup_code && !e->limit_hit;
    if (auto l = std::get_if<Lookup>(&v)) return !l->code && !l->cleanup_code && !l->iface.code;
    if (auto k = std::get_if<Key>(&v)) return !k->code && !k->value.empty();
    return false;
}
std::string N(const char *key, std::int64_t n) { return ",\"" + std::string(key) + "\":" + std::to_string(n); }
std::string S(const char *key, const char *v) { return ",\"" + std::string(key) + "\":\"" + v + "\""; }
std::string B(const char *key, bool b) { return ",\"" + std::string(key) + "\":" + (b ? "true" : "false"); }
}
void Recorder::Store(Kind k, Id id, Borrowed v, bool threw) noexcept {
    if (consumed) return; // caller has ended the epoch; forwarding still never stops
    ++capture.calls;
    const auto tick = Stamp();
    try {
        if (capture.events.size() == capture.limits.events) throw std::length_error("events");
        if (sizeof(Event) > capture.limits.payload - capture.payload) throw std::length_error("event payload");
        capture.events.push_back({capture.calls, k, threw, tick});
        capture.payload += sizeof(Event);
    } catch (...) { ++capture.event_drops; Fail(Error::Events); }
    try {
        if (!capture.clock_valid || tick >= capture.deadline) { ++capture.dropped; return; }
        if (capture.records.size() == capture.limits.records) { ++capture.dropped; Fail(Error::Records); return; }
        const auto bytes = Payload(v);
        if (bytes > capture.limits.payload - capture.payload) { ++capture.dropped; Fail(Error::Payload); return; }
        if (copy_fault_at && capture.calls == copy_fault_at) throw std::runtime_error("host capture fault");
        Value copy = std::visit([](auto p) -> Value {
            if constexpr (std::is_same_v<decltype(p), std::monostate>) return {};
            else return *p;
        }, v);
        capture.records.push_back({capture.calls, k, id, threw, std::move(copy)});
        capture.payload += static_cast<unsigned>(bytes);
    } catch (...) { ++capture.dropped; Fail(Error::Capture); }
}
// The provider operation is outside capture's catch-all. Only its original
// exception is rethrown; all diagnostic recording operations are noexcept.
Enumeration Recorder::Devnodes() {
    Enumeration v;
    try { v = provider.Devnodes(); } catch (...) { Store(Kind::Devnodes,0,{},true); throw; }
    Store(Kind::Devnodes,0,&v,false);
    return v;
}
Enumeration Recorder::Interfaces(Bus b) {
    Enumeration v;
    try { v = provider.Interfaces(b); } catch (...) { Store(Kind::Interfaces,0,{},true); throw; }
    Store(Kind::Interfaces,0,&v,false);
    return v;
}
Lookup Recorder::InterfaceNode(std::wstring_view path, Bus b) {
    Lookup v;
    try { v = provider.InterfaceNode(path,b); } catch (...) { Store(Kind::Lookup,0,{},true); throw; }
    Store(Kind::Lookup,0,&v,false); return v;
}
Node Recorder::Properties(Id id) {
    Node v;
    try { v = provider.Properties(id); } catch (...) { Store(Kind::Properties,id,{},true); throw; }
    Store(Kind::Properties,id,&v,false); return v;
}
Key Recorder::InstanceKey(Id id) {
    Key v;
    try { v = provider.InstanceKey(id); } catch (...) { Store(Kind::Key,id,{},true); throw; }
    Store(Kind::Key,id,&v,false);
    return v;
}
Frozen Recorder::Freeze() && noexcept {
    capture.native_end = Stamp(); capture.freeze_end = Stamp(); consumed = true;
    return Frozen(std::move(capture));
}
Replay::Replay(const Frozen &f) {
    for (const auto &r : f.View().records) {
        if (!Known(r.value)) ++unknown;
        if (r.threw) continue;
        if (auto n = std::get_if<Node>(&r.value)) {
            cache[r.id].push_back(*n);
        }
    }
}
std::vector<Node> Replay::Observations(Id id) {
    const auto it = cache.find(id);
    if (it == cache.end()) { ++unknown; return {}; }
    return it->second;
}
Result Finish(const std::filesystem::path &path, const Frozen &f, const Native &native, Clock &clock, Options options) {
    try {
    const auto &c = f.View();
    Error first = c.first;
    bool valid = c.clock_valid;
    Tick last = c.freeze_end;
    auto fail = [&](Error e) { if (first == Error::None) first = e; };
    auto stamp = [&]() {
        if (!valid) return last;
        try {
            if (clock.Frequency() != c.frequency) throw std::runtime_error("domain");
            const auto t = clock.Now();
            if (t < last || t < 0) throw std::runtime_error("clock");
            last = t;
            if (last >= c.deadline) fail(Error::Time);
        } catch (...) { valid = false; fail(Error::Clock); }
        return last;
    };
    unsigned unknown = 0;
    const auto replay_begin = stamp();
    const bool allowed = valid && last < c.deadline;
    bool replay_ok = true;
    if (allowed) {
        try {
            if (options.replay_fault) throw std::runtime_error("host replay fault");
            Replay replay(f);
            if (options.missing_request) (void)replay.Observations(std::numeric_limits<Id>::max());
            unknown = replay.Unknown();
            if (unknown) fail(Error::Unknown);
        } catch (...) { fail(Error::Replay); ++unknown; replay_ok = false; }
    }
    const auto replay_end = stamp();
    if (!options.cleanup_ok) fail(Error::Cleanup);
    const auto cleanup_end = stamp();
    if (!options.finalization_ok) fail(Error::Writer);
    const auto publication_end = stamp();
    const auto completion_end = stamp();
    const auto scope_end = stamp();
    const auto footer_tick = stamp();
    if (native.exception || !native.coverage || native.first_reason ||
        !native.cleanup_ok || !native.collection_complete) fail(Error::Unknown);
    const bool complete = first == Error::None && valid && !c.dropped && !c.event_drops &&
                          !unknown && options.cleanup_ok && options.finalization_ok;
    std::vector<std::string> lines;
    auto emit = [&](const char *event, Tick tick, const std::string &fields) {
        lines.push_back("{\"schema\":\"pnp-diagnostic-contract-v1\",\"origin\":\"HOST TEST\",\"sequence\":" +
            std::to_string(lines.size()) + N("qpc",tick) + S("event",event) + fields + "}\n");
    };
    emit("header", c.start, N("frequency",c.frequency) + N("diagnostic_ms",25) + N("scan_ms",250) +
         N("record_cap",c.limits.records) + N("payload_cap",c.limits.payload) + N("event_cap",c.limits.events) +
         N("row_cap",c.limits.rows) + N("byte_cap",c.limits.bytes) + N("token_cap",128) + N("parent_cap",8) +
         N("depth_cap",DepthCap) + S("clock_domain","host_test_ticks") + S("native_internal_stages","opaque"));
    emit("scope_start",c.start,N("begin",c.start) + N("deadline",valid ? c.deadline : -1) + B("clock_valid",valid));
    auto begin = [&](unsigned id, const char *stage, Tick tick) {
        emit("stage_begin",tick,N("id",id) + N("parent",0) + S("stage",stage) + B("optional",id==3));
    };
    auto end = [&](unsigned id, Tick a, Tick b, const char *state, Error reason) {
        emit("stage_end",b,N("id",id) + N("begin",a) + N("end",b) +
             N("elapsed_ticks",valid ? b-a : -1) + B("clock_valid",valid) +
             S("state",valid ? state : "not_measurable") + S("reason",Name(valid ? reason : Error::Clock)));
    };
    begin(1,"native_collection",c.start);
    for (const auto &e : c.events)
        emit("call",e.tick,N("ordinal",e.ordinal) + S("kind",Name(e.kind)) + B("threw",e.threw));
    end(1,c.start,c.native_end,native.exception ? "failed" : "completed",native.exception ? Error::Unknown : Error::None);
    begin(2,"capture_freeze",c.native_end);
    for (const auto &r : c.records)
        emit("fact",c.freeze_end,N("ordinal",r.ordinal) + S("kind",Name(r.kind)) + B("threw",r.threw) + B("known",Known(r.value)));
    end(2,c.native_end,c.freeze_end,"completed",Error::None);
    emit("native_result",c.freeze_end,N("frequency",native.frequency) + N("first_reason",native.first_reason) +
         N("first_qpc",native.first_qpc) + B("ready",native.ready) + B("coverage",native.coverage) + B("exception",native.exception) +
         B("cleanup_ok",native.cleanup_ok) + B("collection_complete",native.collection_complete));
    begin(3,"optional_replay",replay_begin);
    end(3,replay_begin,replay_end,allowed ? (replay_ok ? "completed" : "failed") : "skipped",
        allowed ? (replay_ok ? Error::None : Error::Replay) : (valid ? Error::Time : Error::Clock));
    begin(4,"cleanup",replay_end);
    end(4,replay_end,cleanup_end,options.cleanup_ok ? "completed" : "failed",options.cleanup_ok ? Error::None : Error::Cleanup);
    begin(5,"final_publication",cleanup_end);
    end(5,cleanup_end,publication_end,options.finalization_ok ? "completed" : "failed",options.finalization_ok ? Error::None : Error::Writer);
    begin(6,"scope_completion",publication_end);
    end(6,publication_end,completion_end,complete ? "completed" : "failed",first);
    emit("scope_end",scope_end,N("begin",c.start) + N("end",scope_end) + B("clock_valid",valid));
    emit("footer",footer_tick,N("calls",c.calls) + N("retained",c.records.size()) + N("dropped",c.dropped) +
         N("events",c.events.size()) + N("event_drops",c.event_drops) + N("payload_bytes",c.payload) + N("unknown",unknown) +
         S("first_diagnostic",Name(first)) + B("cleanup_ok",options.cleanup_ok) + B("finalization_ok",options.finalization_ok) +
         B("clock_valid",valid) + B("diagnostic_complete",complete) + B("self_close_measured",false) + B("recovery_accepted",false));
    std::string text;
    for (const auto &line : lines) text += line;
    if (lines.size() > c.limits.rows || text.size() > c.limits.bytes) return {false,false,Error::Writer};
    auto partial = path; partial += ".partial";
    if (std::filesystem::exists(path) || std::filesystem::exists(partial)) throw std::runtime_error("Fresh output required");
    std::ofstream file(partial,std::ios::binary);
    file.write(text.data(),static_cast<std::streamsize>(options.write_fault ? text.size()/2 : text.size()));
    file.flush(); const bool written = static_cast<bool>(file); file.close();
    if (!written || file.fail() || options.write_fault) return {false,false,Error::Writer};
    // The final write/close interval is not retroactively described as measured.
    // A returning late/invalid close check withholds publication of a success.
    (void)stamp();
    if (complete && (first != Error::None || !valid)) return {false,false,first};
    if (options.publish_fault) throw std::runtime_error("HOST TEST publication failure");
    std::filesystem::rename(partial,path);
    return {true,complete,first};
    } catch (...) { return {false,false,Error::Writer}; }
}
} // namespace diagnostic_v1
