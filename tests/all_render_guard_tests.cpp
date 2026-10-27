// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
#include "all_render_loop.h"
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
struct LoopOperations {
    long long ticks = 0, stop_query_ms = 0;
    bool stop = true, fail_ready = false;
    unsigned ready_calls = 0;
    auto Now() const { return std::chrono::steady_clock::time_point{} + std::chrono::milliseconds(ticks); }
    long long UnixNs() const { return 12345; }
    void Ready() {
        if (fail_ready) throw std::runtime_error("synthetic readiness write failure");
        ++ready_calls;
    }
    bool Stopped() { ticks += stop_query_ms; return stop; }
    void Pause() { ticks += 25; }
};
struct LoopProvider final : AllRender::Provider {
    LoopOperations& operations;
    long long delay;
    bool fail = false, stop_second_read = false;
    unsigned calls = 0;
    LoopProvider(LoopOperations& ops, long long ms = 0) : operations(ops), delay(ms) {}
    AllRender::Snapshot Read() override {
        ++calls;
        if (!stop_second_read || calls == 2) operations.ticks += delay;
        if (stop_second_read && calls == 2) operations.stop = true;
        if (fail) throw AllRender::ReadFailure("GetMute", "B", "HRESULT", -2147467259LL);
        return Fake{}.next;
    }
};
template<class Action> void Throws(const char* message, Action action) {
    try { action(); }
    catch (const std::runtime_error& error) {
        Require(std::string(error.what()).find(message) != std::string::npos);
        return;
    }
    Require(false);
}
void LoopTests() {
    LoopOperations control; LoopProvider good(control); std::ostringstream complete;
    Require(AllRender::Watch(good, complete, control, 100) == 0);
    Require(control.ready_calls == 1 && good.calls == 1);
    Require(complete.str().find("\"status\":\"passed\"") != std::string::npos);
    const auto required = complete.str().size();
    // The actual production loop, not a separately reimplemented policy.
    for (const long long delay : {100, 101, 150}) {
        for (const bool stop : {false, true}) {
            LoopOperations ops; ops.stop = stop; LoopProvider provider(ops, delay); std::ostringstream log;
            Throws("budget expired", [&] { AllRender::Watch(provider, log, ops, 100); });
            Require(ops.ready_calls == 0 && log.str().empty());
        }
    }
    LoopOperations inside; LoopProvider within(inside, 99); std::ostringstream within_log;
    Require(AllRender::Watch(within, within_log, inside, 100) == 0 && inside.ready_calls == 1);
    LoopOperations boundary; boundary.stop_query_ms = 1;
    LoopProvider almost(boundary, 99); std::ostringstream boundary_log;
    Throws("budget expired", [&] { AllRender::Watch(almost, boundary_log, boundary, 100); });
    Require(boundary_log.str().find("\"status\":\"passed\"") == std::string::npos);
    LoopOperations later; later.stop = false; LoopProvider second(later, 100); second.stop_second_read = true;
    std::ostringstream later_log;
    Throws("budget expired", [&] { AllRender::Watch(second, later_log, later, 100); });
    Require(later.ready_calls == 1 && second.calls == 2);
    Require(later_log.str().find("\"status\":\"passed\"") == std::string::npos);
    // Pending samples plus a complete footer must fit, including the exact cap.
    for (const auto cap : {size_t{1}, required - 1}) {
        LoopOperations ops; LoopProvider provider(ops); std::ostringstream log;
        Throws("byte limit", [&] { AllRender::Watch(provider, log, ops, 100, cap); });
        Require(log.str().empty() && ops.ready_calls == 0);
    }
    LoopOperations full; LoopProvider full_provider(full); std::ostringstream full_log;
    full_log << std::string(required, 'x');
    Throws("byte limit", [&] { AllRender::Watch(full_provider, full_log, full, 100, required); });
    Require(full_log.str().size() == required && full.ready_calls == 0);
    LoopOperations exact; LoopProvider exact_provider(exact); std::ostringstream exact_log;
    Require(AllRender::Watch(exact_provider, exact_log, exact, 100, required) == 0);
    Require(exact_log.str().size() == required);
    // Guard/query failures remain primary even when the same read is overlong.
    LoopOperations failed; LoopProvider bad(failed, 150); bad.fail = true; std::ostringstream failed_log;
    Require(AllRender::Watch(bad, failed_log, failed, 100) == 1);
    Require(failed.ready_calls == 0 && bad.calls == 1);
    Require(failed_log.str().find("query_failed") != std::string::npos);
    Require(failed_log.str().find("-2147467259") != std::string::npos);
    Require(failed_log.str().find("\"status\":\"passed\"") == std::string::npos);
    LoopOperations capped; LoopProvider capped_bad(capped, 150); capped_bad.fail = true; std::ostringstream capped_log;
    Throws("byte limit", [&] { AllRender::Watch(capped_bad, capped_log, capped, 100, 1); });
    Require(capped_log.str().empty() && capped.ready_calls == 0);
    LoopOperations publication; publication.fail_ready = true; LoopProvider publishing(publication); std::ostringstream publish_log;
    Throws("readiness write failure", [&] { AllRender::Watch(publishing, publish_log, publication, 100); });
    Require(publish_log.str().find("\"status\":\"passed\"") == std::string::npos);
    LoopOperations output; LoopProvider writer(output); std::ostringstream broken;
    broken.setstate(std::ios::badbit);
    Throws("output position", [&] { AllRender::Watch(writer, broken, output, 100); });
    Require(output.ready_calls == 0);
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
        const auto guard_checks = checks;
        LoopTests();
        std::cout << "HOST-ONLY all-render guard_checks=" << guard_checks << " loop_checks=" << checks - guard_checks
                  << " total_checks=" << checks << " passed; no COM/devices/streams/setters\n";
        return 0;
    } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
