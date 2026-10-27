// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once
#include "all_render_guard.h"
#include <chrono>
#include <iomanip>
#include <iostream>
#include <locale>
#include <sstream>

namespace AllRender {
constexpr size_t OutputLimit = 32 * 1024 * 1024;
inline std::string JsonString(const std::string& value) {
    std::string text = "\"";
    constexpr char hex[] = "0123456789abcdef";
    for (const unsigned char ch : value) {
        if (ch == '\\' || ch == '"') { text += '\\'; text += static_cast<char>(ch); }
        else if (ch < 32) { text += "\\u00"; text += hex[ch >> 4]; text += hex[ch & 15]; }
        else text += static_cast<char>(ch);
    }
    return text + '"';
}
inline void WriteBounded(std::ostream& log, const std::string& bytes,
                         size_t reserve = 0, size_t limit = OutputLimit) {
    const auto position = log.tellp();
    if (position < std::streampos(0)) throw std::runtime_error("All-render output position unavailable");
    const auto used = static_cast<std::uintmax_t>(static_cast<std::streamoff>(position));
    if (used > limit || bytes.size() > limit - used || reserve > limit - used - bytes.size())
        throw std::runtime_error("All-render observer output exceeds byte limit");
    log << bytes << std::flush;
    if (!log) throw std::runtime_error("All-render output write failed");
}

// The production loop; only clock, ready/stop and sleep operations are shimmed
// in host tests. COM acquisition remains in all_render_observer.h.
template<class Operations>
int Watch(Provider& provider, std::ostream& log, Operations& operations,
          unsigned long timeout, size_t byte_limit = OutputLimit) {
    Guard guard;
    const auto began = operations.Now();
    const auto elapsed_ms = [&] {
        return std::chrono::duration_cast<std::chrono::milliseconds>(operations.Now() - began).count();
    };
    const auto check_time = [&] {
        if (elapsed_ms() >= static_cast<long long>(timeout))
            throw std::runtime_error("All-render observer budget expired");
    };
    unsigned samples = 0;
    size_t published = 0;
    for (;;) {
        const auto observed = guard.Poll(provider);
        const auto elapsed = elapsed_ms();
        if (!observed.ok) {
            // Retain the observed query/identity/unmute failure even if that
            // read also crossed the deadline. It can never publish readiness.
            std::cerr << "All-render mute guard failed: " << observed.reason << " (" << observed.phase << ")\n";
            std::ostringstream failure;
            failure << "{\"schema_version\":2,\"event\":\"failure\",\"elapsed_ms\":" << elapsed
                << ",\"unix_ns\":" << operations.UnixNs() << ",\"reason\":" << JsonString(observed.reason)
                << ",\"phase\":" << JsonString(observed.phase) << ",\"identity\":" << JsonString(observed.identity)
                << ",\"code_domain\":" << JsonString(observed.domain) << ",\"code\":";
            if (observed.code) failure << *observed.code; else failure << "null";
            failure << "}\n{\"schema_version\":2,\"event\":\"summary\",\"status\":\"failed\",\"samples\":" << samples << "}\n";
            WriteBounded(log, failure.str(), 0, byte_limit);
            return 1;
        }
        check_time(); // A synchronous native query may have consumed the budget.
        std::ostringstream pending;
        pending.imbue(std::locale::classic());
        const auto& known = guard.Identities();
        while (published < known.size()) {
            pending << "{\"schema_version\":2,\"event\":\"identity\",\"token\":" << published
                << ",\"identity\":" << JsonString(known[published].id) << "}\n";
            ++published;
        }
        pending << std::setprecision(9) << "{\"schema_version\":2,\"event\":\"sample\",\"elapsed_ms\":" << elapsed
            << ",\"default_tokens\":[" << guard.Token(observed.snapshot.defaults[0]) << ','
            << guard.Token(observed.snapshot.defaults[1]) << ',' << guard.Token(observed.snapshot.defaults[2])
            << "],\"endpoints\":[";
        bool comma = false;
        for (const auto& endpoint : observed.snapshot.endpoints) {
            if (comma) pending << ',';
            comma = true;
            pending << "{\"token\":" << guard.Token(endpoint.id)
                << ",\"active\":true,\"muted\":true,\"volume\":" << endpoint.volume << '}';
        }
        pending << "]}\n";
        const auto footer = "{\"schema_version\":2,\"event\":\"summary\",\"status\":\"passed\",\"samples\":"
            + std::to_string(samples + 1) + "}\n";
        check_time();
        // Reserve the full terminal record before writing pending samples or
        // readiness; buffered bytes and the footer both count against the cap.
        WriteBounded(log, pending.str(), footer.size(), byte_limit);
        ++samples;
        check_time();
        if (samples == 1) operations.Ready();
        const bool stop = operations.Stopped();
        check_time(); // A stop query cannot turn an expired session into success.
        if (stop) {
            WriteBounded(log, footer, 0, byte_limit);
            return 0;
        }
        operations.Pause();
    }
}
} // namespace AllRender
