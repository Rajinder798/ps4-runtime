// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
// HOST TEST ONLY. This executable does not link a Windows acquisition adapter.
#include "snapshot_v1.h"
#include "snapshot_build_v1.h"
#include <iostream>
#include <thread>
using namespace snapshot_v1;
namespace {
Property Text(const std::wstring &s, bool list = false) {
    Property p;
    p.code = 0;
    p.type = list ? 0x2012 : 0x12;
    p.data.assign(s.begin(), s.end());
    p.data.push_back(0);
    if (list && !s.empty())
        p.data.push_back(0);
    p.bytes = static_cast<unsigned>(p.data.size() * 2);
    return p;
}
RawNode Node(const wchar_t *bus, const std::wstring &ids, Id parent = 9000) {
    RawNode n;
    n.enumerator = Text(bus);
    n.hardware = Text(ids, true);
    n.compatible = Text(L"", true);
    n.parent = parent;
    n.parent_code = n.status_code = 0;
    n.status = 8;
    return n;
}
struct Fake final : Source {
    std::map<Id, RawNode> nodes;
    Enumeration present, usb, hid;
    Root root{9000, 0};
    unsigned delay = 0, snapshots = 0;
    Enumeration Devnodes() override {
        if (++snapshots != 1)
            throw std::runtime_error("More than one snapshot");
        if (delay)
            std::this_thread::sleep_for(std::chrono::milliseconds(delay));
        return present;
    }
    Enumeration Interfaces(Bus b) override { return b == Bus::Usb ? usb : hid; }
    RawNode Read(Id id) override { return nodes.contains(id) ? nodes.at(id) : RawNode{}; }
    Root TreeRoot() override { return root; }
    Key InstanceKey(Id id) override { return {L"HOST-PRIVATE-SERIAL-" + std::to_wstring(id), 0}; }
};
Fake Good() {
    Fake f;
    f.nodes[1] = Node(L"USB", L"USB\\VID_054C&PID_0CE6");
    f.nodes[2] = Node(L"USB", L"USB\\VID_054C&PID_0CE6&MI_03", 1);
    f.nodes[3] = Node(L"HID", L"HID\\VID_054C&PID_0CE6&MI_03", 2);
    f.present.nodes = {1, 2, 3};
    f.usb.interfaces = {{1, 1, 0, 122}};
    f.hid.interfaces = {{3, 1, 0, 122}};
    return f;
}
void Configure(Fake &f, const std::string &mode) {
    if (mode == "good")
        return;
    if (mode == "writer-fault" || mode == "cleanup-fault") {
        f.nodes[3].hardware = Text(L"", true);
        return;
    }
    if (mode == "missing-hid") {
        f.nodes[3] = Node(L"USB", L"USB\\VID_054C&PID_0CE6&MI_00", 1);
        f.hid.interfaces.clear();
    } else if (mode == "historical-root") {
        f.nodes[5] = Node(L"USB", L"USB\\VID_054C&PID_0CE6");
        f.nodes[5].status_code = 13;
        f.usb.interfaces.push_back({5, 0, 0, 122});
    } else if (mode == "own-target" || mode == "own-other" || mode == "own-unknown") {
        f.nodes[3].hardware = Text(L"", true);
        f.nodes[3].parent = mode == "own-target" ? 1U : mode == "own-other" ? 9000U : 9999U;
    } else if (mode == "partial") {
        f.nodes[3].hardware = Text(L"HID\\VID_045E&UP:FA00_U:00F5", true);
    } else if (mode == "full-partial") {
        std::wstring ids = L"HID\\VID_054C&PID_0CE6";
        ids.push_back(0);
        ids += L"HID\\VID_054C&UP:0001_U:0005";
        f.nodes[3].hardware = Text(ids, true);
    } else if (mode == "malformed") {
        f.nodes[3].hardware.data.back() = L'X';
    } else if (mode == "empty") {
        f.nodes[3].hardware = Text(L"", true);
    } else if (mode == "unsupported") {
        f.nodes[3].hardware = Text(L"HID\\PRIVATE-OPAQUE-SERIAL", true);
    } else if (mode == "detail-cap") {
        for (Id id = 20; id < 100; ++id) {
            f.nodes[id] = Node(L"HID", L"", 1);
            f.present.nodes.push_back(id);
        }
    } else if (mode == "query-timeout") {
        f.delay = 280;
    } else if (mode == "exact-counts") {
        f = Good();
        f.nodes[3] = Node(L"USB", L"USB\\VID_054C&PID_0CE6&MI_00", 1);
        f.hid.interfaces.clear();
        for (Id id = 4; id <= 258; ++id) {
            f.nodes[id] = Node(L"PCI", L"");
            f.present.nodes.push_back(id);
        }
        for (Id id = 300; id < 327; ++id) {
            f.nodes[id] = Node(L"HID",
                               id < 311   ? L"HID\\VID_054C&UP:0001_U:0005"
                               : id < 315 ? L""
                                          : L"HID\\PRIVATE-OPAQUE-SERIAL",
                               1);
            f.present.nodes.push_back(id);
        }
        f.usb.interfaces.push_back({3, 0, 0, 122});
        for (Id id = 300; id < 311; ++id)
            f.usb.interfaces.push_back({id, 1, 0, 122});
        for (Id id = 311; id < 314; ++id)
            f.hid.interfaces.push_back({id, 1, 0, 122});
        for (Id id = 315; id < 324; ++id)
            f.hid.interfaces.push_back({id, 1, 0, 122});
        for (Id id = 4; id < 13; ++id)
            f.hid.interfaces.push_back({id, 1, 0, 122});
    } else {
        throw std::runtime_error("Unknown HOST TEST scenario");
    }
}
} // namespace
int main(int argc, char **argv) {
    if (argc == 2 && std::string_view(argv[1]) == "--identity-only") {
        std::cout << "{\"schema\":\"pnp-snapshot-worker-v1\",\"source_commit\":\""
                  << SNAPSHOT_SOURCE_COMMIT << "\",\"device_queries\":0}\n";
        return 0;
    }
    if (argc != 4 || std::string_view(argv[1]) != "--host-test")
        return 2;
    try {
        const std::string mode(argv[2]);
        auto fake = Good();
        Configure(fake, mode);
        std::cout << "HOST TEST: one synthetic snapshot; no device APIs\n";
        return Run(fake, std::filesystem::path(argv[3]), true, mode == "writer-fault" ? 3U : 0U,
                   mode == "cleanup-fault");
    } catch (const std::exception &) {
        std::cerr << "HOST TEST failure; preserve all partial evidence\n";
        return 1;
    }
}
