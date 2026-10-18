// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
// See LICENSE in the project root for the full license text.

// Original CPU framebuffer application; no proprietary SDK, shaders or assets.
#include <orbis/libkernel.h>
#include <orbis/VideoOut.h>
#include <stdint.h>
#include <stdio.h>

static int fail(const char* operation) {
    printf("videoout-pattern: FAIL %s\n", operation);
    for (;;) sceKernelUsleep(100000);
}

static bool advance(unsigned phase) {
    const int fd = sceKernelOpen("/app0/phase.bin", 0, 0);
    if (fd < 0) return false;
    uint8_t value = 0;
    if (sceKernelRead(fd, &value, 1) != 1 || sceKernelClose(fd) != 0 || value > 2)
        fail("control");
    return value >= phase + 1;
}

int main() {
    setvbuf(stdout, nullptr, _IONBF, 0);
    printf("videoout-pattern: begin\n");
    uint8_t challenge[4], extra;
    const int fd = sceKernelOpen("/app0/palette.bin", 0, 0);
    if (fd < 0) return fail("open palette");
    if (sceKernelRead(fd, challenge, 4) != 4 || sceKernelRead(fd, &extra, 1) != 0 ||
        sceKernelClose(fd) != 0) return fail("read palette");
    for (unsigned i = 0; i < 4; ++i) {
        if (challenge[i] > 7) return fail("palette value");
        for (unsigned j = 0; j < i; ++j)
            if (challenge[i] == challenge[j]) return fail("palette duplicate");
    }
    constexpr unsigned width = 640, height = 360;
    constexpr size_t allocation = 0x400000, alignment = 0x200000, stride = 0x100000;
    off_t offset;
    void* memory = nullptr;
    if (sceKernelAllocateDirectMemory(0, sceKernelGetDirectMemorySize(), allocation,
                                     alignment, 3, &offset) != 0) return fail("allocate");
    if (sceKernelMapDirectMemory(&memory, allocation, 0x33, 0, offset, alignment) != 0)
        return fail("map");
    void* buffers[2] = {memory, static_cast<uint8_t*>(memory) + stride};
    for (unsigned phase = 0; phase < 2; ++phase) {
        auto* pixels = static_cast<uint32_t*>(buffers[phase]);
        for (unsigned y = 0; y < height; ++y) {
            for (unsigned x = 0; x < width; ++x) {
                const unsigned color = challenge[(x / 80 + y / 45 + phase) % 4];
                pixels[y * width + x] = 0xff000000u | ((color & 1) ? 0xffu : 0) |
                    ((color & 2) ? 0xff00u : 0) | ((color & 4) ? 0xff0000u : 0);
            }
        }
    }
    const int video = sceVideoOutOpen(ORBIS_VIDEO_USER_MAIN, ORBIS_VIDEO_OUT_BUS_MAIN, 0, nullptr);
    if (video < 0) return fail("open video");
    OrbisVideoOutBufferAttribute attribute{};
    sceVideoOutSetBufferAttribute(&attribute, ORBIS_VIDEO_OUT_PIXEL_FORMAT_A8B8G8R8_SRGB,
                                 ORBIS_VIDEO_OUT_TILING_MODE_LINEAR, 0, width, height, width);
    const int group = sceVideoOutRegisterBuffers(video, 0, buffers, 2, &attribute);
    if (group < 0) return fail("register");
    int64_t sequence = 0;
    for (unsigned phase = 0; phase < 2; ++phase) {
        unsigned frames = 0;
        do {
            if (sceVideoOutSubmitFlip(video, phase, ORBIS_VIDEO_OUT_FLIP_VSYNC, ++sequence) != 0)
                return fail("submit");
            bool completed = false;
            for (unsigned poll = 0; poll < 2000; ++poll) {
                OrbisVideoOutFlipStatus status{};
                if (sceVideoOutGetFlipStatus(video, &status) != 0) return fail("flip status");
                if (status.flipArg == sequence && status.currentBuffer == static_cast<int>(phase) &&
                    status.num > 0) { completed = true; break; }
                sceKernelUsleep(1000);
            }
            if (!completed) return fail("flip timeout");
            if (frames++ == 0) printf("videoout-pattern: phase=%u ready\n", phase);
            sceKernelUsleep(16000);
        } while (frames % 12 != 0 || !advance(phase));
    }
    if (sceVideoOutUnregisterBuffers(video, group) != 0 || sceVideoOutClose(video) != 0)
        return fail("video cleanup");
    if (sceKernelMunmap(memory, allocation) != 0 || sceKernelReleaseDirectMemory(offset, allocation) != 0)
        return fail("memory cleanup");
    printf("videoout-pattern: PASS phases=2 cleanup=1\n");
    for (;;) sceKernelUsleep(100000);
}
