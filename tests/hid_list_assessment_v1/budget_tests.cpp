// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
// HOST TEST only. Actual frozen Collector/Companion, generated clock seam, fake Source.
#include "fake_clock.h"
#include "../pnp_rejection_v1/rejection_v1.h"
#include <fstream>
#include <iostream>
#include <stdexcept>
using namespace rejection_v1;
namespace {
void Check(bool b) { if (!b) throw std::runtime_error("HOST TEST assertion failed"); }
Property Single(std::wstring_view text) {
    Property p; p.code = 0; p.type = 0x12;
    p.data.assign(text.begin(), text.end()); p.data.push_back(0);
    p.bytes = static_cast<unsigned>(p.data.size() * 2); return p;
}
Property Multi(std::initializer_list<std::wstring> ids) {
    Property p; p.code = 0; p.type = 0x2012;
    for (const auto &s : ids) { p.data.insert(p.data.end(), s.begin(), s.end()); p.data.push_back(0); }
    p.data.push_back(0); p.bytes = static_cast<unsigned>(p.data.size() * 2); return p;
}
RawNode Node(std::wstring_view bus, Property hardware, Id parent) {
    RawNode n; n.enumerator = Single(bus); n.hardware = std::move(hardware);
    n.compatible = Multi({}); n.parent = parent; n.parent_code = n.status_code = n.problem = 0;
    n.status = 8; return n;
}
Property Six() {
    return Multi({L"HID\\VID_054C&PID_0CE6&REV_0100&MI_03", L"HID\\VID_054C&PID_0CE6&MI_03",
                  L"HID\\VID_054C&UP:0001_U:0005", L"HID_DEVICE_UP:0001_U:0005", L"HID_DEVICE", L"HID_DEVICE"});
}
Tick Ms(unsigned n) { return host_clock_v1::Hz * n / 1000; }
struct Fake final : Source {
    std::map<Id, RawNode> raw;
    Enumeration nodes, usb, hid;
    Tick enumerate = 0, root_lookup = 0, root_discovery = 0, property = 0, parent = 0, tail = 0;
    Id inject_id = 0; Tick inject_cost = 0;
    bool parent_paid = false;
    unsigned reads = 0, key_calls = 0;
    Enumeration Devnodes() override { host_clock_v1::Advance(enumerate, "enumeration"); return nodes; }
    Root TreeRoot() override { host_clock_v1::Advance(root_lookup, "system_root_lookup"); return {9000, 0}; }
    Enumeration Interfaces(Bus b) override {
        if (b == Bus::Hid) host_clock_v1::Advance(tail, "hid_interface_enumeration");
        return b == Bus::Usb ? usb : hid;
    }
    RawNode Read(Id id) override {
        ++reads;
        if (id == 1) host_clock_v1::Advance(root_discovery, "qualified_root_discovery");
        if (id == 10) host_clock_v1::Advance(property, "raw_property_read");
        if (id >= 1000 && id < 9000 && !parent_paid) {
            parent_paid = true; host_clock_v1::Advance(parent, "parent_acquisition");
        }
        if (id == inject_id) host_clock_v1::Advance(inject_cost, "scheduled_property_read");
        return raw.contains(id) ? raw.at(id) : RawNode{};
    }
    Key InstanceKey(Id id) override {
        ++key_calls;
        return {L"HOST-TEST-PRIVATE-SERIAL-" + std::to_wstring(id), 0};
    }
};
Property Bad(unsigned category) {
    if (category == 0) return Multi({L"HID\\VID_045E&UP:0001_U:0005"});
    if (category == 1) return Multi({});
    return Multi({L"PRIVATE-UNSUPPORTED-SERIAL"});
}
Fake Counts() {
    Fake f;
    f.raw[1] = Node(L"USB", Multi({L"USB\\VID_054C&PID_0CE6"}), 9000);
    f.raw[2] = Node(L"USB", Multi({L"USB\\VID_054C&PID_0CE6&MI_03"}), 1);
    f.raw[3] = Node(L"HID", Six(), 2);
    // Rejected HID startup is deliberately unavailable, matching the evidence gap.
    f.raw[3].status_code = NotQueried; f.raw[3].status = 0;
    f.raw[9000] = Node(L"ROOT", Multi({}), 0);
    f.nodes.nodes = {1, 2, 3};
    f.usb.interfaces = {{1, 1, 0, 122}};
    f.hid.interfaces = {{3, 1, 0, 122}};
    for (unsigned i = 0; i < 26; ++i) {
        Id id = 10 + i;
        f.raw[id] = Node(L"HID", Bad(i < 9 ? 0U : i < 16 ? 1U : 2U), 1000 + id);
        f.raw[1000 + id] = Node(L"PCI", Multi({}), 9000);
        f.nodes.nodes.push_back(id);
    }
    for (unsigned i = 1; i <= 22; ++i) {
        Id id = 100 + i;
        f.raw[id] = Node(L"HID", Bad(i <= 11 ? 0U : 2U), 1000 + id);
        f.raw[1000 + id] = Node(L"PCI", Multi({}), 9000);
        f.hid.interfaces.push_back({id, 0, 0, 122});
    }
    return f;
}
void Run(const std::filesystem::path &base, const std::string &name, Fake f,
         bool cleanup_error = false, unsigned writer_fault = 0) {
    host_clock_v1::Reset();
    const auto out = base / name; Check(std::filesystem::create_directory(out));
    {
        Trace trace(out / "pnp-v2.jsonl", true);
        Writer writer(out / "rejection-v1.jsonl", true, ByteCap, RowCap, writer_fault);
        Acquisition acquisition(f); Companion companion(acquisition, writer);
        Collector collector(companion, trace);
        const auto begin = Ticks(); trace.Session(1000, begin);
        collector.Snapshot();
        companion.EndSnapshot(collector.Ready());
        auto end = Ticks();
        const unsigned first = end - begin > Ms(250) ? 9U : 1U;
        // A subsequent failure must not replace an earlier native first failure.
        if (cleanup_error) { trace.Fail(Failure::Cleanup); writer.Fail("evidence_limit"); }
        trace.Stopped(begin, end, false); trace.Cleanup(cleanup_error ? 13U : 0U);
        trace.Finish(false, !cleanup_error); writer.Finish(first, !cleanup_error);
        Check(!collector.Ready());
    }
    std::ofstream meta(out / "schedule.json");
    meta << "{\"schema\":\"diagnostic-budget-schedule-v1\",\"origin\":\"HOST TEST\",\"frequency\":"
         << host_clock_v1::Hz << ",\"clock_read_step_ticks\":1,\"clock_start\":" << host_clock_v1::Start
         << ",\"provider_reads\":" << f.reads << ",\"key_calls\":" << f.key_calls << ",\"costs\":[";
    bool first = true;
    for (const auto &c : host_clock_v1::Costs()) {
        if (!first) meta << ',';
        first = false;
        meta << "{\"stage\":\"" << c.stage << "\",\"begin\":" << c.begin << ",\"end\":" << c.end << '}';
    }
    meta << "],\"live_evidence\":false}";
    Check(static_cast<bool>(meta));
}
void All(const std::filesystem::path &out) {
    Check(std::filesystem::create_directory(out));
    host_clock_v1::Reset(0); Check(Ticks() == Ticks());
    bool caught = false; try { host_clock_v1::Advance(-1, "invalid"); } catch (...) { caught = true; } Check(caught);
    caught = false; try { host_clock_v1::Reset(-1); } catch (...) { caught = true; } Check(caught);
    Run(out, "fast", Counts());
    auto f = Counts(); f.enumerate = Ms(26); Run(out, "slow-enumeration", f);
    f = Counts(); f.root_lookup = Ms(26); Run(out, "slow-system-root", f);
    f = Counts(); f.root_discovery = Ms(26); Run(out, "slow-qualified-root", f);
    f = Counts(); f.property = Ms(26); Run(out, "slow-property", f);
    f = Counts(); f.parent = Ms(26); Run(out, "slow-parent", f);
    f = Counts(); f.enumerate = Ms(25); Run(out, "deadline-before-first", f);
    f = Counts(); f.enumerate = Ms(20); f.inject_id = 113; f.inject_cost = Ms(5);
    Run(out, "forty-of-fifty", f); Run(out, "forty-of-fifty-repeat", f);
    Run(out, "cleanup-after-first", f, true); Run(out, "writer-after-first", f, false, 47);
    f = Counts(); f.hid.interfaces.clear(); f.tail = Ms(30); Run(out, "deadline-after-all-details", f);
    f.tail = Ms(251); Run(out, "original-before-companion", f);
    f = Counts(); f.enumerate = Ms(251); Run(out, "companion-before-original-overhead", f);
    std::cout << "HOST TEST deterministic schedules: 14\n";
}
} // namespace
int main(int argc, char **argv) try {
    if (argc != 3 || std::string_view(argv[1]) != "--host-test") return 2;
    All(argv[2]); return 0;
} catch (const std::exception &) { std::cerr << "HOST TEST budget failure\n"; return 1; }
