// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
// See LICENSE in the project root for the full license text.

// Original synthetic stereo PCM, with explicit silence/swap negative inputs.
#include <orbis/libkernel.h>
#include <orbis/AudioOut.h>
#include <orbis/UserService.h>
#include <stdint.h>
#include <stdio.h>

static int fail(const char* operation) {
    printf("audio-pattern: FAIL %s\n", operation);
    for (;;) sceKernelUsleep(100000);
}

int main() {
    setvbuf(stdout, nullptr, _IONBF, 0);
    printf("audio-pattern: begin\n");
    uint8_t challenge[5], extra;
    const int input = sceKernelOpen("/app0/audio.bin", 0, 0);
    if (input < 0 || sceKernelRead(input, challenge, 5) != 5 ||
        sceKernelRead(input, &extra, 1) != 0 || sceKernelClose(input) != 0) return fail("challenge");
    for (unsigned i = 0; i < 4; ++i) {
        if (challenge[i] > 3) return fail("period");
        for (unsigned j = 0; j < i; ++j)
            if (challenge[i] == challenge[j]) return fail("duplicate period");
    }
    if (challenge[4] > 2) return fail("mode");
    OrbisUserServiceInitializeParams parameters{ORBIS_KERNEL_PRIO_FIFO_LOWEST};
    if (sceUserServiceInitialize(&parameters) != 0 || sceAudioOutInit() != 0) return fail("initialize");
    const int port = sceAudioOutOpen(ORBIS_USER_SERVICE_USER_ID_SYSTEM,
        ORBIS_AUDIO_OUT_PORT_TYPE_MAIN, 0, 256, 48000, ORBIS_AUDIO_OUT_PARAM_FORMAT_S16_STEREO);
    if (port <= 0) return fail("open");
    constexpr unsigned periods[4] = {64, 96, 128, 192};
    int16_t samples[512];
    for (unsigned phase = 0; phase < 4; ++phase) {
        for (unsigned block = 0; block < 192; ++block) {
            for (unsigned frame = 0; frame < 256; ++frame) {
                for (unsigned channel = 0; channel < 2; ++channel) {
                    int16_t value = 0;
                    if ((phase == 1 || phase == 2) && challenge[4] != 1) {
                        const unsigned side = challenge[4] == 2 ? 1 - channel : channel;
                        const unsigned period = periods[challenge[(phase - 1) * 2 + side]];
                        value = (block * 256 + frame) % period < period / 2 ? 2000 : -2000;
                    }
                    samples[frame * 2 + channel] = value;
                }
            }
            if (sceAudioOutOutput(port, nullptr) < 0 || sceAudioOutOutput(port, samples) < 0)
                return fail("output");
        }
        printf("audio-pattern: phase=%u submitted blocks=192\n", phase);
    }
    if (sceAudioOutOutput(port, nullptr) < 0) return fail("drain");
    sceKernelUsleep(500000);
    if (sceAudioOutClose(port) != 0) return fail("close");
    printf("audio-pattern: PASS phases=4 blocks=768 cleanup=1\n");
    for (;;) sceKernelUsleep(100000);
}
