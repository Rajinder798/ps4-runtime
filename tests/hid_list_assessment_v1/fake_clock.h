// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once
#include <cstdint>
#include <string_view>
#include <vector>
namespace host_clock_v1 {
using Tick = std::int64_t;
constexpr Tick Hz = 10000000, Start = 1000000000;
struct Cost { std::string_view stage; Tick begin, end; };
void Reset(Tick read_step = 1);
Tick Read();
void Advance(Tick ticks, std::string_view stage);
const std::vector<Cost> &Costs();
} // namespace host_clock_v1
