// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once
#include "arrival_trace_v1.h"
#include <memory>
namespace arrival_v1 {
class WindowsArrival {
    struct Impl;
    std::unique_ptr<Impl> state;
public:
    explicit WindowsArrival(Trace& trace);
    ~WindowsArrival();
    WindowsArrival(const WindowsArrival&)=delete;
    WindowsArrival& operator=(const WindowsArrival&)=delete;
    void Start(); // Only the separately authorized live entry point calls this.
    void Poll();
    bool Close();
};
// Controlled callback injection only: does not register notifications/enumerate.
void WindowsCallbackHostTest(Trace& trace);
} // namespace arrival_v1
