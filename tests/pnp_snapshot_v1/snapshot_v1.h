// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once
#include "../pnp_rejection_v1/rejection_v1.h"
#include <stdexcept>

namespace snapshot_v1 {
using namespace rejection_v1;
constexpr unsigned QueryCap = 32768, QueryMs = 250;
// Logical Source calls are bounded before and after each call. A synchronous
// Windows API stall requires the separately owned supervisor's containment.
class BoundedSource final : public Source {
    Source &source;
    Tick deadline;
    unsigned calls = 0;
    void Check();
    template <typename F> auto Query(F f) {
        Check();
        auto value = f();
        if (Ticks() > deadline)
            throw std::runtime_error("Snapshot query deadline");
        return value;
    }

  public:
    explicit BoundedSource(Source &s)
        : source(s), deadline(Ticks() + Frequency() * QueryMs / 1000) {}
    Enumeration Devnodes() override;
    Enumeration Interfaces(Bus) override;
    RawNode Read(Id) override;
    Root TreeRoot() override;
    Key InstanceKey(Id) override;
};
// Exactly one Collector::Snapshot. No registration, queue intake or retry.
int Run(Source &, const std::filesystem::path &, bool host_test, unsigned host_writer_fault = 0,
        bool host_cleanup_fault = false);
} // namespace snapshot_v1
