// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
// See LICENSE in the project root for the full license text.

// Original live fixture: repeated pad reads drive pixels and PCM without host phase files.
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
static constexpr unsigned audio_frames = 2048;

static int fail(const char* operation) {
    printf("live-av: FAIL %s\n", operation);
    for (;;) sceKernelUsleep(100000);
}

static void* audio_worker(void*) {
    constexpr unsigned periods[4] = {64, 96, 128, 192};
    unsigned blocks = 0;
    int16_t samples[audio_frames * 2];
    for (;;) {
        const unsigned command = __atomic_load_n(&audio_command, __ATOMIC_ACQUIRE);
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
        __atomic_store_n(&audio_progress, blocks, __ATOMIC_RELEASE);
    }
}

static void read_exact(const char* path, uint8_t* data, unsigned size) {
    uint8_t extra;
    const int fd = sceKernelOpen(path, 0, 0);
    if (fd < 0 || sceKernelRead(fd, data, size) != size || sceKernelRead(fd, &extra, 1) != 0 ||
        sceKernelClose(fd) != 0) fail("challenge");
}

int main() {
    setvbuf(stdout, nullptr, _IONBF, 0);
    printf("live-av: begin\n");
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
    if (scePthreadCreate(&thread, nullptr, audio_worker, nullptr, "live-audio") != 0)
        return fail("audio create");
    // Each closed record is independently readable while the guest keeps running.
    // The host never writes this file and provides no phase/advance control.
    struct Observation { uint32_t sequence, buttons; uint64_t timestamp, flip; };
    static_assert(sizeof(Observation) == 24, "Stable live observation layout");
    int output = sceKernelOpen("/data/live-input.bin", 1 | 0x200 | 0x800, 0600);
    if (output < 0 || sceKernelClose(output) != 0) return fail("observations create");
    unsigned previous = ~0u, changes = 0;
    uint64_t sequence = 0;
    for (;;) {
        OrbisPadData data{};
        if (scePadReadState(pad, &data) != 0 || !data.connected || data.timestamp == 0)
            return fail("pad read/connection");
        const unsigned pressed = (data.buttons & ORBIS_PAD_BUTTON_CROSS) ? 1 : 0;
        __atomic_store_n(&audio_command, pressed, __ATOMIC_RELEASE);
        if (__atomic_load_n(&audio_failed, __ATOMIC_ACQUIRE)) return fail("audio worker");
        if (data.buttons != previous) {
            // Eight independently checked pixels bind readback to this exact
            // input observation, including repeated neutral/pressed images.
            auto* pixels = static_cast<uint32_t*>(buffers[pressed]);
            for (unsigned bit = 0; bit < 8; ++bit)
                pixels[bit] = (changes & (1u << bit)) ? 0xffffffffu : 0xff000000u;
        }
        if (sceVideoOutSubmitFlip(video, pressed, ORBIS_VIDEO_OUT_FLIP_VSYNC, ++sequence) != 0)
            return fail("submit");
        bool completed = false;
        for (unsigned poll = 0; poll < 2000; ++poll) {
            OrbisVideoOutFlipStatus status{};
            if (sceVideoOutGetFlipStatus(video, &status) != 0) return fail("flip status");
            if (status.flipArg == static_cast<int64_t>(sequence) &&
                status.currentBuffer == static_cast<int>(pressed) && status.num > 0) {
                completed = true; break;
            }
            sceKernelUsleep(1000);
        }
        if (!completed) return fail("flip timeout");
        if (data.buttons != previous) {
            if (changes == 128) return fail("observation limit");
            Observation observation{changes, data.buttons, data.timestamp, sequence};
            output = sceKernelOpen("/data/live-input.bin", 1, 0600);
            if (output < 0 || sceKernelLseek(output, 0, 2) != changes * sizeof(Observation) ||
                sceKernelWrite(output, &observation, sizeof(observation)) != sizeof(observation) ||
                sceKernelClose(output) != 0) return fail("observations append");
            if (changes == 0) printf("live-av: ready running=1 audio_thread=1\n");
            printf("live-av: sample=%u buttons=%u timestamp=%llu flip=%llu audio_blocks=%u\n",
                   changes, data.buttons, static_cast<unsigned long long>(data.timestamp),
                   static_cast<unsigned long long>(sequence),
                   __atomic_load_n(&audio_progress, __ATOMIC_ACQUIRE));
            previous = data.buttons;
            ++changes;
        }
        sceKernelUsleep(16000);
    }
}
