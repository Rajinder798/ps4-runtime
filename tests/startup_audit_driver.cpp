// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
// See LICENSE in the project root for the full license text.

#include "startup_audit.h"
#include <iostream>

int main(int argc, char* argv[]) {
    if (argc != 3) return 2;
    try {
        const std::string mode = argv[2];
        Core::StartupAudit::Configure(std::filesystem::absolute(argv[1]));
        if (mode == "missing") {
            Core::StartupAudit::Unresolved("nid#lib#mod\n\"\\", "libkernel", "fixture", "no export");
            if (Core::StartupAudit::Check("entry")) return 3;
            try { Core::StartupAudit::GuestEntry(); }
            catch (const std::runtime_error&) { return 0; }
            return 4;
        }
        if (!Core::StartupAudit::Check("initial") || !Core::StartupAudit::Check("entry")) return 5;
        Core::StartupAudit::GuestEntry();
        Core::StartupAudit::GuestOutput("driver output \n \" \\ \t");
        try { Core::StartupAudit::GuestEntry(); }
        catch (const std::runtime_error&) { return 0; }
        return 6;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
