// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
// See LICENSE in the project root for the full license text.

// Original OpenOrbis application. No host-side service mocks or injected results.
#include <orbis/libkernel.h>
#include <stdio.h>
#include <stdint.h>
#include <string.h>

static uint8_t input[256], output[256];

static void* transform(void* argument) {
    const auto half = reinterpret_cast<uintptr_t>(argument);
    for (unsigned i = half * 128; i < (half + 1) * 128; ++i) {
        output[i] = static_cast<uint8_t>((input[i] ^ 0xa5u) + i);
    }
    return argument;
}

static int fail(const char* operation) {
    printf("service-roundtrip: FAIL %s\n", operation);
    for (;;) { sceKernelUsleep(100000); }
}

int main() {
    setvbuf(stdout, nullptr, _IONBF, 0);
    printf("service-roundtrip: begin\n");
    // These are the PS4 kernel open flags, not the SDK's generic musl flags.
    constexpr int read_only = 0, write_create_exclusive = 1 | 0x200 | 0x800;
    int fd = sceKernelOpen("/app0/challenge.bin", read_only, 0);
    if (fd < 0) return fail("open challenge");
    if (sceKernelRead(fd, input, sizeof(input)) != sizeof(input)) return fail("read challenge");
    uint8_t extra;
    if (sceKernelRead(fd, &extra, 1) != 0 || sceKernelClose(fd) != 0) return fail("challenge eof/close");
    OrbisPthread threads[2];
    for (uintptr_t half = 0; half < 2; ++half) {
        if (scePthreadCreate(&threads[half], nullptr, transform,
                             reinterpret_cast<void*>(half), "roundtrip") != 0) return fail("create");
    }
    for (uintptr_t half = 0; half < 2; ++half) {
        void* result = reinterpret_cast<void*>(3);
        if (scePthreadJoin(threads[half], &result) != 0 ||
            result != reinterpret_cast<void*>(half)) return fail("join/result");
    }
    fd = sceKernelOpen("/data/service-result.bin", write_create_exclusive, 0600);
    if (fd < 0) return fail("create result");
    if (sceKernelWrite(fd, output, sizeof(output)) != sizeof(output) ||
        sceKernelClose(fd) != 0) return fail("write/close");
    fd = sceKernelOpen("/data/service-result.bin", read_only, 0);
    uint8_t check[256];
    if (fd < 0 || sceKernelLseek(fd, 128, 0) != 128 ||
        sceKernelRead(fd, check + 128, 128) != 128 || sceKernelLseek(fd, 0, 0) != 0 ||
        sceKernelRead(fd, check, 128) != 128 || sceKernelClose(fd) != 0 ||
        memcmp(check, output, sizeof(output)) != 0) return fail("seek/readback");
    printf("service-roundtrip: PASS threads=2 bytes=256 seek=128\n");
    for (;;) { sceKernelUsleep(100000); }
}
