// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
// All data here is synthetic. This executable never constructs WindowsProvider.
#include "pnp_coverage_v1.h"
#ifdef _WIN32
#include "pnp_windows_v1.h"
#endif
#include <functional>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <thread>

using namespace pnp_v1;
namespace {
void Check(bool b) {
    if (!b)
        throw std::runtime_error("Host PnP assertion failed");
}
struct Fake final : Provider {
    std::map<Id, Node> nodes;
    Enumeration present, usb, hid;
    Lookup lookup;
    std::uint32_t key_code = 0;
    unsigned lookups = 0;
    unsigned delay_ms = 0;
    Enumeration Devnodes() override {
        return present;
    }
    Enumeration Interfaces(Bus b) override {
        return b == Bus::Usb ? usb : hid;
    }
    Lookup InterfaceNode(std::wstring_view path, Bus) override {
        Check(path == L"PRIVATE-opaque-SERIAL-11:22:33:44:55:66");
        ++lookups;
        return lookup;
    }
    Node Properties(Id id) override {
        if (delay_ms) {
            auto wait = delay_ms;
            delay_ms = 0;
            std::this_thread::sleep_for(std::chrono::milliseconds(wait));
        }
        if (nodes.contains(id))
            return nodes.at(id);
        Node n;
        n.id = id;
        n.enum_code = 13;
        return n;
    }
    Key InstanceKey(Id id) override {
        return {L"PRIVATE-SERIAL-INSTANCE-" + std::to_wstring(id), key_code};
    }
};
Node NodeOf(Id id, Bus bus, Hardware hw, Id parent = 0) {
    Node n;
    n.id = id;
    n.bus = bus;
    n.hardware = hw;
    n.parent = parent;
    n.enum_code = 0;
    n.hw_code = 0;
    n.compatible_code = 0;
    n.parent_code = parent ? 0 : 13;
    n.status_code = 0;
    n.status = 8;
    n.enumerator_valid = true;
    n.hardware_valid = true;
    n.compatible_valid = true;
    return n;
}
Fake Good() {
    Fake p;
    p.nodes.emplace(1, NodeOf(1, Bus::Usb, Hardware::UsbParent));
    p.nodes[1].composite = true;
    p.nodes.emplace(2, NodeOf(2, Bus::Usb, Hardware::UsbFunction, 1));
    p.nodes.emplace(3, NodeOf(3, Bus::Hid, Hardware::Hid, 2));
    p.nodes.emplace(4, NodeOf(4, Bus::Other, Hardware::Other));
    p.present.nodes = {1, 2, 3, 4};
    p.usb.interfaces = {{1, 1, 0, 122}};
    p.hid.interfaces = {{3, 1, 0, 122}};
    p.lookup.iface = {3, 1, 0, 122};
    return p;
}
void Policy() {
    Check(HardwareIds({L"USB\\VID_054C&PID_0CE6&REV_0100", L"USB\\VID_054C&PID_0CE6"}) ==
          Hardware::UsbParent);
    Check(HardwareIds({L"usb\\vid_054c&pid_0ce6&mi_03"}) == Hardware::UsbFunction);
    Check(HardwareIds({L"HID\\VID_054C&PID_0CE6&MI_03&COL01"}) == Hardware::Hid);
    for (auto s : {L"USB\\VID_9999&PID_0CE6", L"HID\\VID_054C&PID_0CE7", L"HID_DEVICE_SYSTEM_GAME"})
        Check(HardwareIds({s}) == Hardware::Other);
    for (auto s : {L"USB\\VID_054C&PID_0CE60", L"USB\\VID_054C&PID_0CE6&FAKE", L"USB\\VID_054C",
                   L"HID\\VID_054C&PID_ZZZZ"})
        Check(HardwareIds({s}) == Hardware::Malformed);
    Check(HardwareIds({}) == Hardware::Missing);
    Check(HardwareIds({}, false) == Hardware::Malformed);
    Check(HardwareIds({L"USB\\VID_054C&PID_0CE6", L"USB\\VID_9999&PID_0CE6"}) ==
          Hardware::Malformed);
    std::vector<std::wstring> out;
    const wchar_t good[] = {L'U', L'S', L'B', 0, 0}, bad[] = {L'U', L'S', L'B', 0};
    Check(DecodeMultiSz(good, 5, out) && out.size() == 1);
    Check(!DecodeMultiSz(bad, 4, out));
    auto p = Good();
    auto r = Resolve(p, 3);
    Check(r.outcome == Outcome::Intended && r.root == 1 && r.role == Role::HidChild &&
          r.depth == 2);
    p.nodes[3].hardware = Hardware::Other;
    r = Resolve(p, 3);
    Check(r.outcome == Outcome::Intended && r.role == Role::RelatedHid);
    p.nodes.erase(1);
    Check(Resolve(p, 3).outcome == Outcome::Indeterminate);
    p = Good();
    p.nodes[2].parent = 3;
    Check(Resolve(p, 3).outcome == Outcome::Indeterminate);
    p = Good();
    p.nodes[3].hardware = Hardware::Missing;
    Check(Resolve(p, 3).outcome == Outcome::Indeterminate);
    p = Good();
    p.nodes[3].bus = Bus::Usb;
    Check(Resolve(p, 3).outcome == Outcome::Indeterminate);
    p = Good();
    p.nodes[3].hardware = Hardware::Other;
    p.nodes[3].bus = Bus::Other;
    Check(Resolve(p, 3).outcome == Outcome::Unmatched);
    p = Good();
    for (Id i = 10; i < 20; ++i)
        p.nodes[i] = NodeOf(i, Bus::Hid, Hardware::Other, i + 1);
    p.nodes[3].parent = 10;
    Check(Resolve(p, 3).outcome == Outcome::Indeterminate && Resolve(p, 3).depth == ParentCap);
    auto q = std::make_unique<Queue>();
    for (unsigned i = 0; i < QueueCap + 1; ++i)
        q->Receive(Bus::Usb, 0, L"opaque", 7, Ticks());
    Check(q->Stats().dropped == 1 && q->Drain().size() == QueueCap);
    q->Receive(Bus::Hid, 1, L"opaque", 6, Ticks());
    Check(!q->Drain().at(0).valid);
#ifdef _WIN32
    WindowsCallbackHostTests();
#endif
}
void Fixture(const std::filesystem::path &folder, const std::string &name, Fake p,
             const std::function<void(Fake &, Collector &, Queue &)> &body = {}) {
    Trace trace(folder / (name + ".jsonl"), true);
    auto q = std::make_unique<Queue>();
    Collector c(p, trace);
    const auto begin = Ticks();
    trace.Session(MaxDurationMs, begin);
    trace.Registration(Bus::Usb, 0);
    trace.Registration(Bus::Hid, 0);
    if (body)
        body(p, c, *q);
    else {
        q->Receive(Bus::Hid, 0, L"PRIVATE-opaque-SERIAL-11:22:33:44:55:66", 45, Ticks());
        c.Notifications(*q);
        c.Snapshot();
    }
    c.QueueSummary(*q);
    trace.Registration(Bus::Usb, 0, true);
    trace.Registration(Bus::Hid, 0, true);
    trace.Stopped(begin, Ticks(), true);
    trace.Cleanup(0);
    trace.Finish(c.Complete(), true);
}
void Fixtures(const std::filesystem::path &folder) {
    std::filesystem::create_directory(folder);
    Fixture(folder, "intended", Good());
    auto p = Good();
    p.nodes[3].hardware = Hardware::Other;
    Fixture(folder, "related-hid", p);
    p = Good();
    p.nodes[1].hardware = Hardware::Other;
    p.nodes[2].hardware = Hardware::Other;
    p.nodes[3].hardware = Hardware::Other;
    Fixture(folder, "unmatched", p);
    p = Good();
    p.nodes[3].hw_code = 37;
    p.nodes[3].hardware = Hardware::Missing;
    Fixture(folder, "missing-hardware", p);
    p = Good();
    p.nodes[3].hardware = Hardware::Malformed;
    Fixture(folder, "malformed-hardware", p);
    p = Good();
    p.nodes.erase(1);
    p.present.nodes = {2, 3, 4};
    p.usb.interfaces.clear();
    Fixture(folder, "parent-unavailable", p);
    p = Good();
    p.nodes.emplace(5, NodeOf(5, Bus::Usb, Hardware::UsbParent));
    p.present.nodes.push_back(5);
    Fixture(folder, "multiple", p);
    p = Good();
    p.usb.interfaces.clear();
    p.hid.interfaces.clear();
    Fixture(folder, "node-without-interface", p);
    p = Good();
    p.present.nodes.clear();
    Fixture(folder, "notice-without-present-node", p);
    p = Good();
    p.lookup.code = 433;
    Fixture(folder, "removal-lookup-failed", p, [](Fake &, Collector &c, Queue &q) {
        q.Receive(Bus::Hid, 1, L"PRIVATE-opaque-SERIAL-11:22:33:44:55:66", 45, Ticks());
        c.Notifications(q);
        c.Snapshot();
    });
    p = Good();
    p.present.code = 5;
    p.present.complete = false;
    p.present.nodes.clear();
    Fixture(folder, "enumeration-failed", p);
    p = Good();
    p.present.code = 234;
    p.present.complete = false;
    p.present.nodes = {1};
    Fixture(folder, "enumeration-partial", p);
    p = Good();
    p.hid.complete = false;
    p.hid.code = 5;
    Fixture(folder, "interface-enumeration-failed", p);
    p = Good();
    p.hid.interfaces[0].code = 433;
    Fixture(folder, "interface-detail-failed", p);
    p = Good();
    p.nodes[3].status = 0x400;
    p.nodes[3].problem = 10;
    Fixture(folder, "not-started", p);
    p = Good();
    p.nodes[3].status_code = 13;
    Fixture(folder, "status-unavailable", p);
    p = Good();
    p.nodes[3].parent = 3;
    Fixture(folder, "parent-cycle", p);
    p = Good();
    p.nodes[3].resource_limited = true;
    p.nodes[3].enumerator_valid = false;
    p.nodes[3].enum_code = NotQueried;
    Fixture(folder, "metadata-resources", p);
    p = Good();
    p.nodes[3].enumerator_valid = false;
    Fixture(folder, "malformed-enumerator", p);
    p = Good();
    p.nodes[3].compatible_valid = false;
    Fixture(folder, "optional-compatible-malformed", p);
    p = Good();
    p.key_code = 37;
    Fixture(folder, "key-unavailable", p);
    p = Good();
    p.hid.interfaces[0].flags = 0;
    Fixture(folder, "inactive-interface", p);
    p = Good();
    p.present.nodes.clear();
    p.usb.interfaces.clear();
    p.hid.interfaces.clear();
    Fixture(folder, "notice-snapshot-disagreement", p);
    Fixture(folder, "empty-complete", p, [](Fake &, Collector &c, Queue &) { c.Snapshot(); });
    p = Good();
    p.present.complete = false;
    p.present.nodes.clear();
    p.usb.interfaces.clear();
    p.hid.interfaces.clear();
    Fixture(folder, "empty-incomplete", p);
    Fixture(folder, "queue-overflow", Good(), [](Fake &, Collector &c, Queue &q) {
        for (unsigned i = 0; i < QueueCap + 1; ++i)
            q.Receive(Bus::Hid, 0, L"PRIVATE-opaque-SERIAL-11:22:33:44:55:66", 45, Ticks());
        c.Notifications(q);
        c.Snapshot();
    });
    Fixture(folder, "malformed-callback", Good(), [](Fake &, Collector &c, Queue &q) {
        q.Receive(Bus::Hid, 0, nullptr, 0, Ticks(), false);
        c.Notifications(q);
        c.Snapshot();
    });
    Fixture(folder, "clock-reversal", Good(), [](Fake &, Collector &c, Queue &q) {
        auto t = Ticks();
        q.Receive(Bus::Hid, 0, L"PRIVATE-opaque-SERIAL-11:22:33:44:55:66", 45, t);
        q.Receive(Bus::Hid, 0, L"PRIVATE-opaque-SERIAL-11:22:33:44:55:66", 45, t - 1);
        c.Notifications(q);
        c.Snapshot();
    });
    Fixture(folder, "relevant-cap", Good(), [](Fake &f, Collector &c, Queue &) {
        for (Id i = 10; i < 10 + RelevantCap; ++i) {
            f.nodes[i] = NodeOf(i, Bus::Hid, Hardware::Hid, 2);
            f.present.nodes.push_back(i);
        }
        c.Snapshot();
    });
    Fixture(folder, "node-cap", Good(), [](Fake &f, Collector &c, Queue &) {
        f.present.nodes.resize(NodeCap + 1, 4);
        c.Snapshot();
    });
    Fixture(folder, "token-cap", Good(), [](Fake &f, Collector &c, Queue &) {
        for (Id i = 10; i <= 10 + TokenCap; ++i) {
            f.present.nodes = {i};
            f.nodes[i] = NodeOf(i, Bus::Usb, Hardware::UsbParent);
            f.usb.interfaces.clear();
            f.hid.interfaces.clear();
            c.Snapshot();
        }
    });
    Fixture(folder, "lookup-cleanup-error", Good(), [](Fake &f, Collector &c, Queue &q) {
        f.lookup.cleanup_code = 5;
        q.Receive(Bus::Hid, 0, L"PRIVATE-opaque-SERIAL-11:22:33:44:55:66", 45, Ticks());
        c.Notifications(q);
        c.Snapshot();
    });
    Fixture(folder, "scan-overhead", Good(), [](Fake &f, Collector &c, Queue &) {
        f.delay_ms = 275;
        c.Snapshot();
    });
    Fixture(folder, "drain-overhead", Good(), [](Fake &f, Collector &c, Queue &q) {
        f.delay_ms = 275;
        q.Receive(Bus::Hid, 0, L"PRIVATE-opaque-SERIAL-11:22:33:44:55:66", 45, Ticks());
        c.Notifications(q);
        c.Snapshot();
    });
    Fixture(folder, "late-cadence", Good(), [](Fake &, Collector &c, Queue &) {
        c.Snapshot();
        std::this_thread::sleep_for(std::chrono::milliseconds(2400));
        c.Snapshot();
    });
    // Writer exhaustion preserves a reserved first failure and separate cleanup.
    {
        Trace trace(folder / "storage-limit.jsonl", true, 4096, 8);
        auto f = Good();
        Collector c(f, trace);
        trace.Session(MaxDurationMs, Ticks());
        trace.Registration(Bus::Usb, 0);
        trace.Registration(Bus::Hid, 0);
        try {
            c.Snapshot();
            Check(false);
        } catch (const std::runtime_error &) {
            trace.Fail(Failure::Resources);
        }
        trace.Cleanup(5);
        trace.Finish(false, false);
    }
    {
        Trace trace(folder / "registration-cleanup-error.jsonl", true);
        trace.Session(MaxDurationMs, Ticks());
        trace.Registration(Bus::Usb, 5);
        trace.Fail(Failure::Internal); // Must not replace the original registration failure.
        trace.Cleanup(35);
        trace.Finish(false, false);
    }
    // Exclusive create must never truncate an existing stream.
    bool rejected = false;
    try {
        Trace duplicate(folder / "intended.jsonl", true);
    } catch (...) {
        rejected = true;
    }
    Check(rejected);
}
} // namespace
int main(int argc, char **argv) {
    try {
        Policy();
        if (argc == 3 && std::string_view(argv[1]) == "--host-test")
            Fixtures(std::filesystem::path(argv[2]));
        else if (argc != 1)
            return 2;
        std::cout << "host-test only: property/ancestry/callback policies passed; no device APIs "
                     "invoked\n";
        return 0;
    } catch (const std::exception &e) {
        std::cerr << e.what() << '\n';
        return 1;
    }
}
