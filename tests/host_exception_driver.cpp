// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later

#include <windows.h>
#include <cstdio>
#include <cstring>
#include "core/host_exception_policy.h"

static thread_local bool guest_thread = false;
static unsigned deferred = 0;
static unsigned retained = 0;

static LONG WINAPI Observe(EXCEPTION_POINTERS* exception) noexcept {
    const bool defer = Core::DeferHostCppException(
        exception->ExceptionRecord->ExceptionCode, guest_thread);
    const char* message = defer ? "deferred\n" : "retained\n";
    DWORD written = 0;
    WriteFile(GetStdHandle(STD_OUTPUT_HANDLE), message,
              static_cast<DWORD>(std::strlen(message)), &written, nullptr);
    if (defer) {
        ++deferred;
    } else {
        ++retained;
    }
    // Exercise Windows' real stack search even in the retained-path tests.
    // This observer does not emulate guest fault dispatch or engine shutdown.
    return EXCEPTION_CONTINUE_SEARCH;
}

int main(int argc, char** argv) {
    SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX);
    if (argc != 2) {
        return 2;
    }
    const bool caught_host = std::strcmp(argv[1], "caught-host") == 0;
    const bool caught_guest = std::strcmp(argv[1], "caught-guest") == 0;
    const bool unhandled_host = std::strcmp(argv[1], "unhandled-host") == 0;
    const bool unhandled_guest = std::strcmp(argv[1], "unhandled-guest") == 0;
    const bool access_violation = std::strcmp(argv[1], "host-access-violation") == 0;
    const bool native_unhandled = std::strcmp(argv[1], "native-unhandled") == 0;
    if (!caught_host && !caught_guest && !unhandled_host && !unhandled_guest && !access_violation &&
        !native_unhandled) {
        return 2;
    }
    if (native_unhandled) {
        throw 42; // Reference for this toolchain's ordinary uncaught C++ termination status.
    }
    guest_thread = caught_guest || unhandled_guest;
    const auto handler = AddVectoredExceptionHandler(0, Observe);
    if (handler == nullptr) {
        return 3;
    }
    if (access_violation) {
        auto* page = static_cast<volatile unsigned char*>(
            VirtualAlloc(nullptr, 4096, MEM_RESERVE | MEM_COMMIT, PAGE_NOACCESS));
        if (page == nullptr) {
            return 4;
        }
        return *page; // Must fail through native unhandled access-violation handling.
    }
    if (unhandled_host || unhandled_guest) {
        throw 42; // Must fail, including the deferred host path.
    }
    bool caught = false;
    try {
        throw 42;
    } catch (int value) {
        caught = value == 42;
    }
    RemoveVectoredExceptionHandler(handler);
    if (!caught || deferred != (caught_host ? 1u : 0u) || retained != (caught_guest ? 1u : 0u)) {
        return 5;
    }
    std::puts("caught=42");
    return 0;
}
