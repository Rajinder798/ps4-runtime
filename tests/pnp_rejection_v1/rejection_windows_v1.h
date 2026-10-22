// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once
#include "rejection_v1.h"
#include "../pnp_readiness_v2/pnp_windows_v2.h"
namespace rejection_v1 {
// Compile-only adapter during this authorization. No constructor performs queries.
// No executable, coordinator import, registration or live CLI selects this class.
class WindowsSource final : public Source {
    pnp_v2::WindowsProvider enumeration;

  public:
    Enumeration Devnodes() override;
    Enumeration Interfaces(Bus) override;
    RawNode Read(Id) override;
    Root TreeRoot() override;
    Key InstanceKey(Id) override;
};
} // namespace rejection_v1
