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
        // API errors during absence must remain errors rather than being interpreted as absence
        for (int32_t rc : {int32_t(-1), int32_t(-2137915391), int32_t(1)}) {
            LiveV2::Policy absent_error_policy;
            LiveV2::Raw absent_raw{0, 0, {0, 0, 0, 0}, 0, 0, {0, 0}};
            auto err_e = absent_error_policy.read(rc, absent_raw);
            check(err_e.state == LiveV2::ApiError && !err_e.payload_valid && err_e.fatal());
            neutral(err_e);
        }
        // Disconnect during non-neutral analog input
        {
            LiveV2::Policy analog_policy;
            LiveV2::Raw non_neutral{50, 0, {0, 255, 64, 192}, 1, 1, {255, 128}};
            auto connected_e = analog_policy.read(0, non_neutral);
            check(connected_e.state == LiveV2::Connected && connected_e.payload_valid && !connected_e.fatal());
            check(connected_e.axes[0] == 0 && connected_e.axes[1] == 255 && connected_e.axes[2] == 64 && connected_e.axes[3] == 192);
            check(connected_e.triggers[0] == 255 && connected_e.triggers[1] == 128);

            non_neutral.connected = 0; non_neutral.timestamp = 0;
            auto disconnected_e = analog_policy.read(0, non_neutral);
            check(disconnected_e.state == LiveV2::Disconnected && disconnected_e.payload_valid && !disconnected_e.fatal());
            neutral(disconnected_e);
            check(non_neutral.axes[0] == 0 && non_neutral.axes[1] == 255 && non_neutral.axes[2] == 64 && non_neutral.axes[3] == 192);
            check(non_neutral.triggers[0] == 255 && non_neutral.triggers[1] == 128);
        }
        // Consecutive absent samples maintain disconnected neutral state
        {
            LiveV2::Policy absent_policy;
            LiveV2::Raw absent_sample{0, 0, {0, 0, 0, 0}, 0, 0, {0, 0}};
            for (int i = 0; i < 5; ++i) {
                auto absent_e = absent_policy.read(0, absent_sample);
                check(absent_e.state == LiveV2::Disconnected && absent_e.payload_valid && !absent_e.fatal());
                neutral(absent_e);
            }
        }
        // Repeated lifecycle state transitions across multiple disconnect/reconnect cycles
        {
            LiveV2::Policy cycle_policy;
            LiveV2::Raw cycle_raw{100, LiveV2::Cross, {128, 128, 128, 128}, 1, 1, {0, 0}};
            // Cycle 1: Connected (100)
            auto c1 = cycle_policy.read(0, cycle_raw);
            check(c1.state == LiveV2::Connected && c1.audio_command == 1);
            // Cycle 1: Disconnect (0)
            cycle_raw.connected = 0; cycle_raw.timestamp = 0;
            auto d1 = cycle_policy.read(0, cycle_raw);
            check(d1.state == LiveV2::Disconnected); neutral(d1);
            // Cycle 1: Reconnect (150)
            cycle_raw.connected = 1; cycle_raw.timestamp = 150;
            auto r1 = cycle_policy.read(0, cycle_raw);
            check(r1.state == LiveV2::Connected && r1.audio_command == 1);

            // Cycle 2: Disconnect (0)
            cycle_raw.connected = 0; cycle_raw.timestamp = 0;
            auto d2 = cycle_policy.read(0, cycle_raw);
            check(d2.state == LiveV2::Disconnected); neutral(d2);
            // Cycle 2: Stale reconnect attempt with older timestamp (120) fails
            cycle_raw.connected = 1; cycle_raw.timestamp = 120;
            auto s2 = cycle_policy.read(0, cycle_raw);
            check(s2.state == LiveV2::StaleReconnect && s2.fatal()); neutral(s2);

            // Fresh multi-cycle policy for successive cycles
            LiveV2::Policy multi_cycle;
            cycle_raw.connected = 1; cycle_raw.timestamp = 100;
            check(multi_cycle.read(0, cycle_raw).state == LiveV2::Connected);
            cycle_raw.connected = 0; cycle_raw.timestamp = 0;
            check(multi_cycle.read(0, cycle_raw).state == LiveV2::Disconnected);
            cycle_raw.connected = 1; cycle_raw.timestamp = 150;
            check(multi_cycle.read(0, cycle_raw).state == LiveV2::Connected);
            cycle_raw.connected = 0; cycle_raw.timestamp = 0;
            check(multi_cycle.read(0, cycle_raw).state == LiveV2::Disconnected);
            cycle_raw.connected = 1; cycle_raw.timestamp = 200;
            auto r3 = multi_cycle.read(0, cycle_raw);
            check(r3.state == LiveV2::Connected && r3.payload_valid && !r3.fatal());
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
