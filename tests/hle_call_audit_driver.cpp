// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
// See LICENSE in the project root for the full license text.

#include "hle_call_audit.h"
#include <iostream>

// Writes the event order the engine variant produces, using the reviewed header.
int main(int argc, char* argv[]) {
    if (argc != 3) return 2;
    try {
        const std::string mode = argv[2];
        if (mode == "disabled") {
            Core::HleCallAudit::Register(0x10, "nid", "libkernel", "libkernel");
            Core::HleCallAudit::Ready();
            Core::HleCallAudit::FirstCall(0x10);
            return std::filesystem::exists(argv[1]) ? 3 : 0;
        }
        Core::StartupAudit::Configure(std::filesystem::absolute(argv[1]));
        // Alias pair at one wrapper, a duplicate registration and a quoted identity.
        Core::HleCallAudit::Register(0x10, "writeAlias", "libkernel", "libkernel");
        Core::HleCallAudit::Register(0x10, "writeNid", "libkernel", "libkernel");
        Core::HleCallAudit::Register(0x10, "writeNid", "libkernel", "libkernel");
        Core::HleCallAudit::Register(0x20, "sleepNid", "libkernel", "libkernel");
        Core::HleCallAudit::Register(0x30, "odd\"\\nid", "libkernel", "libkernel");
        Core::HleCallAudit::Ready();
        if (!Core::StartupAudit::Check("initial") || !Core::StartupAudit::Check("entry")) return 4;
        Core::StartupAudit::GuestEntry();
        Core::HleCallAudit::FirstCall(0x10);
        Core::StartupAudit::GuestOutput("service-roundtrip: begin");
        Core::HleCallAudit::FirstCall(0x99); // Unregistered wrapper.
        if (mode == "sleep") {
            Core::HleCallAudit::FirstCall(0x20);
        }
        Core::StartupAudit::GuestOutput("service-roundtrip: PASS threads=2 bytes=256 seek=128");
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
