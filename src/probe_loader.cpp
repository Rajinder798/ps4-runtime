#include "ps4/probe_loader.h"

#include <algorithm>
#include <array>
#include <cstring>
#include <limits>
#include <sstream>

#ifdef _WIN32
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#elif defined(__linux__)
#include <sys/mman.h>
#include <unistd.h>
#else
#error The mapping experiment currently supports Windows and Linux only.
#endif

namespace ps4 {
namespace {
constexpr std::uint64_t max_image_size = 64 * 1024 * 1024;
constexpr std::array<unsigned char, 6> probe_code{0xb8, 0x2a, 0, 0, 0, 0xc3};
constexpr std::array<unsigned char, 8> probe_data{'P', 'S', '4', 'P', 'R', 'O', 'B', 'E'};

[[noreturn]] void fail(const char* code, const char* message) {
    throw InspectionError(code, message);
}

std::size_t host_page_size() {
#ifdef _WIN32
    SYSTEM_INFO info{};
    GetSystemInfo(&info);
    return info.dwPageSize;
#else
    const auto size = sysconf(_SC_PAGESIZE);
    if (size <= 0) fail("page_size_failed", "Could not determine host page size.");
    return static_cast<std::size_t>(size);
#endif
}

struct Range { std::uint64_t begin, end; const Segment* segment; };

std::uint64_t page_end(std::uint64_t end, std::size_t page) {
    const auto remainder = end % page;
    if (remainder == 0) return end;
    const auto padding = page - remainder;
    if (end > std::numeric_limits<std::uint64_t>::max() - padding)
        fail("mapping_address_overflow", "Page rounding would overflow the address range.");
    return end + padding;
}
} // namespace

struct MappedImage::Impl {
    Inspection info{};
    unsigned char* region = nullptr;
    std::uint64_t guest_base = 0;
    std::size_t size = 0;
    std::size_t page = 0;

    ~Impl() {
        if (!region) return;
#ifdef _WIN32
        VirtualFree(region, 0, MEM_RELEASE);
#else
        munmap(region, size);
#endif
    }

    void reserve() {
#ifdef _WIN32
        region = static_cast<unsigned char*>(VirtualAlloc(nullptr, size, MEM_RESERVE, PAGE_NOACCESS));
#else
        auto* allocation = mmap(nullptr, size, PROT_NONE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
        if (allocation != MAP_FAILED) region = static_cast<unsigned char*>(allocation);
#endif
        if (!region) fail("reserve_failed", "Could not reserve the image address range.");
    }

    void writable(unsigned char* address, std::size_t length) {
#ifdef _WIN32
        if (!VirtualAlloc(address, length, MEM_COMMIT, PAGE_READWRITE))
#else
        if (mprotect(address, length, PROT_READ | PROT_WRITE) != 0)
#endif
            fail("commit_failed", "Could not make segment pages writable for copying.");
    }

    void protect(unsigned char* address, std::size_t length, std::uint32_t flags) {
#ifdef _WIN32
        DWORD old = 0;
        const DWORD mode = (flags & 1) ? PAGE_EXECUTE_READ : (flags & 2) ? PAGE_READWRITE : PAGE_READONLY;
        if (!VirtualProtect(address, length, mode, &old))
#else
        const int mode = PROT_READ | ((flags & 1) ? PROT_EXEC : 0) | ((flags & 2) ? PROT_WRITE : 0);
        if (mprotect(address, length, mode) != 0)
#endif
            fail("protect_failed", "Could not apply final segment permissions.");
        if ((flags & 1) != 0) {
#ifdef _WIN32
            if (!FlushInstructionCache(GetCurrentProcess(), address, length))
                fail("cache_flush_failed", "Could not flush the instruction cache.");
#else
            __builtin___clear_cache(reinterpret_cast<char*>(address), reinterpret_cast<char*>(address + length));
#endif
        }
    }
};

MappedImage::MappedImage(std::istream& input) : impl_(std::make_unique<Impl>()) {
#if !defined(_M_X64) && !defined(__x86_64__)
    fail("unsupported_mapping_host", "The probe mapper requires an x86-64 host.");
#endif
    auto& state = *impl_;
    state.info = inspect_elf(input);
    if (state.info.type != 3 && state.info.type != 0xfe10)
        fail("unsupported_mapping_type", "Only ET_DYN and ET_SCE_DYNEXEC are supported by the rebased mapper.");
    if (state.info.segments.size() > 128)
        fail("too_many_segments", "The experimental mapper supports at most 128 program headers.");
    state.page = host_page_size();
    std::vector<Range> ranges;
    for (const auto& segment : state.info.segments) {
        if (segment.type == 0) continue;
        if (segment.type != 1)
            fail("unsupported_mapping_segment", "Only PT_LOAD and PT_NULL are supported; dynamic linking and TLS are not implemented.");
        if (segment.memory_size == 0)
            fail("empty_load_segment", "Zero-sized load segments are not supported by the mapper.");
        if ((segment.flags & 3) == 3)
            fail("writable_executable_segment", "Writable executable segments are not supported.");
        if (segment.flags != 4 && segment.flags != 5 && segment.flags != 6)
            fail("unsupported_segment_permissions", "The mapper requires R, RX or RW segment permissions.");
        if (segment.alignment > state.page)
            fail("unsupported_mapping_alignment", "Segment alignment exceeds the host page size.");
        ranges.push_back({segment.address - segment.address % state.page,
                          page_end(segment.address + segment.memory_size, state.page), &segment});
    }
    // inspect_elf guarantees a PT_LOAD, and zero-sized ones were rejected above.
    std::sort(ranges.begin(), ranges.end(), [](const Range& a, const Range& b) { return a.begin < b.begin; });
    for (std::size_t i = 1; i < ranges.size(); ++i)
        if (ranges[i].begin < ranges[i - 1].end)
            fail("overlapping_segment_pages", "Load segments overlap or share a host page.");
    state.guest_base = ranges.front().begin;
    const auto span = ranges.back().end - state.guest_base;
    if (span > max_image_size)
        fail("image_too_large", "The experimental mapper limits the image span to 64 MiB.");
    state.size = static_cast<std::size_t>(span);
    state.reserve();
    for (const auto& range : ranges) {
        const auto& segment = *range.segment;
        auto* page = state.region + static_cast<std::size_t>(range.begin - state.guest_base);
        const auto length = static_cast<std::size_t>(range.end - range.begin);
        state.writable(page, length);
        auto* target = state.region + static_cast<std::size_t>(segment.address - state.guest_base);
        input.seekg(static_cast<std::streamoff>(segment.offset), std::ios::beg);
        if (segment.file_size != 0 &&
            !input.read(reinterpret_cast<char*>(target), static_cast<std::streamsize>(segment.file_size)))
            fail("segment_read_failed", "Could not copy segment bytes from the input file.");
        // Fresh anonymous/committed pages are zeroed by the host. Explicitly
        // initialize the ELF zero-fill tail so that the loader contract is clear.
        std::memset(target + segment.file_size, 0, static_cast<std::size_t>(segment.memory_size - segment.file_size));
        state.protect(page, length, segment.flags);
    }
}

MappedImage::~MappedImage() = default;
const Inspection& MappedImage::inspection() const noexcept { return impl_->info; }
std::size_t MappedImage::page_size() const noexcept { return impl_->page; }
std::size_t MappedImage::mapped_size() const noexcept { return impl_->size; }

std::span<const unsigned char> MappedImage::bytes(std::uint64_t address, std::size_t size) const {
    for (const auto& segment : impl_->info.segments) {
        if (segment.type == 1 && address >= segment.address && address - segment.address <= segment.memory_size &&
            size <= segment.memory_size - (address - segment.address))
            return {impl_->region + static_cast<std::size_t>(address - impl_->guest_base), size};
    }
    fail("unmapped_range", "Requested range is outside a single mapped segment.");
}

int MappedImage::call_probe() const {
    const auto& info = impl_->info;
    if (info.type != 0xfe10 || info.os_abi != 9 || info.abi_version != 0 || info.file_size != 8200 ||
        info.entry != 0x1000 || info.segments.size() != 2)
        fail("unsupported_probe", "Execution is restricted to the generated synthetic probe.");
    const auto& code = info.segments[0];
    const auto& data = info.segments[1];
    if (code.type != 1 || code.flags != 5 || code.offset != 0x1000 || code.address != 0x1000 ||
        code.file_size != 6 || code.memory_size != 6 || code.alignment != 0x1000 ||
        data.type != 1 || data.flags != 6 || data.offset != 0x2000 || data.address != 0x4000 ||
        data.file_size != 8 || data.memory_size != 0x1000 || data.alignment != 0x1000)
        fail("unsupported_probe", "Probe segment metadata does not match the generated fixture.");
    const auto instructions = bytes(code.address, probe_code.size());
    const auto marker = bytes(data.address, probe_data.size());
    if (!std::equal(instructions.begin(), instructions.end(), probe_code.begin()) ||
        !std::equal(marker.begin(), marker.end(), probe_data.begin()))
        fail("unsupported_probe", "Probe code or data bytes do not match the generated fixture.");
    const auto zero_fill = bytes(data.address + data.file_size, static_cast<std::size_t>(data.memory_size - data.file_size));
    if (!std::all_of(zero_fill.begin(), zero_fill.end(), [](unsigned char byte) { return byte == 0; }))
        fail("probe_zero_fill_failed", "Probe zero-fill verification failed.");
    // The known stub changes only EAX and returns. No arguments, services, TLS,
    // process startup or general Windows-to-System-V ABI bridge are exercised.
    using ProbeFunction = int (*)();
    return reinterpret_cast<ProbeFunction>(const_cast<unsigned char*>(instructions.data()))();
}

std::string probe_json(const MappedImage& image, int value) {
    std::ostringstream out;
    out << "{\"schema_version\":1,\"operation\":\"probe\",\"return_value\":" << value
        << ",\"mapped_segments\":2,\"mapped_bytes\":" << image.mapped_size()
        << ",\"page_size\":" << image.page_size()
        << ",\"copied_bytes_verified\":14,\"zero_fill_bytes_verified\":4088,\"protections_applied\":true"
           ",\"general_execution_supported\":false}\n";
    return out.str();
}

std::string probe_text(const MappedImage& image, int value) {
    std::ostringstream out;
    out << "Synthetic probe returned: " << value
        << "\nMapped 2 segments across " << image.mapped_size() << " bytes; host page size: " << image.page_size()
        << "\nVerified 14 copied bytes and 4088 zero-fill bytes.\nFinal permissions: RX code, RW data; gaps inaccessible.\n"
           "Controlled return stub only; general PS4 process execution is not implemented.\n";
    return out.str();
}
} // namespace ps4
