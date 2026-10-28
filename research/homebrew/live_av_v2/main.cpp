// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
// Independent continuous live AV v2. Legacy fixtures and policies are unchanged.
#include <stdint.h>
#include <stddef.h>

namespace LiveV2 {
constexpr uint32_t Cross = 0x4000;
enum State : uint8_t { Connected = 1, Disconnected = 2, ApiError = 3,
                       InvalidTimestamp = 4, StaleReconnect = 5 };
struct Raw {
    uint64_t timestamp{};
    uint32_t buttons{};
    uint8_t axes[4]{}, connected{}, count{}, triggers[2]{};
};
struct Effective {
    uint32_t buttons{};
    uint8_t axes[4]{128,128,128,128}, triggers[2]{};
    State state{Disconnected};
    bool payload_valid{};
    unsigned audio_command{};
    bool fatal() const { return state >= ApiError; }
};
class Policy {
    uint64_t last_connected_timestamp{};
    bool available{};
public:
    Effective read(int32_t rc, const Raw& raw) {
        Effective result{};
        result.payload_valid = rc == 0;
        if (rc != 0) { result.state = ApiError; available = false; return result; }
        if (!raw.connected) { available = false; return result; }
        if (raw.timestamp == 0) { result.state = InvalidTimestamp; return result; }
        if (raw.timestamp < last_connected_timestamp ||
            (!available && raw.timestamp <= last_connected_timestamp)) {
            result.state = StaleReconnect;
            return result;  // Explicit failure, never poll/reopen until this passes.
        }
        result.state = Connected;
        result.buttons = raw.buttons;
        for (unsigned i = 0; i < 4; ++i) result.axes[i] = raw.axes[i];
        for (unsigned i = 0; i < 2; ++i) result.triggers[i] = raw.triggers[i];
        result.audio_command = (raw.buttons & Cross) ? 1 : 0;
        last_connected_timestamp = raw.timestamp;
        available = true;
        return result;
    }
};
constexpr unsigned MaxJournalBytes = 4 * 1024 * 1024;
constexpr unsigned RecordLimit = (MaxJournalBytes - 16) / 72;
constexpr unsigned PostFlipSleepUs = 16000;
// Little-endian schema 2 (distinct magic), fixed 72-byte records. Error payload bytes are retained but explicitly invalid.
struct Observation {
    uint32_t sequence;
    int32_t handle, rc;
    uint32_t audio_command;
    uint64_t observed_us, timestamp, flip;
    uint32_t audio_blocks, raw_buttons, effective_buttons;
    uint8_t raw_axes[4], effective_axes[4];
    uint8_t connected, count, raw_triggers[2], effective_triggers[2];
    uint8_t payload_valid, state, reserved[4];
};
static_assert(sizeof(Observation) == 72 && offsetof(Observation, observed_us) == 16 &&
              offsetof(Observation, payload_valid) == 66, "LiveV2 schema 2 offsets");
} // namespace LiveV2

// Host tests compile the exact policy above, without SDK, SDL or guest execution.
#ifndef PS4_RUNTIME_LIVE_V2_POLICY_ONLY
#include <orbis/libkernel.h>
#include <orbis/VideoOut.h>
#include <orbis/Pad.h>
#include <orbis/AudioOut.h>
#include <orbis/UserService.h>
#include <stdio.h>

static uint8_t audio_challenge[4];
static unsigned audio_command = 0, audio_progress = 0, audio_failed = 0;
static int audio_port;
static constexpr unsigned audio_frames = 2048;
static int fail(const char* operation) {
    __atomic_store_n(&audio_command, 0, __ATOMIC_RELEASE);
    printf("live-av-v2: FAIL %s\n", operation);
    for (;;) sceKernelUsleep(100000);
}
static void* audio_worker(void*) {
    constexpr unsigned periods[4] = {64,96,128,192};
    unsigned blocks = 0;
    int16_t samples[audio_frames * 2];
    for (;;) {
        const unsigned command = __atomic_load_n(&audio_command, __ATOMIC_ACQUIRE);
        for (unsigned frame = 0; frame < audio_frames; ++frame)
            for (unsigned channel = 0; channel < 2; ++channel) {
                const unsigned period = periods[audio_challenge[channel]];
                samples[frame*2+channel] = !command ? 0 :
                    ((blocks*audio_frames+frame)%period < period/2 ? 2000 : -2000);
            }
        if (sceAudioOutOutput(audio_port,nullptr) < 0 || sceAudioOutOutput(audio_port,samples) < 0) {
            __atomic_store_n(&audio_failed,1,__ATOMIC_RELEASE);
            return reinterpret_cast<void*>(1);
        }
        __atomic_store_n(&audio_progress,++blocks,__ATOMIC_RELEASE);
    }
}
static void read_exact(const char* path, uint8_t* data, unsigned size) {
    uint8_t extra;
    const int fd = sceKernelOpen(path,0,0);
    if (fd < 0 || sceKernelRead(fd,data,size) != size || sceKernelRead(fd,&extra,1) != 0 ||
        sceKernelClose(fd) != 0) fail("challenge");
}
static uint32_t color(unsigned value) {
    return 0xff000000u | ((value&1)?0xffu:0) | ((value&2)?0xff00u:0) | ((value&4)?0xff0000u:0);
}
static void append(const LiveV2::Observation& o) {
    const int fd = sceKernelOpen("/data/live-av-v2.bin",1,0600);
    if (fd < 0 || sceKernelLseek(fd,0,2) != 16+o.sequence*sizeof(o) ||
        sceKernelWrite(fd,&o,sizeof(o)) != sizeof(o) || sceKernelClose(fd) != 0) fail("observations append");
    printf("live-av-v2: sample=%u handle=%d rc=%d command=%u observed=%llu timestamp=%llu flip=%llu "
           "audio_blocks=%u raw_buttons=%u effective_buttons=%u raw_axes=%u,%u,%u,%u "
           "effective_axes=%u,%u,%u,%u connected=%u count=%u raw_triggers=%u,%u "
           "effective_triggers=%u,%u valid=%u state=%u\n",
           o.sequence,o.handle,o.rc,o.audio_command,static_cast<unsigned long long>(o.observed_us),
           static_cast<unsigned long long>(o.timestamp),static_cast<unsigned long long>(o.flip),
           o.audio_blocks,o.raw_buttons,o.effective_buttons,o.raw_axes[0],o.raw_axes[1],o.raw_axes[2],o.raw_axes[3],
           o.effective_axes[0],o.effective_axes[1],o.effective_axes[2],o.effective_axes[3],o.connected,o.count,
           o.raw_triggers[0],o.raw_triggers[1],o.effective_triggers[0],o.effective_triggers[1],o.payload_valid,o.state);
}
int main() {
    static_assert(LiveV2::Cross == ORBIS_PAD_BUTTON_CROSS, "Reviewed Cross mask");
    static_assert(sizeof(OrbisPadData)==120 && offsetof(OrbisPadData,connected)==76 &&
                  offsetof(OrbisPadData,timestamp)==80 && offsetof(OrbisPadData,count)==104,
                  "Pinned SDK/engine fields used by this fixture");
    setvbuf(stdout,nullptr,_IONBF,0);
    printf("live-av-v2: begin schema=2\n");
    uint8_t palette[4];
    read_exact("/app0/palette.bin",palette,4);
    read_exact("/app0/audio.bin",audio_challenge,4);
    for (unsigned i=0;i<4;++i) {
        if (palette[i]>7 || audio_challenge[i]>3) return fail("challenge range");
        for (unsigned j=0;j<i;++j)
            if (palette[i]==palette[j] || audio_challenge[i]==audio_challenge[j]) return fail("challenge duplicate");
    }
    constexpr unsigned width=640,height=360;
    constexpr size_t allocation=0x400000,alignment=0x200000,stride=0x100000;
    off_t offset;
    void* memory=nullptr;
    if (sceKernelAllocateDirectMemory(0,sceKernelGetDirectMemorySize(),allocation,alignment,3,&offset)!=0 ||
        sceKernelMapDirectMemory(&memory,allocation,0x33,0,offset,alignment)!=0) return fail("memory");
    void* buffers[2]={memory,static_cast<uint8_t*>(memory)+stride};
    const int video=sceVideoOutOpen(ORBIS_VIDEO_USER_MAIN,ORBIS_VIDEO_OUT_BUS_MAIN,0,nullptr);
    if (video<0) return fail("video open");
    OrbisVideoOutBufferAttribute attribute{};
    sceVideoOutSetBufferAttribute(&attribute,ORBIS_VIDEO_OUT_PIXEL_FORMAT_A8B8G8R8_SRGB,
                                 ORBIS_VIDEO_OUT_TILING_MODE_LINEAR,0,width,height,width);
    if (sceVideoOutRegisterBuffers(video,0,buffers,2,&attribute)<0) return fail("video register");
    if (scePadInit()!=0) return fail("pad init");
    OrbisUserServiceInitializeParams parameters{ORBIS_KERNEL_PRIO_FIFO_LOWEST};
    if (sceUserServiceInitialize(&parameters)!=0) return fail("user init");
    int user=-1;
    if (sceUserServiceGetInitialUser(&user)!=0) return fail("initial user");
    const int pad=scePadOpen(user,ORBIS_PAD_PORT_TYPE_STANDARD,0,nullptr);  // Exactly one open.
    if (pad<0 || sceAudioOutInit()!=0) return fail("pad/audio init");
    audio_port=sceAudioOutOpen(ORBIS_USER_SERVICE_USER_ID_SYSTEM,ORBIS_AUDIO_OUT_PORT_TYPE_MAIN,
                             0,audio_frames,48000,ORBIS_AUDIO_OUT_PARAM_FORMAT_S16_STEREO);
    if (audio_port<=0) return fail("audio open");
    OrbisPthread thread;
    if (scePthreadCreate(&thread,nullptr,audio_worker,nullptr,"live-v2-audio")!=0) return fail("audio create");
    struct Header { char magic[8]; uint32_t version,size; };
    const Header header{{'L','A','V','2',0,0,0,0},2,sizeof(LiveV2::Observation)};
    const int fd=sceKernelOpen("/data/live-av-v2.bin",1|0x200|0x800,0600);
    if (fd<0 || sceKernelWrite(fd,&header,sizeof(header))!=sizeof(header) || sceKernelClose(fd)!=0)
        return fail("observations create");
    printf("live-av-v2: ready schema=2\n");
    LiveV2::Policy policy;
    for (unsigned sequence=0;sequence<LiveV2::RecordLimit;++sequence) {
        OrbisPadData data{};
        const int rc=scePadReadState(pad,&data);  // Save the actual result; never retry/reopen.
        LiveV2::Raw raw{data.timestamp,data.buttons,
            {data.leftStick.x,data.leftStick.y,data.rightStick.x,data.rightStick.y},
            data.connected,data.count,{data.analogButtons.l2,data.analogButtons.r2}};
        const auto effective=policy.read(rc,raw);
        __atomic_store_n(&audio_command,effective.audio_command,__ATOMIC_RELEASE);
        LiveV2::Observation o{};
        o.sequence=sequence;o.handle=pad;o.rc=rc;o.audio_command=effective.audio_command;
        o.observed_us=sceKernelGetProcessTime();o.timestamp=raw.timestamp;
        o.audio_blocks=__atomic_load_n(&audio_progress,__ATOMIC_ACQUIRE);
        o.raw_buttons=raw.buttons;o.effective_buttons=effective.buttons;
        for (unsigned i=0;i<4;++i) { o.raw_axes[i]=raw.axes[i];o.effective_axes[i]=effective.axes[i]; }
        for (unsigned i=0;i<2;++i) { o.raw_triggers[i]=raw.triggers[i];o.effective_triggers[i]=effective.triggers[i]; }
        o.connected=raw.connected;o.count=raw.count;o.payload_valid=effective.payload_valid;o.state=effective.state;
        if (effective.fatal()) { append(o);return fail("pad API/timestamp; exact result recorded"); }
        o.flip=sequence+1;
        auto* pixels=static_cast<uint32_t*>(buffers[sequence%2]);
        for (unsigned y=0;y<height;++y)
            for (unsigned x=0;x<width;++x)
                pixels[y*width+x]=y<24 ? (o.state==LiveV2::Disconnected?0xff0000ffu:0xff00ff00u) :
                    color(palette[(x/80+y/45+o.audio_command)%4]);
        const auto* bytes=reinterpret_cast<const uint8_t*>(&o);
        for (unsigned bit=0;bit<sizeof(o)*8;++bit)
            pixels[bit]=(bytes[bit/8]&(1u<<(bit%8)))?0xffffffffu:0xff000000u;
        if (sceVideoOutSubmitFlip(video,sequence%2,ORBIS_VIDEO_OUT_FLIP_VSYNC,o.flip)!=0) return fail("flip submit");
        bool completed=false;
        for (unsigned poll=0;poll<2000;++poll) {
            OrbisVideoOutFlipStatus status{};
            if (sceVideoOutGetFlipStatus(video,&status)!=0) return fail("flip status");
            if (status.flipArg==static_cast<int64_t>(o.flip) && status.currentBuffer==static_cast<int>(sequence%2) && status.num>0) {
                completed=true;break;
            }
            sceKernelUsleep(1000);
        }
        if (!completed) return fail("flip timeout");
        append(o);
        if (__atomic_load_n(&audio_failed,__ATOMIC_ACQUIRE)) return fail("audio worker");
        sceKernelUsleep(LiveV2::PostFlipSleepUs);
    }
    return fail("journal storage exhausted");
}
#endif
