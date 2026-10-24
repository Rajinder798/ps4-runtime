// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once
#include "../pnp_readiness_v2/pnp_coverage_v2.h"
#include <span>
#include <variant>

// HOST TEST contract only. No Windows provider, acquisition adapter or live mode.
namespace diagnostic_v1 {
using namespace pnp_v2;
constexpr unsigned RecordCap = 64, PayloadCap = 1048576, RowCap = 4096,
                   ByteCap = 1048576, DepthCap = 32, EventCap = 1024;
struct Clock {
    virtual ~Clock() = default;
    virtual Tick Now() = 0;
    virtual Tick Frequency() = 0;
};
enum class Kind { Devnodes, Interfaces, Lookup, Properties, Key };
enum class Error { None, Clock, Time, Records, Payload, Events, Capture, Replay,
                   Unknown, Cleanup, Writer };
const char *Name(Kind);
const char *Name(Error);
struct Limits {
    unsigned records = RecordCap, payload = PayloadCap, events = EventCap;
    unsigned rows = RowCap, bytes = ByteCap;
};
using Value = std::variant<std::monostate, Enumeration, Lookup, Node, Key>;
using Borrowed = std::variant<std::monostate, const Enumeration *, const Lookup *, const Node *, const Key *>;
struct Record {
    std::uint64_t ordinal = 0;
    Kind kind = Kind::Devnodes;
    Id id = 0; // transient only; never serialized
    bool threw = false;
    Value value;
};
struct Event {
    std::uint64_t ordinal = 0;
    Kind kind = Kind::Devnodes;
    bool threw = false;
    Tick tick = 0;
};
struct Capture {
    Limits limits;
    std::vector<Record> records;
    std::vector<Event> events;
    std::uint64_t calls = 0, dropped = 0, event_drops = 0;
    unsigned payload = 0;
    Tick frequency = 0, start = 0, deadline = -1, last = 0, native_end = 0, freeze_end = 0;
    bool clock_valid = true;
    Error first = Error::None;
};
class Frozen {
    Capture capture;
    explicit Frozen(Capture &&c) : capture(std::move(c)) {}
    friend class Recorder;
public:
    const Capture &View() const noexcept { return capture; }
};
class Recorder final : public Provider {
    Provider &provider;
    Clock &clock;
    Capture capture;
    unsigned copy_fault_at;
    bool consumed = false;
    Tick Stamp() noexcept;
    void Store(Kind, Id, Borrowed, bool) noexcept;
    void Fail(Error) noexcept;
public:
    Recorder(Provider &, Clock &, Limits = {}, unsigned host_copy_fault_at = 0) noexcept;
    Enumeration Devnodes() override;
    Enumeration Interfaces(Bus) override;
    Lookup InterfaceNode(std::wstring_view, Bus) override;
    Node Properties(Id) override;
    Key InstanceKey(Id) override;
    // Consumes this capture epoch. Do not issue more mandatory calls in that epoch.
    Frozen Freeze() && noexcept;
};
class Replay {
    std::map<Id, std::vector<Node>> cache; // independent cache, ordered observations
    unsigned unknown = 0;
public:
    explicit Replay(const Frozen &);
    std::vector<Node> Observations(Id);
    unsigned Unknown() const noexcept { return unknown; }
};
struct Native {
    Tick frequency = 0, first_qpc = 0;
    unsigned first_reason = 0;
    bool ready = false, coverage = false, exception = false;
    bool cleanup_ok = false, collection_complete = false; // native summary outcomes
};
struct Options {
    bool replay_fault = false, missing_request = false, cleanup_ok = true,
         finalization_ok = true, write_fault = false, publish_fault = false;
};
struct Result { bool published = false, complete = false; Error diagnostic = Error::None; };
// Publishes a fresh file only after successful write/flush/close. A partial file
// is failure evidence, never the published contract. Native proof is read-only.
Result Finish(const std::filesystem::path &, const Frozen &, const Native &, Clock &, Options = {});
} // namespace diagnostic_v1
