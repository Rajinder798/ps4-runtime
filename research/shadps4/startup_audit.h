// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
// See LICENSE in the project root for the full license text.

#pragma once

#include <chrono>
#include <filesystem>
#include <fstream>
#include <mutex>
#include <stdexcept>
#include <string>
#include <string_view>

namespace Core::StartupAudit {
inline std::mutex mutex;
inline std::ofstream output;
inline unsigned unresolved_count = 0;
inline bool configured = false;
inline bool entered = false;
inline std::chrono::steady_clock::time_point start;

inline std::string Json(std::string_view text) {
    constexpr char hex[] = "0123456789abcdef";
    std::string result = "\"";
    for (unsigned char c : text) {
        if (c == '"' || c == '\\') {
            result += '\\';
            result += static_cast<char>(c);
        } else if (c < 32) {
            result += "\\u00";
            result += hex[c >> 4];
            result += hex[c & 15];
        } else {
            result += static_cast<char>(c);
        }
    }
    return result + '"';
}

// Call only with mutex held. Every event is flushed before execution proceeds.
inline void Event(std::string_view fields) {
    const auto us = std::chrono::duration_cast<std::chrono::microseconds>(
                        std::chrono::steady_clock::now() - start).count();
    output << "{\"schema_version\":1,\"elapsed_us\":" << us << ',' << fields << "}\n";
    output.flush();
    if (!output) {
        throw std::runtime_error("Cannot write strict startup audit");
    }
}

inline void Configure(const std::filesystem::path& path) {
    std::scoped_lock lock{mutex};
    if (configured || !path.is_absolute() || std::filesystem::exists(path)) {
        throw std::runtime_error("Startup audit requires a new absolute output path");
    }
    output.open(path, std::ios::binary | std::ios::out);
    if (!output) {
        throw std::runtime_error("Cannot create startup audit");
    }
    start = std::chrono::steady_clock::now();
    Event("\"event\":\"configured\",\"strict_imports\":true");
    configured = true;
}

inline bool Enabled() {
    return configured; // Configured once on the main thread, before guest threads start.
}

inline void Unresolved(std::string_view symbol, std::string_view library,
                       std::string_view module, std::string_view reason) {
    if (!Enabled()) {
        return;
    }
    std::scoped_lock lock{mutex};
    ++unresolved_count;
    Event("\"event\":\"unresolved\",\"symbol\":" + Json(symbol) +
          ",\"library\":" + Json(library) + ",\"module\":" + Json(module) +
          ",\"reason\":" + Json(reason));
}

inline bool Check(std::string_view phase) {
    if (!Enabled()) {
        return true;
    }
    std::scoped_lock lock{mutex};
    Event("\"event\":\"imports_checked\",\"phase\":" + Json(phase) +
          ",\"unresolved_count\":" + std::to_string(unresolved_count));
    return unresolved_count == 0;
}

inline void GuestEntry() {
    if (!Enabled()) {
        return;
    }
    std::scoped_lock lock{mutex};
    if (unresolved_count || entered) {
        throw std::runtime_error("Strict startup entry rejected");
    }
    entered = true;
    Event("\"event\":\"guest_entry\"");
}

inline void GuestOutput(std::string_view text) {
    if (!Enabled()) {
        return;
    }
    std::scoped_lock lock{mutex};
    Event("\"event\":\"guest_output\",\"text\":" + Json(text));
}
} // namespace Core::StartupAudit
