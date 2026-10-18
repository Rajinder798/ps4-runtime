// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
// See LICENSE in the project root for the full license text.

#include "kernel_services.h"
#include <chrono>
#include <cstdlib>
#include <iostream>
#include <thread>
#ifdef _WIN32
#include <windows.h>
#else
#include <sys/mman.h>
#endif

namespace S = Core::ResearchServices;
int checks = 0;
void Check(bool value) {
    ++checks;
    if (!value) {
        std::cerr << "Failed check " << checks << '\n';
        std::exit(1);
    }
}
void CheckResult(S::Result result, int value, int error = 0) {
    Check(result.value == value && result.error == error);
}

int main() {
    const auto snapshot = [](int fd) {
        if (fd == 0) return S::PollKind::Logger;
        if (fd == 3) return S::PollKind::Regular;
        if (fd == 4) return S::PollKind::Unsupported;
        return S::PollKind::Invalid;
    };
    int slept = 0;
    const auto sleep = [&](int ms) { slept += ms; };
    S::PollFd fds[] = {{-8, S::In, 123}, {0, 0, 123}, {3, S::In | S::Out, 123},
                       {3, S::WriteNormal | S::ReadNormal, 123}, {99, 0, 123}};
    CheckResult(S::Poll(fds, 5, 200, snapshot, sleep), 3);
    Check(slept == 0 && fds[0].revents == 0 && fds[1].revents == 0);
    Check(fds[2].revents == (S::In | S::Out));
    Check(fds[3].revents == (S::ReadNormal | S::WriteNormal));
    Check(fds[4].revents == S::Nval);
    CheckResult(S::Poll(nullptr, 1, 0, snapshot, sleep), -1, S::Fault);
    CheckResult(S::Poll(nullptr, 1025, 0, snapshot, sleep), -1, S::Invalid);
    CheckResult(S::Poll(nullptr, UINT64_MAX, 0, snapshot, sleep), -1, S::Invalid);
    CheckResult(S::Poll(nullptr, 0, 7, snapshot, sleep), 0);
    Check(slept == 7);
    S::PollFd zero[] = {{0, 0, 123}, {-1, -1, 123}};
    CheckResult(S::Poll(zero, 2, 0, snapshot, sleep), 0);
    Check(zero[0].revents == 0 && zero[1].revents == 0);
    S::PollFd logger[] = {{0, S::Out | S::WriteNormal, 0}};
    CheckResult(S::Poll(logger, 1, 30, snapshot, sleep), 1);
    Check(logger[0].revents == (S::Out | S::WriteNormal));
    for (short event : {S::In, S::ReadNormal, S::Pri, S::ReadBand, S::WriteBand}) {
        logger[0].events = event;
        CheckResult(S::Poll(logger, 1, 0, snapshot, sleep), -1, S::NotSupported);
    }
    S::PollFd socket[] = {{4, 0, 55}};
    CheckResult(S::Poll(socket, 1, 0, snapshot, sleep), -1, S::NotSupported);
    Check(socket[0].revents == 0);
    // Actual timer path: no descriptors are manufactured ready at expiry.
    const auto start = std::chrono::steady_clock::now();
    CheckResult(S::Poll(nullptr, 0, 25, snapshot, [](int ms) {
        std::this_thread::sleep_for(std::chrono::milliseconds{ms});
    }), 0);
    Check(std::chrono::steady_clock::now() - start >= std::chrono::milliseconds{20});
    // Any negative timeout means indefinite. Interrupt the injected wait to
    // verify the branch without hanging a test or substituting finite behavior.
    struct Interrupted {};
    bool interrupted = false;
    try {
        S::Poll(nullptr, 0, -7, snapshot, [](int ms) {
            Check(ms == 1000);
            throw Interrupted{};
        });
    } catch (Interrupted&) { interrupted = true; }
    Check(interrupted);

    S::DescriptorState first{9, 0}, second{2, 0}, unknown;
    CheckResult(S::Fcntl(first, 1, UINT64_MAX), 0); // Getter ignores optional argument.
    CheckResult(S::Fcntl(first, 2, 1), 0);
    CheckResult(S::Fcntl(first, 1, 0), 1);
    CheckResult(S::Fcntl(second, 1, 0), 0); // Descriptor state is independent.
    CheckResult(S::Fcntl(first, 2, 2), -1, S::Invalid);
    CheckResult(S::Fcntl(first, 1, 0), 1); // Failed mutation leaves state intact.
    CheckResult(S::Fcntl(first, 2, 0), 0);
    CheckResult(S::Fcntl(first, 3, UINT64_MAX), 9);
    CheckResult(S::Fcntl(unknown, 3, 0), -1, S::NotSupported);
    for (int command : {0, 4, 5, 6, 11, 12, 13, 17, 1030}) {
        CheckResult(S::Fcntl(first, command, 0), -1, S::NotSupported);
    }
    Check(first.status_flags == 9 && first.descriptor_flags == 0);
    CheckResult(S::Fcntl(first, 999, 0), -1, S::Invalid);

    int calls = 0;
    const auto query = [](std::uint64_t p) -> std::uint64_t {
        if (p >= 0x4000 && p < 0x8000) return 0x8000;
        if (p >= 0x8000 && p < 0xc000) return 0xc000;
        return 0;
    };
    const auto host = [&](std::uint64_t p, std::uint64_t size) {
        ++calls;
        Check(p == 0x4000 && size == 0x8000);
        return 0;
    };
    CheckResult(S::Madvise(0x4000, 0x4001, 3, query, host), 0);
    Check(calls == 1);
    CheckResult(S::Madvise(0x4000, 0x8001, 3, query, host), -1, S::NoMemory);
    CheckResult(S::Madvise(0, 1, 3, query, host), -1, S::NoMemory);
    CheckResult(S::Madvise(0x4001, 1, 3, query, host), -1, S::Invalid);
    CheckResult(S::Madvise(0x4000, UINT64_MAX, 3, query, host), -1, S::Invalid);
    CheckResult(S::Madvise(UINT64_MAX & ~std::uint64_t{0x3fff}, 1, 3, query, host),
                -1, S::Invalid);
    CheckResult(S::Madvise(0x4000, 1, -1, query, host), -1, S::Invalid);
    CheckResult(S::Madvise(0x4000, 1, 11, query, host), -1, S::Invalid);
    for (int advice : {0, 1, 2, 4, 5, 6, 7, 8, 9, 10}) {
        CheckResult(S::Madvise(0x4000, 1, advice, query, host), -1, S::NotSupported);
    }
    Check(calls == 1); // Invalid/unmapped/unsupported ranges never reach host.
    CheckResult(S::Madvise(0x4000, 0, 3, query, host), 0);
    CheckResult(S::Madvise(0x4000, 1, 3, query, [](auto, auto) { return S::NoMemory; }),
                -1, S::NoMemory);
    // A real host prefetch preserves existing contents. This
    // checks our supported operation without treating discard as BSD DONTNEED.
    constexpr std::size_t size = 0x8000;
#ifdef _WIN32
    auto* memory = static_cast<unsigned char*>(VirtualAlloc(nullptr, size, MEM_RESERVE | MEM_COMMIT,
                                                          PAGE_READWRITE));
#else
    auto* memory = static_cast<unsigned char*>(mmap(nullptr, size, PROT_READ | PROT_WRITE,
                                                   MAP_PRIVATE | MAP_ANONYMOUS, -1, 0));
    if (memory == MAP_FAILED) memory = nullptr;
#endif
    Check(memory != nullptr);
    for (std::size_t i = 0; i < size; ++i) memory[i] = static_cast<unsigned char>(i * 7);
    const auto base = reinterpret_cast<std::uintptr_t>(memory);
    // Linux mmap need only be 4 KiB aligned. Choose an interior guest-aligned range.
    const auto aligned = (base + 0x3fff) & ~std::uintptr_t{0x3fff};
    CheckResult(S::Madvise(aligned, 0x4000, 3, [&](auto p) {
        return p >= base && p < base + size ? base + size : 0;
    }, [](auto p, auto length) {
#ifdef _WIN32
        WIN32_MEMORY_RANGE_ENTRY range{reinterpret_cast<void*>(p), static_cast<SIZE_T>(length)};
        return PrefetchVirtualMemory(GetCurrentProcess(), 1, &range, 0) ? 0 : S::NoMemory;
#else
        return madvise(reinterpret_cast<void*>(p), length, MADV_WILLNEED) == 0 ? 0 : S::NoMemory;
#endif
    }), 0);
    bool preserved = true;
    for (std::size_t i = 0; i < size; ++i) preserved &= memory[i] == static_cast<unsigned char>(i * 7);
    Check(preserved);
#ifdef _WIN32
    Check(VirtualFree(memory, 0, MEM_RELEASE));
#else
    Check(munmap(memory, size) == 0);
#endif
    std::cout << checks << " kernel-service checks passed (host/policy tests, not guest execution)\n";
}
