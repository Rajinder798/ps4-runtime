// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
// See LICENSE in the project root for the full license text.

// Original combined fixture: observed pad state drives pixels and worker PCM.
#include <orbis/libkernel.h>
#include <orbis/VideoOut.h>
#include <orbis/Pad.h>
#include <orbis/AudioOut.h>
#include <orbis/UserService.h>
#include <stdint.h>
#include <stdio.h>

static uint8_t audio_challenge[5];
static unsigned audio_command = 0, audio_progress = 0, audio_failed = 0;
static int audio_port;
// A supported larger buffer reduces wakeup pressure during Vulkan presentation.
static constexpr unsigned audio_frames = 2048, minimum_audio_blocks = 24;

static int fail(const char* operation) {
    printf("interactive-av: FAIL %s\n", operation);
    for (;;) sceKernelUsleep(100000);
}

static void* audio_worker(void*) {
    constexpr unsigned periods[4] = {64, 96, 128, 192};
    unsigned previous = ~0u, blocks = 0;
    int16_t samples[audio_frames * 2];
    for (;;) {
        const unsigned command = __atomic_load_n(&audio_command, __ATOMIC_ACQUIRE);
        if (command == ~0u) break;
        if (command != previous) { previous = command; blocks = 0; }
        for (unsigned frame = 0; frame < audio_frames; ++frame) {
            for (unsigned channel = 0; channel < 2; ++channel) {
                int16_t value = 0;
                // Low bit comes from the actual observed Cross bit, not phase.bin.
                if ((command & 1) && audio_challenge[4] != 1) {
                    const unsigned side = audio_challenge[4] == 2 ? 1 - channel : channel;
                    const unsigned period = periods[audio_challenge[side]];
                    value = (blocks * audio_frames + frame) % period < period / 2 ? 2000 : -2000;
                }
                samples[frame * 2 + channel] = value;
            }
        }
        if (sceAudioOutOutput(audio_port, nullptr) < 0 || sceAudioOutOutput(audio_port, samples) < 0) {
            __atomic_store_n(&audio_failed, 1, __ATOMIC_RELEASE);
            return reinterpret_cast<void*>(1);
        }
        ++blocks;
        __atomic_store_n(&audio_progress, ((command >> 1) << 20) | blocks, __ATOMIC_RELEASE);
    }
    if (sceAudioOutOutput(audio_port, nullptr) < 0) return reinterpret_cast<void*>(1);
    sceKernelUsleep(500000);
    if (sceAudioOutClose(audio_port) != 0) return reinterpret_cast<void*>(1);
    return nullptr;
}

static bool advance(unsigned state) {
    const int fd = sceKernelOpen("/app0/phase.bin", 0, 0);
    if (fd < 0) return false;
    uint8_t value = 0;
    if (sceKernelRead(fd, &value, 1) != 1 || sceKernelClose(fd) != 0 || value > 3)
        fail("control");
    return value >= state + 1;
}

static void read_exact(const char* path, uint8_t* data, unsigned size) {
    uint8_t extra;
    const int fd = sceKernelOpen(path, 0, 0);
    if (fd < 0 || sceKernelRead(fd, data, size) != size || sceKernelRead(fd, &extra, 1) != 0 ||
        sceKernelClose(fd) != 0) fail("challenge");
}

int main() {
    setvbuf(stdout, nullptr, _IONBF, 0);
    printf("interactive-av: begin\n");
    uint8_t palette[4];
    read_exact("/app0/palette.bin", palette, 4);
    read_exact("/app0/audio.bin", audio_challenge, 5);
    for (unsigned i = 0; i < 4; ++i) {
        if (palette[i] > 7 || audio_challenge[i] > 3) return fail("challenge value");
        for (unsigned j = 0; j < i; ++j)
            if (palette[i] == palette[j] || audio_challenge[i] == audio_challenge[j])
                return fail("challenge duplicate");
    }
    if (audio_challenge[4] > 2) return fail("audio mode");
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
                const unsigned color = palette[(x / 80 + y / 45 + phase) % 4];
                pixels[y * width + x] = 0xff000000u | ((color & 1) ? 0xffu : 0) |
                    ((color & 2) ? 0xff00u : 0) | ((color & 4) ? 0xff0000u : 0);
            }
        }
    }
    const int video = sceVideoOutOpen(ORBIS_VIDEO_USER_MAIN, ORBIS_VIDEO_OUT_BUS_MAIN, 0, nullptr);
    if (video < 0) return fail("video open");
    OrbisVideoOutBufferAttribute attribute{};
    sceVideoOutSetBufferAttribute(&attribute, ORBIS_VIDEO_OUT_PIXEL_FORMAT_A8B8G8R8_SRGB,
                                 ORBIS_VIDEO_OUT_TILING_MODE_LINEAR, 0, width, height, width);
    const int group = sceVideoOutRegisterBuffers(video, 0, buffers, 2, &attribute);
    if (group < 0) return fail("video register");
    if (scePadInit() != 0) return fail("pad init");
    OrbisUserServiceInitializeParams parameters{ORBIS_KERNEL_PRIO_FIFO_LOWEST};
    if (sceUserServiceInitialize(&parameters) != 0) return fail("user init");
    int user = -1;
    if (sceUserServiceGetInitialUser(&user) != 0) return fail("initial user");
    const int pad = scePadOpen(user, ORBIS_PAD_PORT_TYPE_STANDARD, 0, nullptr);
    if (pad < 0 || sceAudioOutInit() != 0) return fail("pad/audio init");
    audio_port = sceAudioOutOpen(ORBIS_USER_SERVICE_USER_ID_SYSTEM,
        ORBIS_AUDIO_OUT_PORT_TYPE_MAIN, 0, audio_frames, 48000, ORBIS_AUDIO_OUT_PARAM_FORMAT_S16_STEREO);
    if (audio_port <= 0) return fail("audio open");
    OrbisPthread thread;
    if (scePthreadCreate(&thread, nullptr, audio_worker, nullptr, "interactive-audio") != 0)
        return fail("audio create");
    struct Observation { uint32_t buttons; uint8_t connected, reserved[3]; uint64_t timestamp; };
    static_assert(sizeof(Observation) == 16, "Stable observation layout");
    Observation observations[3]{};
    int64_t sequence = 0;
    for (unsigned state = 0; state < 3; ++state) {
        const unsigned wanted = state == 1 ? ORBIS_PAD_BUTTON_CROSS : 0;
        OrbisPadData data{};
        bool observed = false;
        for (unsigned poll = 0; poll < 800; ++poll) {
            if (scePadReadState(pad, &data) != 0) return fail("pad read");
            if (data.connected && data.buttons == wanted && data.timestamp > 0) { observed = true; break; }
            sceKernelUsleep(10000);
        }
        if (!observed) return fail("input timeout");
        observations[state].buttons = data.buttons;
        observations[state].connected = data.connected;
        observations[state].timestamp = data.timestamp;
        const unsigned pressed = (data.buttons & ORBIS_PAD_BUTTON_CROSS) ? 1 : 0;
        __atomic_store_n(&audio_command, (state << 1) | pressed, __ATOMIC_RELEASE);
        unsigned frames = 0;
        bool announced = false;
        do {
            if (__atomic_load_n(&audio_failed, __ATOMIC_ACQUIRE)) return fail("audio worker");
            if (sceVideoOutSubmitFlip(video, pressed, ORBIS_VIDEO_OUT_FLIP_VSYNC, ++sequence) != 0)
                return fail("submit");
            bool completed = false;
            for (unsigned poll = 0; poll < 2000; ++poll) {
                OrbisVideoOutFlipStatus status{};
                if (sceVideoOutGetFlipStatus(video, &status) != 0) return fail("flip status");
                if (status.flipArg == sequence && status.currentBuffer == static_cast<int>(pressed) &&
                    status.num > 0) { completed = true; break; }
                sceKernelUsleep(1000);
            }
            if (!completed) return fail("flip timeout");
            const unsigned progress = __atomic_load_n(&audio_progress, __ATOMIC_ACQUIRE);
            if (!announced && (progress >> 20) == state && (progress & 0xfffffu) >= minimum_audio_blocks) {
                printf("interactive-av: state=%u buttons=%u ready\n", state, data.buttons);
                announced = true;
            }
            ++frames;
            sceKernelUsleep(16000);
        } while (!announced || frames % 12 != 0 || !advance(state));
    }
    __atomic_store_n(&audio_command, ~0u, __ATOMIC_RELEASE);
    void* status = reinterpret_cast<void*>(1);
    if (scePthreadJoin(thread, &status) != 0 || status != nullptr) return fail("audio join/close");
    if (scePadClose(pad) != 0) return fail("pad close");
    const int output = sceKernelOpen("/data/input-result.bin", 1 | 0x200 | 0x800, 0600);
    if (output < 0 || sceKernelWrite(output, observations, sizeof(observations)) != sizeof(observations) ||
        sceKernelClose(output) != 0) return fail("observations");
    if (sceVideoOutUnregisterBuffers(video, group) != 0 || sceVideoOutClose(video) != 0 ||
        sceKernelMunmap(memory, allocation) != 0 || sceKernelReleaseDirectMemory(offset, allocation) != 0)
        return fail("video/memory cleanup");
    printf("interactive-av: PASS states=3 audio_thread=1 cleanup=1\n");
    for (;;) sceKernelUsleep(100000);
}
