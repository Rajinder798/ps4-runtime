// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
// See LICENSE in the project root for the full license text.

// Original OpenOrbis application. No host-side service mocks or injected results.
// The read-back half of the per-title save persistence test: it never creates save
// data. It mounts an existing PS4RTSAVE01 read-only, checks result.bin against the
// same transform of the host's challenge that save_roundtrip stored, and finds the
// directory by name. A missing save must fail the mount, not create one.
#include <orbis/libkernel.h>
#include <orbis/SaveData.h>
#include <orbis/UserService.h>
#include <stdio.h>
#include <stdint.h>
#include <string.h>

static uint8_t input[256], expected[256], check[256];
static const char directory_name[] = "PS4RTSAVE01";

static int fail(const char* operation, int code) {
    printf("save-readback: FAIL %s 0x%08x\n", operation, static_cast<unsigned>(code));
    for (;;) { sceKernelUsleep(100000); }
}

int main() {
    setvbuf(stdout, nullptr, _IONBF, 0);
    printf("save-readback: begin\n");
    // PS4 kernel open flags, not the SDK's generic musl flags.
    constexpr int read_only = 0;
    int fd = sceKernelOpen("/app0/challenge.bin", read_only, 0);
    if (fd < 0) return fail("open challenge", fd);
    if (sceKernelRead(fd, input, sizeof(input)) != sizeof(input)) return fail("read challenge", 0);
    uint8_t extra;
    if (sceKernelRead(fd, &extra, 1) != 0 || sceKernelClose(fd) != 0) return fail("challenge eof/close", 0);
    for (unsigned i = 0; i < sizeof(input); ++i) {
        expected[i] = static_cast<uint8_t>((input[i] + 0x3cu) ^ (i * 7u));
    }

    OrbisUserServiceInitializeParams parameters{ORBIS_KERNEL_PRIO_FIFO_LOWEST};
    int code = sceUserServiceInitialize(&parameters);
    if (code != 0) return fail("user init", code);
    int user = -1;
    if ((code = sceUserServiceGetInitialUser(&user)) != 0) return fail("initial user", code);
    if ((code = sceSaveDataInitialize3(0)) != 0) return fail("save init", code);

    // Read-only, no CREATE: only a save carried over from an earlier launch can mount.
    OrbisSaveDataDirName name{};
    memcpy(name.data, directory_name, sizeof(directory_name));
    OrbisSaveDataMount2 request{};
    request.userId = user;
    request.dirName = &name;
    request.blocks = ORBIS_SAVE_DATA_BLOCKS_MIN2;
    request.mountMode = ORBIS_SAVE_DATA_MOUNT_MODE_RDONLY;
    OrbisSaveDataMountResult mounted{};
    if ((code = sceSaveDataMount2(&request, &mounted)) != 0) return fail("mount existing", code);
    char path[64];
    snprintf(path, sizeof(path), "%.16s/result.bin", mounted.mountPathName);
    fd = sceKernelOpen(path, read_only, 0);
    if (fd < 0) return fail("open saved result", fd);
    if (sceKernelRead(fd, check, sizeof(check)) != sizeof(check) || sceKernelRead(fd, &extra, 1) != 0 ||
        sceKernelClose(fd) != 0 || memcmp(check, expected, sizeof(expected)) != 0)
        return fail("readback", 0);
    OrbisSaveDataMountPoint point{};
    memcpy(point.data, mounted.mountPathName, sizeof(point.data));
    if ((code = sceSaveDataUmount(&point)) != 0) return fail("unmount", code);

    OrbisSaveDataDirName found[2]{};
    OrbisSaveDataDirNameSearchCond condition{};
    condition.userId = user;
    condition.dirName = &name;
    OrbisSaveDataDirNameSearchResult result{};
    result.dirNames = found;
    result.dirNamesNum = 2;
    if ((code = sceSaveDataDirNameSearch(&condition, &result)) != 0) return fail("search", code);
    if (result.hitNum != 1 || strcmp(found[0].data, directory_name) != 0) return fail("search result", 0);

    printf("save-readback: PASS bytes=256 existing=1 search=1\n");
    for (;;) { sceKernelUsleep(100000); }
}
