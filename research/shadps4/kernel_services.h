// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
// See LICENSE in the project root for the full license text.

#pragma once

#include <cstdint>
#include <limits>

// Bounded research implementations, shared by the pinned engine adapters and
// portable tests. Values belong to the selected OpenOrbis guest ABI, never the
// host's errno, poll.h or fcntl.h. Unsupported capabilities fail explicitly.
namespace Core::ResearchServices {
inline constexpr int BadFd = 9, NoMemory = 12, Fault = 14, Invalid = 22, NotSupported = 45;
struct Result {
    int value;
    int error = 0;
};

struct PollFd {
    std::int32_t fd;
    std::int16_t events;
    std::int16_t revents;
};
static_assert(sizeof(PollFd) == 8 && alignof(PollFd) == 4);
inline constexpr short In = 1, Pri = 2, Out = 4, Err = 8, Hup = 16, Nval = 32;
inline constexpr short ReadNormal = 0x40, ReadBand = 0x80;
inline constexpr short WriteNormal = 0x100, WriteBand = 0x200;
enum class PollKind { Invalid, Regular, Logger, Unsupported };

// These supported backends have no asynchronous readiness transition. The
// snapshot callback holds the descriptor table lock while inspecting a file.
// A future socket/device implementation must supply real event/error/hangup
// readiness instead of pretending that select's direction bits are poll events.
template <class Snapshot, class Sleep>
Result Poll(PollFd* fds, std::uint64_t count, int timeout_ms, Snapshot snapshot, Sleep sleep) {
    if (count > 1024) {
        return {-1, Invalid}; // Explicit research descriptor-array limit.
    }
    if (count && !fds) {
        return {-1, Fault};
    }
    for (std::uint64_t i = 0; i < count; ++i) {
        fds[i].revents = 0;
    }
    int ready = 0;
    for (std::uint64_t i = 0; i < count; ++i) {
        auto& fd = fds[i];
        if (fd.fd < 0) {
            continue;
        }
        const auto kind = snapshot(fd.fd);
        if (kind == PollKind::Invalid) {
            fd.revents = Nval; // Report even if events == 0.
        } else if (kind == PollKind::Unsupported) {
            return {-1, NotSupported};
        } else {
            if (fd.events & (Pri | ReadBand | WriteBand)) {
                return {-1, NotSupported};
            }
            if (kind == PollKind::Logger && (fd.events & (In | ReadNormal))) {
                return {-1, NotSupported}; // Logger has no input backend.
            }
            const short supported = kind == PollKind::Regular
                                        ? In | ReadNormal | Out | WriteNormal
                                        : Out | WriteNormal;
            fd.revents = fd.events & supported;
        }
        ready += fd.revents != 0; // Count entries, including duplicates, not bits.
    }
    if (!ready && timeout_ms) {
        if (timeout_ms < 0) {
            for (;;) {
                sleep(1000);
            }
        }
        sleep(timeout_ms);
    }
    return {ready};
}

struct DescriptorState {
    int status_flags = -1; // Unknown for descriptors created outside open/std setup.
    int descriptor_flags = 0;
};

inline Result Fcntl(DescriptorState& state, int command, std::uint64_t argument) {
    switch (command) {
    case 1: // F_GETFD
        return {state.descriptor_flags};
    case 2: // F_SETFD; the engine has no exec operation, but stores FD_CLOEXEC.
        if (argument & ~std::uint64_t{1}) {
            return {-1, Invalid};
        }
        state.descriptor_flags = static_cast<int>(argument);
        return {0};
    case 3: // F_GETFL
        return state.status_flags < 0 ? Result{-1, NotSupported} : Result{state.status_flags};
    case 0: // F_DUPFD
    case 4: // F_SETFL: no invented success for changing host append/nonblocking mode.
    case 5: // F_GETOWN
    case 6: // F_SETOWN
    case 11: // F_GETLK
    case 12: // F_SETLK
    case 13: // F_SETLKW
    case 17: // F_DUPFD_CLOEXEC (FreeBSD)
    case 1030: // F_DUPFD_CLOEXEC in the selected SDK's generic fcntl.h
        return {-1, NotSupported};
    default:
        return {-1, Invalid};
    }
}

// Query returns the end of the committed, CPU-readable guest mapping containing
// cursor, or zero. Validate the complete rounded range before invoking the host.
// Host returns a guest errno, zero on success. Only WILLNEED has a host adapter.
template <class Query, class Host>
Result Madvise(std::uint64_t address, std::uint64_t length, int advice, Query query, Host host) {
    constexpr std::uint64_t mask = 0x3fff;
    constexpr auto max = std::numeric_limits<std::uint64_t>::max();
    if ((address & mask) || advice < 0 || advice > 10 || length > max - mask) {
        return {-1, Invalid};
    }
    const auto rounded = (length + mask) & ~mask;
    if (rounded > max - address) {
        return {-1, Invalid};
    }
    if (!rounded) {
        return {0}; // Empty range: no pages to advise.
    }
    const auto end = address + rounded;
    for (auto cursor = address; cursor < end;) {
        const auto next = query(cursor);
        if (next <= cursor) {
            return {-1, NoMemory};
        }
        cursor = next < end ? next : end;
    }
    if (advice != 3) {
        // FreeBSD DONTNEED preserves contents. Do not map it to Linux
        // MADV_DONTNEED or Windows DiscardVirtualMemory/MEM_RESET.
        return {-1, NotSupported};
    }
    const int error = host(address, rounded);
    return error ? Result{-1, error} : Result{0};
}
} // namespace Core::ResearchServices
