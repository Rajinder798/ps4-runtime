// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
// Opt-in Pad/VideoOut research fixture. No audio, host phases or input synthesis.
#include <orbis/libkernel.h>
#include <orbis/VideoOut.h>
#include <orbis/Pad.h>
#include <orbis/UserService.h>
#include <stdint.h>
#include <stdio.h>

static int fail(const char* operation) {
    printf("pad-axes: FAIL %s\n", operation);
    for (;;) sceKernelUsleep(100000);
}

struct Observation {
    uint32_t sequence, buttons;
    uint64_t timestamp, flip;
    uint8_t axes[4], connected, reserved[3];
};
static_assert(sizeof(Observation) == 32, "Pad axes schema 1 record layout");

static uint32_t color(unsigned value) {
    return 0xff000000u | ((value & 1) ? 0xffu : 0) |
        ((value & 2) ? 0xff00u : 0) | ((value & 4) ? 0xff0000u : 0);
}

int main() {
    setvbuf(stdout, nullptr, _IONBF, 0);
    printf("pad-axes: begin schema=1\n");
    uint8_t palette[4], extra;
    int fd = sceKernelOpen("/app0/palette.bin", 0, 0);
    if (fd < 0 || sceKernelRead(fd, palette, 4) != 4 || sceKernelRead(fd, &extra, 1) != 0 ||
        sceKernelClose(fd) != 0) return fail("palette");
    for (unsigned i = 0; i < 4; ++i) {
        if (palette[i] > 7) return fail("palette range");
        for (unsigned j = 0; j < i; ++j)
            if (palette[i] == palette[j]) return fail("palette duplicate");
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
    const int video = sceVideoOutOpen(ORBIS_VIDEO_USER_MAIN, ORBIS_VIDEO_OUT_BUS_MAIN, 0, nullptr);
    if (video < 0) return fail("video open");
    OrbisVideoOutBufferAttribute attribute{};
    sceVideoOutSetBufferAttribute(&attribute, ORBIS_VIDEO_OUT_PIXEL_FORMAT_A8B8G8R8_SRGB,
                                 ORBIS_VIDEO_OUT_TILING_MODE_LINEAR, 0, width, height, width);
    if (sceVideoOutRegisterBuffers(video, 0, buffers, 2, &attribute) < 0) return fail("video register");
    if (scePadInit() != 0) return fail("pad init");
    OrbisUserServiceInitializeParams parameters{ORBIS_KERNEL_PRIO_FIFO_LOWEST};
    if (sceUserServiceInitialize(&parameters) != 0) return fail("user init");
    int user = -1;
    if (sceUserServiceGetInitialUser(&user) != 0) return fail("initial user");
    const int pad = scePadOpen(user, ORBIS_PAD_PORT_TYPE_STANDARD, 0, nullptr);
    if (pad < 0) return fail("pad open");
    struct Header { char magic[8]; uint32_t version, record_size; };
    const Header header{{'P','A','D','A','X','1',0,0}, 1, sizeof(Observation)};
    fd = sceKernelOpen("/data/pad-axes.bin", 1 | 0x200 | 0x800, 0600);
    if (fd < 0 || sceKernelWrite(fd, &header, sizeof(header)) != sizeof(header) ||
        sceKernelClose(fd) != 0) return fail("observations create");
    for (unsigned sequence = 0; sequence < 6000; ++sequence) {
        OrbisPadData data{};
        const int rc = scePadReadState(pad, &data);
        if (rc != 0) return fail("pad read");
        if (!data.connected) return fail("pad disconnected");
        if (data.timestamp == 0) return fail("pad timestamp");
        Observation observation{sequence, data.buttons, data.timestamp, sequence + 1,
            {data.leftStick.x, data.leftStick.y, data.rightStick.x, data.rightStick.y}, data.connected, {0,0,0}};
        auto* pixels = static_cast<uint32_t*>(buffers[sequence % 2]);
        // Four full-width bars display actual guest LX, LY, RX, RY, top to bottom.
        for (unsigned y = 0; y < height; ++y) {
            const unsigned axis = y / 90;
            const unsigned end = observation.axes[axis] * (width - 1) / 255;
            for (unsigned x = 0; x < width; ++x)
                pixels[y * width + x] = x <= end ? color(palette[axis]) : 0xff202020u;
        }
        // Exact image identity: sequence, raw axes, buttons, connection, LSB first.
        for (unsigned bit = 0; bit < 32; ++bit) {
            pixels[bit] = (sequence & (1u << bit)) ? 0xffffffffu : 0xff000000u;
            pixels[32 + bit] = (observation.axes[bit / 8] & (1u << (bit % 8))) ? 0xffffffffu : 0xff000000u;
            pixels[64 + bit] = (data.buttons & (1u << bit)) ? 0xffffffffu : 0xff000000u;
        }
        pixels[96] = data.connected ? 0xffffffffu : 0xff000000u;
        if (sceVideoOutSubmitFlip(video, sequence % 2, ORBIS_VIDEO_OUT_FLIP_VSYNC, sequence + 1) != 0)
            return fail("flip submit");
        bool completed = false;
        for (unsigned poll = 0; poll < 2000; ++poll) {
            OrbisVideoOutFlipStatus status{};
            if (sceVideoOutGetFlipStatus(video, &status) != 0) return fail("flip status");
            if (status.flipArg == static_cast<int64_t>(sequence + 1) &&
                status.currentBuffer == static_cast<int>(sequence % 2) && status.num > 0) {
                completed = true; break;
            }
            sceKernelUsleep(1000);
        }
        if (!completed) return fail("flip timeout");
        fd = sceKernelOpen("/data/pad-axes.bin", 1, 0600);
        if (fd < 0 || sceKernelLseek(fd, 0, 2) != sizeof(header) + sequence * sizeof(Observation) ||
            sceKernelWrite(fd, &observation, sizeof(observation)) != sizeof(observation) ||
            sceKernelClose(fd) != 0) return fail("observations append");
        if (sequence == 0) printf("pad-axes: ready schema=1\n");
        printf("pad-axes: sample=%u buttons=%u timestamp=%llu flip=%llu lx=%u ly=%u rx=%u ry=%u connected=%u\n",
               sequence, data.buttons, static_cast<unsigned long long>(data.timestamp),
               static_cast<unsigned long long>(observation.flip), observation.axes[0], observation.axes[1],
               observation.axes[2], observation.axes[3], observation.connected);
        sceKernelUsleep(100000);
    }
    return fail("observation limit");
}
