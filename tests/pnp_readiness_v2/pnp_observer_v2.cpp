// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
#include "pnp_windows_v2.h"
#define NOMINMAX
#include <iostream>
#include <stdexcept>
#include <windows.h>

int wmain(int argc, wchar_t **argv) {
    // Reject everything else before any registration, enumeration or file creation.
    if (argc != 7 || std::wstring_view(argv[1]) != L"--observe-pnp-coverage-v2" ||
        std::wstring_view(argv[6]) != L"--pnp-coverage-authorized") {
        std::cerr << "Requires --observe-pnp-coverage-v2 EVIDENCE STOP READY DURATION_MS "
                     "--pnp-coverage-authorized\n";
        return 2;
    }
    unsigned duration = 0;
    const std::wstring_view text(argv[5]);
    if (text.empty() || text.size() > 6)
        return 2;
    for (auto c : text) {
        if (c < L'0' || c > L'9')
            return 2;
        duration = duration * 10 + static_cast<unsigned>(c - L'0');
    }
    if (duration < 1000 || duration > pnp_v2::MaxDurationMs)
        return 2;
    try {
        const auto evidence = std::filesystem::absolute(argv[2]).lexically_normal();
        const auto stop = std::filesystem::absolute(argv[3]).lexically_normal();
        const auto ready = std::filesystem::absolute(argv[4]).lexically_normal();
        if (evidence == stop || evidence == ready || stop == ready ||
            std::filesystem::exists(evidence) || std::filesystem::exists(stop) ||
            std::filesystem::exists(ready))
            throw std::runtime_error("Paths must be fresh and distinct");
        pnp_v2::Trace trace(evidence);
        const auto begin = pnp_v2::Ticks();
        trace.Session(duration, begin);
        auto queue = std::make_shared<pnp_v2::Queue>();
        pnp_v2::WindowsProvider provider;
        pnp_v2::Collector collector(provider, trace);
        pnp_v2::WindowsNotifications notifications(queue, trace);
        bool requested = false, cleanup = true;
        try {
            notifications.Start(); // Register before enumeration; overlaps are retained.
            collector.Snapshot();
            collector.Notifications(*queue);
            if (trace.Failed())
                throw std::runtime_error("Initial PnP coverage incomplete");
            if (!collector.Ready()) {
                trace.Fail(pnp_v2::Failure::Coverage);
                throw std::runtime_error("Initial PnP readiness not established");
            }
            auto h = CreateFileW(ready.c_str(), GENERIC_WRITE, FILE_SHARE_READ, nullptr, CREATE_NEW,
                                 FILE_ATTRIBUTE_NORMAL, nullptr);
            if (h == INVALID_HANDLE_VALUE)
                throw std::runtime_error("Cannot create fresh readiness marker");
            if (!CloseHandle(h))
                throw std::runtime_error("Readiness close failed");
            auto next = pnp_v2::Ticks() + pnp_v2::Frequency() * pnp_v2::PeriodMs / 1000;
            const auto deadline = begin + pnp_v2::Frequency() * duration / 1000;
            while (!trace.Failed() && pnp_v2::Ticks() < deadline &&
                   !(requested = std::filesystem::exists(stop))) {
                collector.Notifications(*queue);
                if (trace.Failed())
                    break;
                if (pnp_v2::Ticks() >= next) {
                    collector.Snapshot();
                    // No catch-up burst. Snapshot duration and missed cadence remain observable.
                    next = pnp_v2::Ticks() + pnp_v2::Frequency() * pnp_v2::PeriodMs / 1000;
                }
                Sleep(10);
            }
        } catch (...) {
            trace.Fail(pnp_v2::Failure::Internal); // Latch before unregister/cleanup.
        }
        // A failed unregister retains the shared callback queue until process exit.
        cleanup = notifications.Close();
        try {
            collector.Notifications(*queue);
            collector.QueueSummary(*queue);
        } catch (...) {
            trace.Fail(pnp_v2::Failure::Internal);
            cleanup = false;
        }
        const auto end = pnp_v2::Ticks();
        if (end - begin > pnp_v2::Frequency() * (duration + pnp_v2::ScanBudgetMs) / 1000)
            trace.Fail(pnp_v2::Failure::Overhead);
        try {
            trace.Stopped(begin, end, requested);
        } catch (...) {
            trace.Fail(pnp_v2::Failure::Resources);
            cleanup = false;
        }
        if (!cleanup)
            trace.Fail(pnp_v2::Failure::Cleanup);
        trace.Cleanup(cleanup ? 0U : 1U);
        trace.Finish(collector.Complete(), cleanup);
        return trace.Failed() || !collector.Ready() ? 1 : 0;
    } catch (const std::exception &) {
        // Exception text and private arguments/paths are deliberately not serialized.
        std::cerr
            << "PnP coverage failed; retain incomplete evidence and separate cleanup errors\n";
        return 1;
    }
}
