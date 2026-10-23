// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once
#include "../pnp_rejection_v1/rejection_v1.h"
#include <cstdio>
#include <functional>
#include <string_view>

// HOST ONLY prototype. No Windows acquisition adapter, production worker or HID v1 policy.
namespace stage_ledger_v1 {
using namespace rejection_v1;
constexpr unsigned LedgerRows = 4096, LedgerBytes = 1048576, SourceCalls = 32768;
enum class Stage { PresentEnumeration, SystemRoot, TargetDiscovery, RawProperty,
    AcquisitionCache, Classification, Ancestry, Serialization, InterfaceEnumeration,
    ScopeCompletion, Cleanup, Publication };
const char *Name(Stage);
struct Clock { virtual ~Clock() = default; virtual Tick Now() = 0; };
struct HostSource : Source { // Explicit separate host boundary; WindowsSource is not this type.
    virtual void Cost(Stage) {} // deterministic synthetic work only; no live clock adapter
};
struct Detail {
    unsigned attempt = 0;
    std::string source, reason, relation;
    std::vector<unsigned> chain;
    std::string encoded;
    Tick collected = 0;
};
struct Totals {
    unsigned total = 0, retained = 0, omitted = 0, target = 0, other = 0, unknown = 0;
    unsigned node = 0, interfaces = 0;
    std::map<std::string, unsigned> reasons;
};
class Ledger {
    Clock &clock;
    FILE *file = nullptr;
    unsigned rows = 0, bytes = 0, row_cap, byte_cap, next_id = 0;
    Tick last = 0, start = 0, deadline = -1;
    bool valid_clock = true, begun = false, sink_ok = true, ended = false;
    std::vector<std::pair<unsigned, Tick>> stack;
    void Emit(std::string_view, const std::string &, Tick);
    Tick Stamp();
    void Check(Tick);
  public:
    std::string first_diagnostic;
    Tick diagnostic_qpc = 0, original_qpc = 0;
    unsigned original_reason = 0;
    Ledger(const std::filesystem::path &, Clock &, unsigned cap_rows = LedgerRows,
           unsigned cap_bytes = LedgerBytes);
    ~Ledger();
    void Start();
    unsigned Begin(Stage, bool optional);
    void End(unsigned);
    bool Allowed();
    Tick Last() const { return last; }
    Tick Deadline() const { return deadline; }
    void Fail(std::string_view);
    void OriginalFailure(unsigned, Tick);
    void Anchors(const std::vector<unsigned> &, unsigned system_root, bool discovery_complete, bool present_complete);
    void Publish(const std::vector<Detail> &, const Totals &, bool ready, bool cleanup,
                 const std::function<void(Stage)> &cost);
    void BreakWriter(); // explicit host fault injection; never a live mode
};
class Prototype final : public Provider {
    class Bridge final : public Source {
        Prototype &p;
        void Call();
      public:
        unsigned calls = 0, optional_started_late = 0;
        explicit Bridge(Prototype &owner) : p(owner) {}
        Enumeration Devnodes() override;
        Enumeration Interfaces(Bus) override;
        RawNode Read(Id) override;
        Root TreeRoot() override;
        Key InstanceKey(Id) override;
    } bridge;
    HostSource &source;
    Ledger &ledger;
    Acquisition acquisition;
    bool optional_mode = false, anchor_complete = false, present_complete = false;
    std::set<Id> present, targets;
    std::map<Id, unsigned> tokens;
    Root tree;
    std::vector<Detail> details;
    unsigned Token(Id);
    Fact FactFor(Id, bool optional);
    void Attempt(Id, std::string_view);
    bool Work(Stage, bool optional, const std::function<void()> &);
  public:
    Totals totals;
    Prototype(HostSource &, Ledger &);
    Enumeration Devnodes() override;
    Enumeration Interfaces(Bus) override;
    Lookup InterfaceNode(std::wstring_view, Bus) override;
    Node Properties(Id) override;
    Key InstanceKey(Id) override;
    void Complete(bool ready, const std::function<void()> &cleanup, bool cleanup_ok);
    unsigned SourceCount() const { return bridge.calls; }
    unsigned OptionalStartedLate() const { return bridge.optional_started_late; }
};
} // namespace stage_ledger_v1
