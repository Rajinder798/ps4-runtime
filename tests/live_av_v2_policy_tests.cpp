// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
// Host-only tests of the exact guest decision function, never device events.
#define PS4_RUNTIME_LIVE_V2_POLICY_ONLY
#include "../research/homebrew/live_av_v2/main.cpp"
#include <iostream>
#include <stdexcept>
#include <string>

static unsigned checks = 0;
static void check(bool condition) {
    ++checks;
    if (!condition) throw std::runtime_error("live v2 policy check " + std::to_string(checks));
}
static void neutral(const LiveV2::Effective& e) {
    check(e.buttons == 0 && e.audio_command == 0 && e.triggers[0] == 0 && e.triggers[1] == 0);
    for (auto value : e.axes) check(value == 128);
}
int main() {
    try {
        LiveV2::Policy p;
        LiveV2::Raw raw{10, LiveV2::Cross, {1,2,3,4}, 1, 1, {100,200}};
        auto e = p.read(0, raw);
        check(e.state == LiveV2::Connected && e.payload_valid && !e.fatal());
        check(e.buttons == LiveV2::Cross && e.audio_command == 1 && e.axes[0] == 1 && e.axes[3] == 4);
        check(e.triggers[0] == 100 && e.triggers[1] == 200);
        check(p.read(0, raw).state == LiveV2::Connected);
        raw.connected = 0; raw.timestamp = 0;
        e = p.read(0, raw);
        check(e.state == LiveV2::Disconnected && e.payload_valid && !e.fatal()); neutral(e);
        check(raw.buttons == LiveV2::Cross && raw.axes[0] == 1 && raw.triggers[1] == 200 && raw.timestamp == 0);
        check(p.read(0, raw).state == LiveV2::Disconnected);
        raw.connected = 1; raw.timestamp = 11;
        e = p.read(0, raw);
        check(e.state == LiveV2::Connected && e.audio_command == 1 && e.buttons == raw.buttons);
        raw.timestamp = 12; raw.buttons = 0;
        check(p.read(0, raw).audio_command == 0);
        for (int32_t rc : {int32_t(-1), int32_t(-2137915391), int32_t(1)}) {
            LiveV2::Policy error_policy;
            e = error_policy.read(rc, raw);
            check(e.state == LiveV2::ApiError && !e.payload_valid && e.fatal()); neutral(e);
        }
        LiveV2::Policy zero;
        raw.timestamp = 0;
        e = zero.read(0, raw);
        check(e.state == LiveV2::InvalidTimestamp && e.payload_valid && e.fatal()); neutral(e);
        for (uint64_t stamp : {uint64_t(9), uint64_t(10)}) {
            LiveV2::Policy stale;
            raw.timestamp = 10;raw.connected = 1;
            check(stale.read(0,raw).state == LiveV2::Connected);
            raw.connected = 0;neutral(stale.read(0,raw));
            raw.connected = 1;raw.timestamp = stamp;
            e = stale.read(0,raw);
            check(e.state == LiveV2::StaleReconnect && e.fatal()); neutral(e);
        }
        LiveV2::Policy reverse;
        raw.timestamp = 20;check(reverse.read(0,raw).state == LiveV2::Connected);
        raw.timestamp = 19;check(reverse.read(0,raw).state == LiveV2::StaleReconnect);
        check(sizeof(LiveV2::Observation)==72);
        check(LiveV2::PostFlipSleepUs == 16000);
        check(LiveV2::RecordLimit > 4096);
        check(16 + LiveV2::RecordLimit * sizeof(LiveV2::Observation) <= LiveV2::MaxJournalBytes);
        std::cout << checks << " host policy checks passed; no guest/controller/audio access\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';return 1;
    }
}
