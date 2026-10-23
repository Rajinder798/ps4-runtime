// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
// Public synthetic fixtures only; no original six-string list was retained.
#include "assessment_v1.h"
#include "../pnp_readiness_v2/pnp_coverage_v2.h"
#include <algorithm>
#include <charconv>
#include <filesystem>
#include <iostream>
#include <stdexcept>
#include <vector>
using namespace hid_list_v1;
namespace {
unsigned checks = 0;
void Check(bool ok) { ++checks; if (!ok) throw std::runtime_error("HOST TEST assertion failed"); }
std::vector<char16_t> Multi(const std::vector<std::u16string> &ids) {
    std::vector<char16_t> out;
    for (const auto &s : ids) { out.insert(out.end(), s.begin(), s.end()); out.push_back(0); }
    out.push_back(0); return out;
}
Assessment Raw(const std::vector<char16_t> &d, std::uint32_t code = 0, std::uint32_t type = 0x2012) {
    return Assess({code, type, static_cast<std::uint32_t>(d.size() * 2), d});
}
Assessment Test(const std::vector<std::u16string> &ids, Kind kind, Identity identity = Identity::None) {
    auto a = Raw(Multi(ids)); Check(a.kind == kind); Check(a.identity == identity);
    Check(a.OwnTargetHid() == (identity == Identity::TargetHid));
    std::cout << Json(a) << '\n'; return a;
}
std::uint32_t Number(const char *s) {
    std::uint32_t n = 0; auto end = s + std::char_traits<char>::length(s);
    auto parsed = std::from_chars(s, end, n); if (parsed.ec != std::errc{} || parsed.ptr != end) throw std::runtime_error("invalid input");
    return n;
}
void RawCli(char **argv, std::string_view hex) {
    auto code = Number(argv[2]), type = Number(argv[3]), bytes = Number(argv[4]);
    if (hex.size() > PropertyBytes * 2 || hex.size() % 4) throw std::runtime_error("invalid input");
    std::vector<char16_t> units;
    for (std::size_t at = 0; at < hex.size(); at += 4) {
        unsigned n = 0; auto p = std::from_chars(hex.data() + at, hex.data() + at + 4, n, 16);
        if (p.ec != std::errc{} || p.ptr != hex.data() + at + 4) throw std::runtime_error("invalid input");
        units.push_back(static_cast<char16_t>(n));
    }
    std::cout << Json(Assess({code, type, bytes, units})) << '\n';
}
// Hypothetical HOST TEST bridge only: the assessor has no status/ancestry input.
// Frozen Resolve independently requires its own parent proof. No live integration.
struct Fake final : pnp_v2::Provider {
    pnp_v2::Node hid, usb, function;
    bool gap = false, hid_present = true;
    unsigned usb_flags = 1, hid_flags = 1;
    pnp_v2::Enumeration Devnodes() override {
        pnp_v2::Enumeration e; e.nodes = {1, 24};
        if (hid_present) e.nodes.push_back(23);
        if (gap) e.nodes.push_back(77);
        return e;
    }
    pnp_v2::Enumeration Interfaces(pnp_v2::Bus b) override {
        pnp_v2::Enumeration e;
        e.interfaces = {{b == pnp_v2::Bus::Usb ? 1U : 23U, b == pnp_v2::Bus::Usb ? usb_flags : hid_flags, 0, 122}};
        return e;
    }
    pnp_v2::Lookup InterfaceNode(std::wstring_view, pnp_v2::Bus) override { return {}; }
    pnp_v2::Key InstanceKey(pnp_v2::Id id) override { return {L"HOST TEST KEY " + std::to_wstring(id), 0}; }
    pnp_v2::Node Properties(pnp_v2::Id id) override {
        return id == 1 ? usb : id == 24 ? function : id == 23 ? hid : pnp_v2::Node{};
    }
};
Fake Proof(const Assessment &a) {
    Fake f;
    f.usb.id = 1; f.usb.bus = pnp_v2::Bus::Usb; f.usb.hardware = pnp_v2::Hardware::UsbParent;
    f.usb.enum_code = f.usb.hw_code = f.usb.status_code = 0;
    f.usb.enumerator_valid = f.usb.hardware_valid = true; f.usb.status = 8;
    f.hid.id = 23; f.hid.bus = pnp_v2::Bus::Hid;
    f.hid.hardware = a.OwnTargetHid() ? pnp_v2::Hardware::Hid : pnp_v2::Hardware::Other;
    f.hid.enum_code = f.hid.hw_code = 0; f.hid.enumerator_valid = f.hid.hardware_valid = true;
    f.function = f.usb; f.function.id = 24; f.function.hardware = pnp_v2::Hardware::UsbFunction;
    f.function.parent = 1; f.function.parent_code = 0;
    f.hid.parent = 24; f.hid.parent_code = 0;
    return f;
}
void PropertyToPolicy(const Assessment &a) {
    auto f = Proof(a);
    auto r = pnp_v2::Resolve(f, 23);
    Check(r.ancestry_complete && r.root == 1);
    Check(r.node.status_code == pnp_v2::NotQueried && !(r.node.status & 8));
    // Resolving identity/topology alone does not supply node startup status.
    Check(a.OwnTargetHid() && r.role == pnp_v2::Role::HidChild);
    f.hid.parent_code = 13; Check(!pnp_v2::Resolve(f, 23).ancestry_complete);
    f.hid.parent_code = 0; f.hid.hardware = pnp_v2::Hardware::Other;
    Check(pnp_v2::Resolve(f, 23).role != pnp_v2::Role::HidChild);
}
void PolicyCases(const std::filesystem::path &out) {
    Check(std::filesystem::create_directory(out));
    const auto a = Raw(Multi({u"HID\\VID_054C&PID_0CE6&REV_0100&MI_03", u"HID\\VID_054C&PID_0CE6&MI_03",
                             u"HID\\VID_054C&UP:0001_U:0005", u"HID_DEVICE_UP:0001_U:0005", u"HID_DEVICE", u"HID_DEVICE"}));
    auto run = [&](std::string_view name, Fake f, bool ready) {
        auto path = out / (std::string(name) + ".jsonl");
        pnp_v2::Trace trace(path, true); pnp_v2::Collector collector(f, trace);
        auto begin = pnp_v2::Ticks(); trace.Session(1000, begin); collector.Snapshot();
        Check(collector.Ready() == ready);
        trace.Stopped(begin, pnp_v2::Ticks(), false); trace.Cleanup(0); trace.Finish(false, true);
    };
    auto good = Proof(a); good.hid.status_code = 0; good.hid.status = 8;
    run("hypothetical-complete-proof", good, true);
    run("syntax-only-status-unknown", Proof(a), false);
    auto f = good; f.hid.status = 0; run("not-started", f, false);
    f = good; f.hid.status = 0x408; f.hid.problem = 1; run("problem-present", f, false);
    f = good; f.hid.parent_code = 13; run("parent-unproved", f, false);
    f = good; f.gap = true; run("global-gap", f, false);
    f = good; f.hid_flags = 0; run("inactive-hid-interface", f, false);
    f = good; f.usb_flags = 0; run("inactive-usb-interface", f, false);
    f = good; f.hid_present = false; run("hid-not-present", f, false);
    f = good; f.hid.hardware = pnp_v2::Hardware::Other;
    f.hid.hardware_reason = pnp_v2::Reason::UnsupportedDocumentedForm;
    run("related-hid-not-own-identity", f, false);
    auto partial = Raw(Multi({u"HID\\VID_054C&UP:0001_U:0005"}));
    f = Proof(partial); f.hid.status_code = 0; f.hid.status = 8;
    run("partial-context-no-product", f, false);
}
void Tests() {
    const std::u16string pair = u"HID\\VID_054C&PID_0CE6&MI_03";
    auto six = std::vector<std::u16string>{u"HID\\VID_054C&PID_0CE6&REV_0100&MI_03", pair,
        u"HID\\VID_054C&UP:0001_U:0005", u"HID_DEVICE_UP:0001_U:0005", u"HID_DEVICE", u"HID_DEVICE"};
    auto good = Test(six, Kind::CompleteWithContext, Identity::TargetHid);
    Check(good.entries == 6 && good.first_context == 2 && good.first_issue == -1);
    std::vector<wchar_t> frozen;
    for (auto x : Multi(six)) frozen.push_back(static_cast<wchar_t>(x));
    auto old = pnp_v2::AssessProperty(0, 0x2012, static_cast<unsigned>(frozen.size() * 2), frozen.data(), frozen.size());
    Check(old.reason == pnp_v2::Reason::InvalidHardwareSyntax);
    // The first two entries succeed; adding contextual entry index 2 fails v2.
    std::vector<std::wstring> prefix;
    for (unsigned i = 0; i < 3; ++i) {
        prefix.emplace_back(six[i].begin(), six[i].end());
        Check((pnp_v2::AssessIds(prefix).reason == pnp_v2::Reason::None) == (i < 2));
    }
    PropertyToPolicy(good);
    Test({pair}, Kind::Complete, Identity::TargetHid);
    Test({u"hid\\vid_054c&pid_0ce6&mi_03"}, Kind::Complete, Identity::TargetHid);
    Test({u"HID\\VID_045E&PID_0001"}, Kind::Complete, Identity::Other);
    Test({u"USB\\VID_054C&PID_0CE6"}, Kind::Complete, Identity::TargetUsbParent);
    Test({u"USB\\VID_054C&PID_0CE6&MI_03"}, Kind::Complete, Identity::TargetUsbFunction);
    Test({u"USB\\VID_054C&PID_0CE6&REV_0100", u"USB\\VID_054C&PID_0CE6"}, Kind::Complete, Identity::TargetUsbParent);
    for (unsigned mask = 0; mask < 8; ++mask) {
        std::u16string base = u"HID\\VID_054C&PID_0CE6";
        auto full = base;
        if (mask & 1U) full += u"&REV_0100";
        if (mask & 2U) { full += u"&MI_03"; base += u"&MI_03"; }
        if (mask & 4U) { full += u"&COL01"; base += u"&COL01"; }
        Test({full, base, u"HID\\VID_054C&UP:0001_U:0005", u"HID_DEVICE_UP:0001_U:0005"},
             Kind::CompleteWithContext, Identity::TargetHid);
    }
    Test({u"HID\\VID_054C&UP:0001_U:0005"}, Kind::PartialContext);
    Test({u"HID_DEVICE"}, Kind::GenericOnly);
    Test({pair, u"HID_DEVICE"}, Kind::CompleteWithContext, Identity::TargetHid);
    Test({pair, u"UNSUPPORTED_PRIVATE_SERIAL"}, Kind::Unsupported);
    Test({pair, u"HID_DEVICE_SYSTEM_GAME"}, Kind::Unsupported);
    Test({u"UNRECOGNIZED_PRIVATE_SERIAL"}, Kind::Unrecognized);
    Test({pair, u"HID\\VID_054C&PID_0001&MI_03"}, Kind::Conflict);
    Test({pair, u"HID\\VID_0001&PID_0CE6&MI_03"}, Kind::Conflict);
    Test({pair, u"HID\\VID_054C&UP:0001_U:0005", u"HID\\VID_0001&UP:0001_U:0005"}, Kind::Conflict);
    Test({pair, u"HID\\VID_0001&UP:0001_U:0005"}, Kind::Conflict);
    Test({pair, u"HID\\VID_054C&PID_0CE6&MI_04"}, Kind::Conflict);
    Test({pair, u"HID\\VID_054C&PID_0CE6"}, Kind::Conflict);
    Test({u"HID\\VID_054C&PID_0CE6&COL01", u"HID\\VID_054C&PID_0CE6&COL02"}, Kind::Conflict);
    Test({u"HID\\VID_054C&PID_0CE6&REV_0100", u"HID\\VID_054C&PID_0CE6&REV_0101"}, Kind::Conflict);
    Test({pair, u"USB\\VID_054C&PID_0CE6&MI_03"}, Kind::Conflict);
    Test({u"USB\\VID_054C&PID_0CE6", u"HID\\VID_054C&UP:0001_U:0005"}, Kind::Conflict);
    Test({pair, u"HID\\VID_054C&UP:0001_U:0005", u"HID_DEVICE_UP:0001_U:0004"}, Kind::Conflict);
    Test({u"HID\\VID_054C&UP:0001_U:0005", u"HID\\VID_054C&UP:0002_U:0005"}, Kind::Conflict);
    for (const auto &bad : {u"HID\\VID_054&PID_0CE6", u"HID\\VID_054G&PID_0CE6", u"HID\\VID_054C&PID_0CE6&", u"HID\\VID_054C&PID_0CE6&MI_03&REV_0100", u"HID\\VID_054C&UP:001_U:0005", u"HID_DEVICE_UP:0001_U:005", u"USB\\VID_054C&PID_0CE6&REV_0100&MI_03"})
        Test({pair, bad}, Kind::Malformed);
    Test({}, Kind::Empty);
    auto data = Multi({pair});
    Check(Raw(data, 13).kind == Kind::ApiFailure);
    Check(Raw(data, 0, 0x12).kind == Kind::InvalidType);
    Check(Assess({0, 0x2012, PropertyBytes + 2, {}}).kind == Kind::Limit);
    Check(Assess({0, 0x2012, 3, data}).kind == Kind::InvalidLength);
    Check(Assess({0, 0x2012, 2000, data}).kind == Kind::InvalidLength);
    Check(Assess({0, 0x2012, 0, {}}).kind == Kind::InvalidLength);
    data.pop_back(); Check(Raw(data).kind == Kind::InvalidTermination);
    data = Multi({pair}); data.push_back(0); Check(Raw(data).kind == Kind::InvalidTermination);
    data = Multi({pair}); data[0] = 0; Check(Raw(data).kind == Kind::InvalidTermination);
    for (auto surrogate : {char16_t{0xD800}, char16_t{0xDC00}}) {
        data = Multi({pair}); data[5] = surrogate; Check(Raw(data).kind == Kind::InvalidEncoding);
    }
    Test({std::u16string{char16_t{0xD83D}, char16_t{0xDE00}}}, Kind::Unrecognized);
    Test(std::vector<std::u16string>(64, pair), Kind::Complete, Identity::TargetHid);
    Test(std::vector<std::u16string>(65, pair), Kind::Limit);
    Test({std::u16string(1023, u'X')}, Kind::Unrecognized);
    Test({std::u16string(1024, u'X')}, Kind::Limit);
    auto max_bytes = std::vector<std::u16string>(7, std::u16string(1023, u'X'));
    max_bytes.push_back(std::u16string(1022, u'X'));
    Check(Multi(max_bytes).size() * 2 == PropertyBytes);
    Test(max_bytes, Kind::Unrecognized);
    max_bytes.back().push_back(u'X'); Test(max_bytes, Kind::Limit);
    // Every ordering must retain full-list vetoes, including after the target pair.
    for (unsigned i = 0; i < 6; ++i) {
        auto x = six; std::rotate(x.begin(), x.begin() + i, x.end());
        Test(x, Kind::CompleteWithContext, Identity::TargetHid);
        x.insert(x.begin() + i, u"HID\\VID_0001&PID_0001&MI_03"); Test(x, Kind::Conflict);
    }
    std::cout << "HOST TEST property checks: " << checks << '\n';
}
} // namespace
int main(int argc, char **argv) try {
    if (argc == 6 && std::string_view(argv[1]) == "--raw") RawCli(argv, argv[5]);
    else if (argc == 5 && std::string_view(argv[1]) == "--raw-stdin") {
        // Bounded transport for cap tests without Windows command-line length limits.
        std::string input(PropertyBytes * 2 + 1, '\0');
        std::cin.read(input.data(), static_cast<std::streamsize>(input.size()));
        input.resize(static_cast<std::size_t>(std::cin.gcount()));
        RawCli(argv, input);
    }
    else if (argc == 3 && std::string_view(argv[1]) == "--policy-dir") PolicyCases(argv[2]);
    else if (argc == 1) Tests();
    else return 2;
    return 0;
} catch (const std::exception &) { std::cerr << "HOST TEST failed\n"; return 1; }
