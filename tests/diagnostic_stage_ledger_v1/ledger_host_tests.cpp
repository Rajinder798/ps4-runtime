// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
#include "ledger_v1.h"
#include "../hid_list_assessment_v1/fake_clock.h"
#include <fstream>
#include <iostream>
#include <limits>
#include <stdexcept>
using namespace stage_ledger_v1;
namespace {
void Check(bool b) { if (!b) throw std::runtime_error("HOST TEST assertion"); }
Property Single(std::wstring_view s) {
    Property p; p.code = 0; p.type = 0x12; p.data.assign(s.begin(), s.end()); p.data.push_back(0);
    p.bytes = static_cast<unsigned>(p.data.size() * 2); return p;
}
Property Multi(std::initializer_list<std::wstring> ids) {
    Property p; p.code = 0; p.type = 0x2012;
    for (const auto &s : ids) { p.data.insert(p.data.end(), s.begin(), s.end()); p.data.push_back(0); }
    p.data.push_back(0); p.bytes = static_cast<unsigned>(p.data.size() * 2); return p;
}
RawNode Node(std::wstring_view bus, Property ids, Id parent) {
    RawNode n; n.enumerator = Single(bus); n.hardware = std::move(ids); n.compatible = Multi({});
    n.parent = parent; n.parent_code = n.status_code = 0; n.status = 8; return n;
}
struct Fake final : HostSource {
    std::map<Id, RawNode> raw;
    Enumeration nodes, usb, hid;
    Tick enumerate = 0, raw_delay = 0, parent_delay = 0;
    bool no_root = false;
    std::map<Stage, Tick> costs;
    unsigned serial = 0, serial_expire = 0;
    void Cost(Stage stage) override {
        if (auto it = costs.find(stage); it != costs.end()) {
            host_clock_v1::Advance(it->second, Name(stage)); costs.erase(it);
        }
        if (stage == Stage::Serialization && ++serial == serial_expire) host_clock_v1::Advance(50000, "serialization-expiry");
    }
    Enumeration Devnodes() override { host_clock_v1::Advance(enumerate, "enumeration"); return nodes; }
    Enumeration Interfaces(Bus b) override { return b == Bus::Usb ? usb : hid; }
    Root TreeRoot() override { return no_root ? Root{0, 13} : Root{9000, 0}; }
    RawNode Read(Id id) override {
        if (id == 1) { host_clock_v1::Advance(raw_delay, "raw-acquisition"); raw_delay = 0; }
        if (id == 1010) { host_clock_v1::Advance(parent_delay, "parent-acquisition"); parent_delay = 0; }
        return raw.contains(id) ? raw.at(id) : RawNode{};
    }
    Key InstanceKey(Id id) override { return {L"PRIVATE-HOST-FIXTURE-SERIAL-" + std::to_wstring(id), 0}; }
};
Fake Counts() {
    Fake f;
    f.raw[1] = Node(L"USB", Multi({L"USB\\VID_054C&PID_0CE6"}), 9000);
    f.raw[2] = Node(L"USB", Multi({L"USB\\VID_054C&PID_0CE6&MI_03"}), 1);
    f.raw[3] = Node(L"HID", Multi({L"HID\\VID_054C&PID_0CE6&REV_0100&MI_03", L"HID\\VID_054C&PID_0CE6&MI_03",
        L"HID\\VID_054C&UP:0001_U:0005", L"HID_DEVICE_UP:0001_U:0005", L"HID_DEVICE", L"HID_DEVICE"}), 2);
    f.raw[3].status_code = NotQueried; f.raw[3].status = 0;
    f.raw[9000] = Node(L"ROOT", Multi({}), 0);
    f.nodes.nodes = {1, 2, 3}; f.usb.interfaces = {{1, 1, 0, 122}}; f.hid.interfaces = {{3, 1, 0, 122}};
    auto bad = [](unsigned category) { return category == 0 ? Multi({L"HID\\VID_045E&UP:0001_U:0005"}) :
        category == 1 ? Multi({}) : Multi({L"PRIVATE-HOST-UNKNOWN-SERIAL"}); };
    for (unsigned i = 0; i < 26; ++i) {
        Id id = 10 + i; f.raw[id] = Node(L"HID", bad(i < 9 ? 0U : i < 16 ? 1U : 2U), 1000 + id);
        f.raw[1000 + id] = Node(L"PCI", Multi({}), 9000); f.nodes.nodes.push_back(id);
    }
    for (unsigned i = 1; i <= 22; ++i) {
        Id id = 100 + i; f.raw[id] = Node(L"HID", bad(i <= 11 ? 0U : 2U), 1000 + id);
        f.raw[1000 + id] = Node(L"PCI", Multi({}), 9000); f.hid.interfaces.push_back({id, 0, 0, 122});
    }
    return f;
}
struct FakeClock final : Clock { Tick Now() override { return Ticks(); } };
std::pair<unsigned, Tick> NativeFailure(const std::filesystem::path &path) {
    std::ifstream f(path); std::string line;
    const std::string reason = "\"event\":\"first_failure\",\"reason\":";
    unsigned count = 0;
    while (count++ < 20000 && std::getline(f, line)) {
        if (line.size() > 16384) throw std::runtime_error("Native line cap");
        auto r = line.find(reason), q = line.find("\"qpc\":");
        if (r != line.npos) return {static_cast<unsigned>(std::stoul(line.substr(r + reason.size()))), std::stoll(line.substr(q + 6))};
    }
    return {};
}
void Run(const std::filesystem::path &base, const std::string &name, Fake f, Tick step = 1,
         bool cleanup_fault = false, bool writer_fault = false, unsigned rows_cap = LedgerRows) {
    host_clock_v1::Reset(step); FakeClock clock;
    auto folder = base / name; Check(std::filesystem::create_directory(folder));
    Ledger ledger(folder / "ledger-v1.jsonl", clock, rows_cap);
    Trace trace(folder / "pnp-v2.jsonl", true);
    Prototype prototype(f, ledger); Collector collector(prototype, trace);
    auto begin = Ticks(); trace.Session(1000, begin); collector.Snapshot();
    if (!collector.Ready()) trace.Fail(Failure::Coverage);
    auto observe = [&] { auto [code, qpc] = NativeFailure(folder / "pnp-v2.jsonl"); ledger.OriginalFailure(code, qpc); };
    observe();
    prototype.Complete(collector.Ready(), [&] {
        if (cleanup_fault) trace.Fail(Failure::Cleanup);
        trace.Stopped(begin, Ticks(), false); trace.Cleanup(cleanup_fault ? 13U : 0U); trace.Finish(false, !cleanup_fault);
        observe(); if (writer_fault) ledger.BreakWriter();
    }, !cleanup_fault);
    Check(prototype.totals.total == 50 && prototype.totals.retained + prototype.totals.omitted == 50);
    Check(prototype.OptionalStartedLate() == 0 && !collector.Ready());
    std::ofstream result(folder / "host-result.json");
    result << "{\"origin\":\"HOST TEST\",\"total\":" << prototype.totals.total << ",\"retained\":" << prototype.totals.retained
           << ",\"omitted\":" << prototype.totals.omitted << ",\"first_diagnostic\":\"" << ledger.first_diagnostic
           << "\",\"original_reason\":" << ledger.original_reason << ",\"source_calls\":" << prototype.SourceCount()
           << ",\"optional_started_late\":" << prototype.OptionalStartedLate() << ",\"recovery_accepted\":false}";
}
struct ManualClock final : Clock { Tick value = 1000000; bool throws = false; Tick Now() override {
    if (throws) throw std::runtime_error("Synthetic clock fault");
    return value;
} };
void ClockCases(const std::filesystem::path &base) {
    for (const std::string name : {"clock-backward", "clock-overflow", "clock-exception"}) {
        ManualClock clock;
        if (name == "clock-overflow") clock.value = std::numeric_limits<Tick>::max() - 10;
        auto path = base / name; Check(std::filesystem::create_directory(path));
        Ledger ledger(path / "ledger-v1.jsonl", clock); ledger.Start();
        if (name != "clock-overflow") {
            auto stage = ledger.Begin(Stage::Ancestry, true);
            if (name == "clock-backward") --clock.value; else clock.throws = true;
            ledger.End(stage);
        }
        Check(!ledger.Allowed() && ledger.first_diagnostic == "clock_error");
        ledger.Publish({}, {}, false, true, [](Stage) {});
    }
    host_clock_v1::Reset(); bool rejected = false;
    try { host_clock_v1::Advance(std::numeric_limits<Tick>::max(), "overflow"); } catch (...) { rejected = true; }
    Check(rejected);
}
void All(const std::filesystem::path &out) {
    Check(std::filesystem::create_directory(out));
    Run(out, "fast", Counts());
    auto f = Counts(); f.enumerate = 260000; Run(out, "slow-enumeration", f);
    f = Counts(); f.costs[Stage::SystemRoot] = 260000; Run(out, "slow-system-root", f);
    f = Counts(); f.costs[Stage::TargetDiscovery] = 260000; Run(out, "slow-target-discovery", f);
    f = Counts(); f.raw_delay = 260000; Run(out, "slow-raw-property", f);
    f = Counts(); f.costs[Stage::Ancestry] = 260000; Run(out, "slow-traversal", f);
    f = Counts(); f.parent_delay = 260000; Run(out, "slow-parent-acquisition", f);
    f = Counts(); f.enumerate = 250000; Run(out, "before-first-detail", f, 0);
    f = Counts(); f.enumerate = 200000; f.serial_expire = 41; Run(out, "forty-of-fifty", f);
    Run(out, "repeat-forty-of-fifty", f); Run(out, "writer-after-time-failure", f, 1, false, true);
    Run(out, "cleanup-after-time-failure", f, 1, true);
    f = Counts(); f.costs[Stage::Publication] = 260000; Run(out, "late-publication", f);
    f = Counts(); f.costs[Stage::ScopeCompletion] = 260000; Run(out, "final-tail", f);
    f = Counts(); f.costs[Stage::ScopeCompletion] = 249999; Run(out, "boundary-below", f, 0);
    f.costs[Stage::ScopeCompletion] = 250000; Run(out, "boundary-exact", f, 0);
    f.costs[Stage::ScopeCompletion] = 250001; Run(out, "boundary-above", f, 0);
    f = Counts(); f.enumerate = 2510000; Run(out, "original-overhead", f);
    f = Counts(); f.no_root = true; Run(out, "unknown-root", f);
    f = Counts(); f.raw[3].parent_code = 13; Run(out, "unknown-target-ancestry", f);
    Run(out, "cleanup-only-failure", Counts(), 1, true);
    Run(out, "ledger-row-limit", Counts(), 1, false, false, 32);
    ClockCases(out);
    std::cout << "HOST TEST: 22 provider schedules and 3 clock-fault cases\n";
}
} // namespace
int main(int argc, char **argv) try {
    if (argc != 3 || std::string_view(argv[1]) != "--host-test") return 2;
    All(argv[2]); return 0;
} catch (const std::exception &) { std::cerr << "HOST TEST ledger failure\n"; return 1; }
