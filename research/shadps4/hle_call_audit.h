// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
// See LICENSE in the project root for the full license text.

#pragma once

#include <cstddef>
#include <cstdint>
#include <map>
#include <mutex>
#include <set>
#include <string>
#include <tuple>

#include "core/startup_audit.h"

// Diagnostic-only research variant: records the first guest entry into each
// registered HLE host-call wrapper in the existing strict startup audit. It is
// layered on the strict patch and never part of the default research engine.
namespace Core::HleCallAudit {
using Identity = std::tuple<std::string, std::string, std::string>; // nid, library, module
inline std::mutex mutex;
inline std::map<std::uint64_t, std::set<Identity>> registered;

inline void Register(std::uint64_t address, const char* nid, const char* library, const char* module) {
    std::scoped_lock lock{mutex};
    registered[address].emplace(nid, library, module);
}

// After InitHLELibs. Proves the variant is active before guest entry; an audit
// without this event must not be read as "nothing was called".
inline void Ready() {
    if (!StartupAudit::Enabled()) {
        return;
    }
    std::size_t addresses = 0;
    std::size_t identities = 0;
    {
        std::scoped_lock lock{mutex};
        addresses = registered.size();
        for (const auto& [address, symbols] : registered) {
            identities += symbols.size();
        }
    }
    std::scoped_lock lock{StartupAudit::mutex};
    StartupAudit::Event("\"event\":\"hle_call_audit\",\"registered_addresses\":" +
                        std::to_string(addresses) +
                        ",\"registered_identities\":" + std::to_string(identities));
}

// Once per wrapper. Every identity registered at that address is listed, because
// the wrapper cannot tell which alias the guest imported. An empty list is a
// host-call wrapper that no LIB_FUNCTION registered (for example a thread entry).
// A write failure terminates the process instead of unwinding into guest frames.
inline void FirstCall(std::uint64_t address) noexcept {
    if (!StartupAudit::Enabled()) {
        return;
    }
    std::string symbols = "[";
    {
        std::scoped_lock lock{mutex};
        if (const auto found = registered.find(address); found != registered.end()) {
            for (const auto& [nid, library, module] : found->second) {
                if (symbols.size() > 1) {
                    symbols += ',';
                }
                symbols += "{\"nid\":" + StartupAudit::Json(nid) +
                           ",\"library\":" + StartupAudit::Json(library) +
                           ",\"module\":" + StartupAudit::Json(module) + '}';
            }
        }
    }
    symbols += ']';
    std::scoped_lock lock{StartupAudit::mutex};
    StartupAudit::Event("\"event\":\"hle_first_call\",\"symbols\":" + symbols);
}
} // namespace Core::HleCallAudit
