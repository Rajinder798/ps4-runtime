// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
// HOST TEST ONLY: this executable links no Windows acquisition adapter.
#include "rejection_v1.h"
#include <fstream>
#include <iostream>
#include <thread>
using namespace rejection_v1;
namespace {
void Check(bool b) {
    if (!b)
        throw std::runtime_error("Host rejection assertion failed");
}
Property Single(const std::wstring &s) {
    Property p;
    p.code = 0;
    p.type = 0x12;
    p.data.assign(s.begin(), s.end());
    p.data.push_back(0);
    p.bytes = static_cast<unsigned>(p.data.size() * 2);
    return p;
}
Property Multi(std::initializer_list<std::wstring> ids) {
    Property p;
    p.code = 0;
    p.type = 0x2012;
    for (const auto &s : ids) {
        p.data.insert(p.data.end(), s.begin(), s.end());
        p.data.push_back(0);
    }
    p.data.push_back(0);
    p.bytes = static_cast<unsigned>(p.data.size() * 2);
    return p;
}
RawNode Node(const wchar_t *bus, std::initializer_list<std::wstring> ids, Id parent = 9000) {
    RawNode n;
    n.enumerator = Single(bus);
    n.hardware = Multi(ids);
    n.compatible = Multi({});
    n.parent = parent;
    n.parent_code = 0;
    n.status_code = 0;
    n.status = 8;
    return n;
}
struct Fake final : Source {
    std::map<Id, RawNode> raw;
    Enumeration present, usb, hid;
    Root root{9000, 0};
    unsigned delay_ms = 0, reads = 0;
    Enumeration Devnodes() override { return present; }
    Enumeration Interfaces(Bus b) override { return b == Bus::Usb ? usb : hid; }
    RawNode Read(Id id) override {
        ++reads;
        if (delay_ms) {
            auto d = delay_ms;
            delay_ms = 0;
            std::this_thread::sleep_for(std::chrono::milliseconds(d));
        }
        return raw.contains(id) ? raw.at(id) : RawNode{};
    }
    Root TreeRoot() override { return root; }
    Key InstanceKey(Id id) override {
        return {L"PRIVATE-INSTANCE-SERIAL-11:22:33:44:55:66-" + std::to_wstring(id), 0};
    }
};
Fake Good() {
    Fake f;
    f.raw[1] = Node(L"USB", {L"USB\\VID_054C&PID_0CE6&REV_0100", L"USB\\VID_054C&PID_0CE6"});
    f.raw[1].compatible = Multi({L"USB\\COMPOSITE"});
    f.raw[2] = Node(L"USB", {L"USB\\VID_054C&PID_0CE6&MI_03"}, 1);
    f.raw[3] = Node(L"HID",
                    {L"HID\\VID_054C&PID_0CE6&REV_0100&MI_03", L"HID\\VID_054C&PID_0CE6&MI_03",
                     L"HID_DEVICE_UP:0001_U:0005", L"HID_DEVICE"},
                    2);
    f.raw[4] = Node(L"PCI", {});
    f.present.nodes = {1, 2, 3, 4};
    f.usb.interfaces = {{1, 1, 0, 122}};
    f.hid.interfaces = {{3, 1, 0, 122}};
    return f;
}
unsigned First(const std::filesystem::path &p) {
    std::ifstream f(p);
    std::string line;
    while (std::getline(f, line)) {
        auto at = line.find("\"event\":\"first_failure\",\"reason\":");
        if (at != std::string::npos)
            return static_cast<unsigned>(std::stoul(line.substr(at + 33)));
    }
    return 0;
}
void Run(const std::filesystem::path &folder, const std::string &name, Fake f,
         unsigned cap = ByteCap, unsigned row_cap = RowCap, unsigned fault = 0,
         bool bad_cleanup = false, unsigned snapshots = 1, bool raw_notice = false) {
    const auto native = folder / (name + ".v2.jsonl"), diag = folder / (name + ".rejection.jsonl");
    Trace trace(native, true);
    Writer writer(diag, true, cap, row_cap, fault);
    Acquisition acquisition(f);
    Companion companion(acquisition, writer);
    Collector collector(companion, trace);
    Queue queue;
    auto begin = Ticks();
    trace.Session(110000, begin);
    trace.Registration(Bus::Usb, 0);
    trace.Registration(Bus::Hid, 0);
    for (unsigned i = 0; i < snapshots; ++i) {
        collector.Snapshot();
        companion.EndSnapshot(collector.Ready());
        if (raw_notice)
            Check(companion.InterfaceNode(L"PRIVATE-NOTIFICATION-SERIAL", Bus::Hid).code ==
                  NotQueried);
        // The unchanged observer rejects complete-but-unready initial topology.
        if (!collector.Ready())
            trace.Fail(Failure::Coverage);
    }
    collector.QueueSummary(queue);
    trace.Registration(Bus::Usb, 0, true);
    trace.Registration(Bus::Hid, 0, true);
    trace.Stopped(begin, Ticks(), true);
    if (bad_cleanup)
        trace.Fail(Failure::Cleanup);
    trace.Cleanup(bad_cleanup ? 1 : 0);
    trace.Finish(collector.Complete(), !bad_cleanup);
    writer.Finish(First(native), !bad_cleanup);
    Check(f.reads <= snapshots * CacheCap);
}
void Fixtures(const std::filesystem::path &folder) {
    std::filesystem::create_directory(folder);
    unsigned variant = 0;
    for (auto suffix : {L"", L"&REV_0100", L"&COL01", L"&REV_0100&COL01", L"&MI_03",
                        L"&REV_0100&MI_03", L"&MI_03&COL01", L"&REV_0100&MI_03&COL01"}) {
        auto f = Good();
        f.raw[3].hardware =
            Multi({std::wstring(L"HID\\VID_054C&PID_0CE6") + suffix, L"HID_DEVICE_UP:0001_U:0005",
                   L"HID_DEVICE_SYSTEM_GAME", L"HID_DEVICE"});
        Run(folder, "canonical-" + std::to_string(variant++), f);
    }
    auto f = Good();
    f.raw[3].hardware = Multi({L"HID\\VID_045E&UP:FA00_U:00F5"});
    Run(folder, "partial", f);
    f.raw[3].hardware = Multi({L"HID\\VID_054C&PID_0CE6&MI_03", L"HID\\VID_054C&UP:0001_U:0005"});
    Run(folder, "full-partial", f);
    f.raw[3].hardware = Multi({L"HID\\VID_054C&UP:0001_U:0005", L"HID\\VID_054C&PID_0CE6&MI_03"});
    Run(folder, "partial-full", f);
    f.raw[3].hardware = Multi({L"HID\\VID_054C&PID_0CE6&MI_03", L"HID\\VID_045E&UP:FA00_U:00F5"});
    Run(folder, "partial-conflict", f);
    f.raw[3].hardware = Multi({L"USB\\VID_054C&PID_0CE6", L"HID\\VID_054C&UP:0001_U:0005"});
    Run(folder, "mixed-bus-context", f);
    f.raw[3].hardware = Multi({L"HID\\VID_054C&PID_0CE6", L"HID\\VID_1111&PID_2222"});
    Run(folder, "conflict", f);
    f.raw[3].hardware = Multi({});
    Run(folder, "missing", f);
    f = Good();
    f.raw[3].hardware.data.back() = L'X';
    Run(folder, "termination", f);
    f = Good();
    f.raw[3].hardware.type = 0x12;
    Run(folder, "property-type", f);
    f = Good();
    f.raw[3].hardware.code = 37;
    Run(folder, "property-api", f);
    f = Good();
    f.raw[3].hardware = Multi({L"HID_DEVICE_UP:0001_U:0005", L"HID_DEVICE"});
    Run(folder, "generic-target", f);
    f.raw[3].parent = 0;
    f.raw[3].parent_code = 37;
    Run(folder, "generic-unknown", f);
    f.raw[3].parent_code = 13;
    Run(folder, "generic-root-code13", f);
    f = Good();
    f.raw[3].hardware = Multi({L"HID\\VID_054C&UP:0001_U:0005"});
    Run(folder, "own-reject-target", f);
    f.raw[3].parent = 9000;
    Run(folder, "own-reject-other", f);
    f.root.code = 13;
    Run(folder, "root-proof-unavailable", f);
    f = Good();
    f.raw[2].hardware = Multi({L"USB\\VID_054C&UP:0001_U:0005"});
    Run(folder, "ancestor-reject", f);
    f.raw[4].parent = 2;
    f.raw[3].parent = 4;
    Run(folder, "transport-boundary", f);
    f = Good();
    f.raw[2].hardware = Multi({L"USB\\VID_1111&PID_2222"});
    Run(folder, "foreign-ancestor", f);
    f = Good();
    f.raw[3].hardware = Multi({});
    f.raw[3].parent = 3;
    Run(folder, "cycle", f);
    f = Good();
    f.raw[3].hardware = Multi({});
    for (Id i = 10; i < 20; ++i)
        f.raw[i] = Node(L"PCI", {}, i + 1);
    f.raw[3].parent = 10;
    Run(folder, "depth", f);
    f = Good();
    f.raw[3].enumerator.type = 0x2012;
    Run(folder, "enumerator-type", f);
    f = Good();
    f.raw[3].enumerator.code = 37;
    Run(folder, "enumerator-api", f);
    f = Good();
    f.raw.erase(3);
    Run(folder, "unclassifiable", f);
    f = Good();
    f.raw[1].hardware = Multi({});
    Run(folder, "no-target-anchor", f);
    f = Good();
    f.raw[5] = Node(L"USB", {L"USB\\VID_054C&PID_0CE6"});
    f.raw[5].status_code = 13;
    f.usb.interfaces.push_back({5, 0, 0, 122});
    Run(folder, "historical-root", f);
    f.raw[5].hardware = Multi({L"HID\\PRIVATE-OPAQUE-SERIAL-11:22:33:44:55:66"});
    Run(folder, "inactive-rejected", f);
    f = Good();
    f.present.nodes = {1, 2, 4};
    f.hid.interfaces.clear();
    Run(folder, "missing-hid", f);
    f = Good();
    f.usb.interfaces[0].code = 433;
    Run(folder, "interface-lookup", f);
    f = Good();
    f.raw[3].hardware.bytes = PropertyBytes + 2;
    Run(folder, "property-limit", f);
    f = Good();
    f.raw[3].hardware.bytes -= 1;
    Run(folder, "odd-length", f);
    f = Good();
    f.raw[3].hardware = Multi({});
    for (unsigned i = 0; i < 65; ++i) {
        auto p = Multi({L"HID_DEVICE"});
        f.raw[3].hardware.data.insert(f.raw[3].hardware.data.end() - 1, p.data.begin(),
                                      p.data.end() - 1);
    }
    f.raw[3].hardware.bytes = static_cast<unsigned>(f.raw[3].hardware.data.size() * 2);
    Run(folder, "entry-cap", f);
    f = Good();
    f.delay_ms = 35;
    f.raw[3].hardware = Multi({L"HID\\VID_054C&UP:0001_U:0005"});
    Run(folder, "diagnostic-time", f);
    f = Good();
    f.delay_ms = 280;
    Run(folder, "scan-time", f);
    f = Good();
    Run(folder, "two-snapshots", f, ByteCap, RowCap, 0, false, 2);
    Run(folder, "raw-notification", f, ByteCap, RowCap, 0, false, 1, true);
    f = Good();
    f.raw[3].hardware = Multi({});
    Run(folder, "cleanup-after-first", f, ByteCap, RowCap, 0, true);
    Run(folder, "writer-fault", f, ByteCap, RowCap, 3);
    // Exact aggregate reproduction, intentionally designed synthetic metadata.
    Fake exact;
    exact.raw[1] = Good().raw[1];
    exact.raw[2] = Good().raw[2];
    exact.raw[3] = Node(L"USB", {L"USB\\VID_054C&PID_0CE6&MI_00"}, 1);
    exact.present.nodes = {1, 2, 3};
    for (Id i = 4; i <= 258; ++i) {
        exact.raw[i] = Node(L"PCI", {});
        exact.present.nodes.push_back(i);
    }
    for (Id i = 300; i < 327; ++i) {
        auto hw = i < 311   ? Multi({L"HID\\VID_054C&UP:0001_U:0005"})
                  : i < 315 ? Multi({})
                            : Multi({L"HID\\PRIVATE-OPAQUE-SERIAL-11:22:33:44:55:66"});
        exact.raw[i] = Node(L"HID", {}, i % 3 == 0 ? 1 : 9000);
        exact.raw[i].hardware = hw;
        exact.present.nodes.push_back(i);
    }
    exact.usb.interfaces = {{1, 1, 0, 122}, {3, 0, 0, 122}};
    // 11 repeated syntax, 3 repeated missing, 9 repeated unrecognized.
    for (Id i = 300; i < 311; ++i)
        exact.usb.interfaces.push_back({i, 1, 0, 122});
    for (Id i = 311; i < 314; ++i)
        exact.hid.interfaces.push_back({i, 1, 0, 122});
    for (Id i = 315; i < 324; ++i)
        exact.hid.interfaces.push_back({i, 1, 0, 122});
    for (Id i = 4; i < 13; ++i)
        exact.hid.interfaces.push_back({i, 1, 0, 122});
    Run(folder, "exact-counts", exact);
    Run(folder, "byte-cap", exact, 4096);
    Run(folder, "row-cap", exact, ByteCap, 8);
    Fake details = Good();
    for (Id i = 20; i < 100; ++i) {
        details.raw[i] = Node(L"HID", {}, 1);
        details.present.nodes.push_back(i);
    }
    Run(folder, "detail-cap", details);
    Fake tokens = Good();
    for (Id i = 100; i < 170; ++i) {
        tokens.raw[i] = Node(L"HID", {}, i + 1000);
        tokens.raw[i + 1000] = Node(L"PCI", {}, 9000);
        tokens.present.nodes.push_back(i);
    }
    Run(folder, "token-cap", tokens);
    Fake cache = Good();
    for (Id i = 10; i < 2054; ++i) {
        cache.raw[i] = Node(L"HID", {}, i + 10000);
        cache.present.nodes.push_back(i);
        cache.raw[i + 10000] = Node(L"PCI", {}, 9000);
    }
    cache.usb.interfaces.clear();
    cache.hid.interfaces.clear();
    for (Id i = 30000; i < 32048; ++i) {
        cache.raw[i] = Node(L"HID", {}, 9000);
        cache.usb.interfaces.push_back({i, 1, 0, 122});
        cache.raw[i + 10000] = Node(L"HID", {}, 9000);
        cache.hid.interfaces.push_back({i + 10000, 1, 0, 122});
    }
    Run(folder, "acquisition-cache-cap", cache);
    // The writer must not truncate an existing file or enable fault injection in live origin.
    bool rejected = false;
    try {
        Writer duplicate(folder / "partial.rejection.jsonl", true);
    } catch (const std::runtime_error &) {
        rejected = true;
    }
    Check(rejected);
    rejected = false;
    try {
        Writer bad(folder / "forbidden.jsonl", false, ByteCap, RowCap, 1);
    } catch (const std::runtime_error &) {
        rejected = true;
    }
    Check(rejected);
}
} // namespace
int main(int argc, char **argv) {
    try {
        if (argc != 3 || std::string_view(argv[1]) != "--host-test")
            return 2;
        Fixtures(std::filesystem::path(argv[2]));
        std::cout << "HOST TEST: raw acquisition, frozen v2 policy and companion fixtures; no "
                     "device APIs\n";
        return 0;
    } catch (const std::exception &) {
        std::cerr << "HOST TEST failed; retain original evidence\n";
        return 1;
    }
}
