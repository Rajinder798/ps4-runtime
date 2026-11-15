// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
// See LICENSE in the project root for the full license text.

// Original OpenOrbis application. No host-side service mocks or injected results.
// A save that must outlive the launch: each run reads the counter left by the
// previous launch (0 when there is no save), stores count + 1, remounts read-only
// and checks it. The host stages the previous save, computes the expected line
// from it, then checks the stored file itself before keeping it.
#include <orbis/libkernel.h>
#include <orbis/SaveData.h>
#include <orbis/UserService.h>
#include <stdio.h>
#include <stdint.h>
#include <string.h>

static const char directory_name[] = "PS4RTCOUNT";
static const char magic[8] = {'P', 'S', '4', 'R', 'T', 'C', 'N', 'T'};
// sceSaveDataMount2 result for a missing directory, as observed on the pinned engine.
static constexpr int save_not_found = static_cast<int>(0x809f0008u);

struct Counter {
    char magic[8];
    uint32_t count;
    uint32_t check;  // ~count, so a damaged file cannot pass as a valid count
};
static_assert(sizeof(Counter) == 16, "counter.bin is 16 bytes");

static int fail(const char* operation, int code) {
    printf("save-counter: FAIL %s 0x%08x\n", operation, static_cast<unsigned>(code));
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

// PS4 kernel open flags, not the SDK's generic musl flags.
static constexpr int read_only = 0, write_create = 1 | 0x200;

// Reads exactly one valid Counter from the mounted save; returns 0 on success.
static int read_counter(const OrbisSaveDataMountResult& mounted, uint32_t* count) {
    char path[64];
    snprintf(path, sizeof(path), "%.16s/counter.bin", mounted.mountPathName);
    int fd = sceKernelOpen(path, read_only, 0);
    if (fd < 0) return fd;
    Counter value{};
    uint8_t extra;
    bool valid = sceKernelRead(fd, &value, sizeof(value)) == sizeof(value) && sceKernelRead(fd, &extra, 1) == 0;
    if (sceKernelClose(fd) != 0 || !valid || memcmp(value.magic, magic, sizeof(magic)) != 0 ||
        value.check != ~value.count)
        return -1;
    *count = value.count;
    return 0;
}

int main() {
    setvbuf(stdout, nullptr, _IONBF, 0);
    printf("save-counter: begin\n");

    OrbisUserServiceInitializeParams parameters{ORBIS_KERNEL_PRIO_FIFO_LOWEST};
    int code = sceUserServiceInitialize(&parameters);
    if (code != 0) return fail("user init", code);
    int user = -1;
    if ((code = sceUserServiceGetInitialUser(&user)) != 0) return fail("initial user", code);
    if ((code = sceSaveDataInitialize3(0)) != 0) return fail("save init", code);

    // Only a save carried over from an earlier launch can mount read-only.
    uint32_t previous = 0;
    OrbisSaveDataMountResult mounted;
    code = mount(user, ORBIS_SAVE_DATA_MOUNT_MODE_RDONLY, &mounted);
    bool existing = code == 0;
    if (existing) {
        if ((code = read_counter(mounted, &previous)) != 0) return fail("read previous", code);
        if ((code = unmount(mounted)) != 0) return fail("unmount previous", code);
        if (previous == 0 || previous >= 1000000u) return fail("previous range", static_cast<int>(previous));
    } else if (code != save_not_found) {
        return fail("mount existing", code);
    }

    const uint32_t count = previous + 1;
    uint32_t mode = existing ? ORBIS_SAVE_DATA_MOUNT_MODE_RDWR
                             : ORBIS_SAVE_DATA_MOUNT_MODE_CREATE | ORBIS_SAVE_DATA_MOUNT_MODE_RDWR;
    if ((code = mount(user, mode, &mounted)) != 0) return fail(existing ? "write mount" : "create mount", code);
    char path[64];
    snprintf(path, sizeof(path), "%.16s/counter.bin", mounted.mountPathName);
    // The file is always 16 bytes, so overwriting in place leaves no stale tail.
    int fd = sceKernelOpen(path, write_create, 0600);
    if (fd < 0) return fail("open counter", fd);
    Counter value{};
    memcpy(value.magic, magic, sizeof(magic));
    value.count = count;
    value.check = ~count;
    if (sceKernelWrite(fd, &value, sizeof(value)) != sizeof(value) || sceKernelClose(fd) != 0)
        return fail("write/close", 0);
    if ((code = unmount(mounted)) != 0) return fail("unmount after write", code);

    // Remount read-only so the check cannot come from the open write mount.
    uint32_t stored = 0;
    if ((code = mount(user, ORBIS_SAVE_DATA_MOUNT_MODE_RDONLY, &mounted)) != 0) return fail("remount", code);
    if ((code = read_counter(mounted, &stored)) != 0 || stored != count) return fail("readback", code);
    if ((code = unmount(mounted)) != 0) return fail("unmount after read", code);

    printf("save-counter: PASS previous=%u count=%u\n", static_cast<unsigned>(previous), static_cast<unsigned>(count));
    for (;;) { sceKernelUsleep(100000); }
}
