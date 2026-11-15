// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
// See LICENSE in the project root for the full license text.

// Original OpenOrbis application. No host-side service mocks or injected results.
// Saves a transform of a host-generated challenge, remounts read-only, reads it back
// and finds the directory by name. The host later checks the stored file itself.
#include <orbis/libkernel.h>
#include <orbis/SaveData.h>
#include <orbis/UserService.h>
#include <stdio.h>
#include <stdint.h>
#include <string.h>

static uint8_t input[256], expected[256], check[256];
static const char directory_name[] = "PS4RTSAVE01";

static int fail(const char* operation, int code) {
    printf("save-roundtrip: FAIL %s 0x%08x\n", operation, static_cast<unsigned>(code));
    for (;;) { sceKernelUsleep(100000); }
}

static int mount(int user, uint32_t mode, OrbisSaveDataMountResult* result) {
    OrbisSaveDataDirName name{};
    memcpy(name.data, directory_name, sizeof(directory_name));
    OrbisSaveDataMount2 request{};
    request.userId = user;
    request.dirName = &name;
    request.blocks = ORBIS_SAVE_DATA_BLOCKS_MIN2;
    request.mountMode = mode;
    memset(result, 0, sizeof(*result));
    return sceSaveDataMount2(&request, result);
}

static int unmount(const OrbisSaveDataMountResult& result) {
    OrbisSaveDataMountPoint point{};
    memcpy(point.data, result.mountPathName, sizeof(point.data));
    return sceSaveDataUmount(&point);
}

int main() {
    setvbuf(stdout, nullptr, _IONBF, 0);
    printf("save-roundtrip: begin\n");
    // These are the PS4 kernel open flags, not the SDK's generic musl flags.
    constexpr int read_only = 0, write_create_exclusive = 1 | 0x200 | 0x800;
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

    // A fresh profile has no such directory, so CREATE must succeed.
    OrbisSaveDataMountResult mounted;
    if ((code = mount(user, ORBIS_SAVE_DATA_MOUNT_MODE_CREATE | ORBIS_SAVE_DATA_MOUNT_MODE_RDWR, &mounted)) != 0)
        return fail("create mount", code);
    char path[64];
    snprintf(path, sizeof(path), "%.16s/result.bin", mounted.mountPathName);
    fd = sceKernelOpen(path, write_create_exclusive, 0600);
    if (fd < 0) return fail("create result", fd);
    if (sceKernelWrite(fd, expected, sizeof(expected)) != sizeof(expected) || sceKernelClose(fd) != 0)
        return fail("write/close", 0);
    if ((code = unmount(mounted)) != 0) return fail("unmount after write", code);

    // Remount read-only so the readback cannot come from the open write mount.
    if ((code = mount(user, ORBIS_SAVE_DATA_MOUNT_MODE_RDONLY, &mounted)) != 0) return fail("remount", code);
    snprintf(path, sizeof(path), "%.16s/result.bin", mounted.mountPathName);
    fd = sceKernelOpen(path, read_only, 0);
    if (fd < 0) return fail("open saved result", fd);
    if (sceKernelRead(fd, check, sizeof(check)) != sizeof(check) || sceKernelRead(fd, &extra, 1) != 0 ||
        sceKernelClose(fd) != 0 || memcmp(check, expected, sizeof(expected)) != 0)
        return fail("readback", 0);
    if ((code = unmount(mounted)) != 0) return fail("unmount after read", code);

    OrbisSaveDataDirName name{}, found[2]{};
    memcpy(name.data, directory_name, sizeof(directory_name));
    OrbisSaveDataDirNameSearchCond condition{};
    condition.userId = user;
    condition.dirName = &name;
    OrbisSaveDataDirNameSearchResult result{};
    result.dirNames = found;
    result.dirNamesNum = 2;
    if ((code = sceSaveDataDirNameSearch(&condition, &result)) != 0) return fail("search", code);
    if (result.hitNum != 1 || strcmp(found[0].data, directory_name) != 0) return fail("search result", 0);

    printf("save-roundtrip: PASS bytes=256 remount=1 search=1\n");
    for (;;) { sceKernelUsleep(100000); }
}
