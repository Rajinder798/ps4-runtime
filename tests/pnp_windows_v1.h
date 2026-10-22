// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once
#include "pnp_coverage_v1.h"
#include <memory>
namespace pnp_v1 {
class WindowsProvider final : public Provider {
    struct Impl;
    std::unique_ptr<Impl> state;

  public:
    WindowsProvider();
    ~WindowsProvider() override;
    Enumeration Devnodes() override;
    Enumeration Interfaces(Bus) override;
    Lookup InterfaceNode(std::wstring_view, Bus) override;
    Node Properties(Id) override;
    Key InstanceKey(Id) override;
};
class WindowsNotifications {
    struct Impl;
    std::unique_ptr<Impl> state;

  public:
    WindowsNotifications(std::shared_ptr<Queue>, Trace &);
    ~WindowsNotifications();
    void Start(); // The live opt-in entry point only. Construction is inert.
    bool Close();
};
void WindowsCallbackHostTests(); // Controlled buffers only; no registrations/queries.
} // namespace pnp_v1
