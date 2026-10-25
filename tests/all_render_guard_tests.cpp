// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
#include "all_render_guard.h"
#include <iostream>
#include <limits>

namespace {
unsigned checks = 0;
void Require(bool condition) { ++checks; if (!condition) throw std::runtime_error("All-render host check failed"); }
struct Fake final : AllRender::Provider {
    AllRender::Snapshot next{{"A", "A", "A"}, {{"A", true, true, .5f}, {"B", true, true, .75f}}};
    bool fail = false;
    std::string error_phase = "GetMute";
    unsigned calls = 0;
    AllRender::Snapshot Read() override {
        ++calls;
        if (fail) throw AllRender::ReadFailure(error_phase, "B", "HRESULT", -2147467259LL);
        return next;
    }
};
template<class Change> void Reject(const char* expected, Change change) {
    Fake fake; AllRender::Guard guard;
    Require(guard.Poll(fake).ok);
    change(fake);
    const auto bad = guard.Poll(fake);
    Require(!bad.ok && bad.reason == expected);
    const auto count = fake.calls;
    fake.fail = false; fake.next = Fake{}.next;
    const auto again = guard.Poll(fake);
    Require(!again.ok && again.reason == bad.reason && fake.calls == count);
}
}
int main() {
    try {
        Fake fake; AllRender::Guard guard;
        Require(guard.Poll(fake).ok);
        std::swap(fake.next.endpoints[0], fake.next.endpoints[1]);
        Require(guard.Poll(fake).ok && guard.Token("A") == 0 && guard.Token("B") == 1);
        fake.next.endpoints.push_back({"C", true, true, .25f});
        Require(guard.Poll(fake).ok && guard.Token("C") == 2);
        Reject("endpoint_unmuted", [](Fake& f) { f.next.endpoints[0].muted = false; });
        Reject("endpoint_unmuted", [](Fake& f) { f.next.endpoints[1].muted = false; });
        Reject("endpoint_unmuted", [](Fake& f) { f.next.endpoints.push_back({"C",true,false,1}); });
        for (size_t role = 0; role < 3; ++role)
            Reject("default_changed", [role](Fake& f) { f.next.defaults[role] = "B"; });
        Reject("endpoint_removed", [](Fake& f) { f.next.endpoints.pop_back(); });
        Reject("endpoint_unavailable", [](Fake& f) { f.next.endpoints[1].active = false; });
        Reject("identity_unverifiable", [](Fake& f) { f.next.endpoints[1].id.clear(); });
        Reject("identity_unverifiable", [](Fake& f) { f.next.endpoints[1].id = "A"; });
        Reject("default_unavailable", [](Fake& f) { f.next.endpoints[0].id = "C"; });
        Reject("volume_changed", [](Fake& f) { f.next.endpoints[1].volume = .9f; });
        Reject("volume_unverifiable", [](Fake& f) { f.next.endpoints[1].volume = std::numeric_limits<float>::quiet_NaN(); });
        Reject("no_active_endpoints", [](Fake& f) { f.next.endpoints.clear(); });
        Reject("query_failed", [](Fake& f) { f.fail = true; });
        Fake error; AllRender::Guard failed; error.fail = true;
        const auto observed = failed.Poll(error);
        Require(!observed.ok && observed.phase == "GetMute" && observed.identity == "B" &&
                observed.domain == "HRESULT" && observed.code == -2147467259LL);
        for (const char* phase : {"GetDefaultConsole", "GetDefaultMultimedia", "GetDefaultCommunications",
                "EnumAudioEndpoints", "GetCount", "Item", "GetId", "GetState", "ActivateEndpointVolume", "GetVolume"}) {
            Fake query; query.fail=true; query.error_phase=phase; AllRender::Guard error_guard;
            const auto bad=error_guard.Poll(query);
            Require(!bad.ok && bad.phase==phase && bad.code==-2147467259LL);
        }
        Fake initial; initial.next.endpoints[1].muted = false; AllRender::Guard first;
        Require(!first.Poll(initial).ok);
        Fake many; many.next.endpoints.clear();
        for (size_t i=0;i<=AllRender::Limit;++i) many.next.endpoints.push_back({std::to_string(i),true,true,.5f});
        AllRender::Guard bounded; Require(!bounded.Poll(many).ok);
        std::cout << "HOST-ONLY all-render checks=" << checks << " passed; no COM/devices/streams/setters\n";
        return 0;
    } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
