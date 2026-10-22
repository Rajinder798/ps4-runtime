// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once
#include "../pnp_readiness_v2/pnp_coverage_v2.h"
#include <functional>
#include <optional>
#include <set>

// Companion evidence only. No live executable, registrations, settings or SDL.
namespace rejection_v1 {
using namespace pnp_v2;
constexpr unsigned DetailCap = 64, RelationshipCap = 128, EntryCap = 64;
constexpr unsigned CacheCap = NodeCap + 2 * InterfaceCap + ParentCap;
constexpr unsigned DiagnosticMs = 25, ByteCap = 1048576, RowCap = 4096;
struct Property {
    std::uint32_t code = NotQueried, type = 0, bytes = 0;
    std::vector<wchar_t> data; // transient, bounded UTF-16 code units; NEVER serialized
};
struct RawNode {
    Property enumerator, hardware, compatible;
    Id parent = 0;
    std::uint32_t parent_code = NotQueried, status_code = NotQueried, status = 0, problem = 0;
};
struct Root {
    Id id = 0;
    std::uint32_t code = NotQueried;
};
struct Source {
    virtual ~Source() = default;
    virtual Enumeration Devnodes() = 0;
    virtual Enumeration Interfaces(Bus) = 0;
    virtual RawNode Read(Id) = 0;
    virtual Root TreeRoot() = 0; // independent successful root lookup, not inferred code 13
    virtual Key InstanceKey(Id) = 0;
};
struct Shape {
    std::uint32_t code = NotQueried, type = 0;
    std::string length = "unknown", decoding = "not_queried", shape = "none";
    std::string order = "none", relationship = "not_decoded", pair = "none";
    unsigned strings = 0;
    int first = -1;
    bool count_known = false, complete_pair = false;
    Reason original = Reason::None;
};
Shape Inspect(const Property &);
struct Fact {
    Node node;
    Shape shape, enumerator_shape;
    RawNode links; // only parent/status fields retained; property buffers cleared
};
class Acquisition final : public Provider {
    Source &source;
    std::map<Id, Fact> facts;
    Fact limited;

  public:
    explicit Acquisition(Source &s) : source(s) {}
    void Reset();
    const Fact &Read(Id);
    Enumeration Devnodes() override;
    Enumeration Interfaces(Bus) override;
    Lookup InterfaceNode(std::wstring_view, Bus) override; // unsupported: no raw notifications
    Node Properties(Id) override;
    Key InstanceKey(Id) override;
    Root TreeRoot() { return source.TreeRoot(); }
};
class Writer {
    void *file = nullptr;
    std::uint64_t bytes = 0, rows = 0, cap, row_cap;
    Tick last = 0;
    bool broken = false, failed = false, finished = false;
    unsigned fault_after = 0;

  public:
    Writer(const std::filesystem::path &, bool host_test, unsigned byte_cap = ByteCap,
           unsigned rows_cap = RowCap, unsigned host_write_fault_after = 0);
    ~Writer();
    bool Append(std::string_view event, const std::string &fields, bool reserved = false);
    void Fail(std::string_view fixed_reason);
    void Finish(unsigned original_first_failure, bool original_cleanup_ok);
    bool Good() const { return !broken && !failed && finished; }
    bool Broken() const { return broken; }
};
// All extra work occurs inside frozen Collector::Snapshot's measured budget.
// Snapshot detail/attribution never supplies acceptance. Provider methods are
// bounded synchronous calls; an OS stall is detected, not represented as on time.
class Companion final : public Provider {
    Acquisition &acquisition;
    Writer &writer;
    std::set<Id> present, targets;
    std::map<Id, unsigned> tokens;
    Root tree_root;
    bool present_complete = false, details_complete = true;
    unsigned sample = 0, details = 0, omitted = 0, total = 0, target = 0, other = 0;
    unsigned unknown = 0, inactive = 0, hid_own = 0, node_unknown = 0, interface_unknown = 0;
    unsigned contexts = 0, context_unknown = 0;
    Tick begin = 0, diagnostic_deadline = 0;
    std::map<std::string, unsigned> reasons;
    unsigned Token(Id);
    void Attempt(Id, std::string_view source, unsigned flags);

  public:
    Companion(Acquisition &a, Writer &w) : acquisition(a), writer(w) {}
    Enumeration Devnodes() override;
    Enumeration Interfaces(Bus) override;
    Lookup InterfaceNode(std::wstring_view, Bus) override;
    Node Properties(Id) override;
    Key InstanceKey(Id) override;
    void EndSnapshot(bool original_ready);
};
} // namespace rejection_v1
