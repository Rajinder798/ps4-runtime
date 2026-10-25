// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <optional>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

// Issue #39 observer policy only. No device acquisition, setters or audio streams.
namespace AllRender {
constexpr size_t Limit = 32;
struct Endpoint { std::string id; bool active; bool muted; float volume; };
struct Snapshot { std::array<std::string, 3> defaults; std::vector<Endpoint> endpoints; };
struct ReadFailure : std::runtime_error {
    std::string phase, identity, domain;
    std::optional<std::int64_t> code;
    ReadFailure(std::string p, std::string id, std::string d, std::optional<std::int64_t> c)
        : std::runtime_error("Endpoint query failed"), phase(std::move(p)),
          identity(std::move(id)), domain(std::move(d)), code(c) {}
};
struct Provider { virtual ~Provider() = default; virtual Snapshot Read() = 0; };
struct Observation {
    bool ok = false;
    Snapshot snapshot;
    std::string reason, phase, identity, domain;
    std::optional<std::int64_t> code;
};
class Guard {
    std::vector<Endpoint> known;
    std::array<std::string, 3> initial_defaults;
    bool initialized = false;
    bool failed = false;
    Observation first_failure;
    Observation Fail(Observation o, const char* reason, const std::string& id = {}) {
        o.ok = false; o.reason = reason; o.identity = id;
        if (o.phase.empty()) o.phase = "mute_guard";
        failed = true; first_failure = o;
        return o;
    }
public:
    const std::vector<Endpoint>& Identities() const { return known; }
    int Token(const std::string& id) const {
        for (size_t i = 0; i < known.size(); ++i)
            if (known[i].id == id) return static_cast<int>(i);
        return -1;
    }
    Observation Poll(Provider& provider) {
        if (failed) return first_failure; // No retries after the first failed read.
        Observation o;
        try { o.snapshot = provider.Read(); }
        catch (const ReadFailure& e) {
            o.phase = e.phase; o.domain = e.domain; o.code = e.code;
            return Fail(o, "query_failed", e.identity);
        }
        catch (const std::exception&) { return Fail(o, "reader_exception"); }
        const auto& s = o.snapshot;
        if (s.endpoints.empty()) return Fail(o, "no_active_endpoints");
        if (s.endpoints.size() > Limit) return Fail(o, "endpoint_limit");
        for (size_t role = 0; role < s.defaults.size(); ++role) {
            if (s.defaults[role].empty()) return Fail(o, "default_unverifiable");
            if (initialized && initial_defaults[role] != s.defaults[role])
                return Fail(o, "default_changed", s.defaults[role]);
        }
        std::vector<std::string> ids;
        for (const auto& e : s.endpoints) {
            if (e.id.empty() || std::find(ids.begin(), ids.end(), e.id) != ids.end())
                return Fail(o, "identity_unverifiable", e.id);
            ids.push_back(e.id);
            if (!e.active) return Fail(o, "endpoint_unavailable", e.id);
            if (!e.muted) return Fail(o, "endpoint_unmuted", e.id);
            if (!std::isfinite(e.volume) || e.volume < 0 || e.volume > 1)
                return Fail(o, "volume_unverifiable", e.id);
            const int token = Token(e.id);
            if (token >= 0 && known[static_cast<size_t>(token)].volume != e.volume)
                return Fail(o, "volume_changed", e.id);
        }
        for (const auto& id : s.defaults)
            if (std::find(ids.begin(), ids.end(), id) == ids.end())
                return Fail(o, "default_unavailable", id);
        for (const auto& e : known)
            if (std::find(ids.begin(), ids.end(), e.id) == ids.end())
                return Fail(o, "endpoint_removed", e.id);
        size_t additions = 0;
        for (const auto& e : s.endpoints) if (Token(e.id) < 0) ++additions;
        if (known.size() + additions > Limit) return Fail(o, "identity_limit");
        for (const auto& e : s.endpoints) if (Token(e.id) < 0) known.push_back(e);
        initial_defaults = s.defaults; initialized = true;
        o.ok = true;
        return o;
    }
};
} // namespace AllRender
