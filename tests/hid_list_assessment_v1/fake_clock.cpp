// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
#include "fake_clock.h"
#include "../pnp_readiness_v2/pnp_coverage_v2.h"
#include <limits>
#include <stdexcept>
namespace host_clock_v1 {
namespace { Tick now = Start, step = 1; std::vector<Cost> costs; }
void Reset(Tick read_step) {
    if (read_step < 0 || read_step > Hz) throw std::runtime_error("invalid HOST TEST clock step");
    now = Start; step = read_step; costs.clear();
}
Tick Read() {
    if (now > std::numeric_limits<Tick>::max() - step) throw std::runtime_error("HOST TEST clock overflow");
    auto value = now; now += step; return value;
}
void Advance(Tick ticks, std::string_view stage) {
    if (ticks < 0 || now > std::numeric_limits<Tick>::max() - ticks) throw std::runtime_error("invalid HOST TEST cost");
    if (costs.size() == 32768) throw std::runtime_error("HOST TEST cost cap");
    costs.push_back({stage, now, now + ticks}); now += ticks;
}
const std::vector<Cost> &Costs() { return costs; }
} // namespace host_clock_v1
namespace pnp_v2 {
Tick Ticks() { return host_clock_v1::Read(); }
Tick Frequency() { return host_clock_v1::Hz; }
} // namespace pnp_v2
