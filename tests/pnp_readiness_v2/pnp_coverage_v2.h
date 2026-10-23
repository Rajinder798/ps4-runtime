// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once
#include <array>
#include <atomic>
#include <cstdint>
#include <filesystem>
#include <map>
#include <mutex>
#include <string>
#include <string_view>
#include <vector>

// A separate diagnostic contract. No SDL, guest, Pad or acceptance dependencies.
namespace pnp_v2 {
using Tick = std::int64_t;
using Id = std::uint32_t; // Internal DEVINST only; never serialized.
constexpr std::uint32_t NotQueried = 0xffffffffU;
constexpr unsigned NodeCap = 2048, InterfaceCap = 2048, RelevantCap = 64, TokenCap = 128;
constexpr unsigned ParentCap = 8, QueueCap = 256, PathCap = 1024, PropertyBytes = 16384;
constexpr unsigned PeriodMs = 2000, ScanBudgetMs = 250, MaxDurationMs = 360000;
Tick Ticks();
Tick Frequency();
enum class Bus { Usb, Hid, Other, Unknown };
enum class Hardware { UsbParent, UsbFunction, Hid, Other, Missing, Malformed };
// Closed public reasons; no device strings are retained in diagnostic output.
enum class Reason {
    None,
    PropertyApiFailure,
    UnexpectedPropertyType,
    InvalidPropertyLength,
    InvalidMultiSzTermination,
    PropertyLimit,
    UnsupportedDocumentedForm,
    UnrecognizedForm,
    InvalidHardwareSyntax,
    MissingHardwareId,
    ConflictingIdentities,
    EnumeratorUnavailable,
    EnumeratorMalformed,
    IdentityBusConflict,
    ParentUnresolved,
    ParentCycle,
    ParentLimit,
    ResourceLimit,
    InterfaceLookupFailed
};
const char *Name(Reason);
struct Assessment {
    Hardware hardware = Hardware::Missing;
    Reason reason = Reason::MissingHardwareId;
};
Assessment AssessIds(const std::vector<std::wstring> &);
Assessment AssessProperty(std::uint32_t code, std::uint32_t type, std::uint32_t bytes,
                          const wchar_t *data, std::size_t capacity);
enum class Outcome { Intended, Unmatched, Indeterminate };
enum class Role { UsbParent, UsbFunction, HidChild, RelatedHid, Unresolved, None };
enum class Failure {
    Coverage = 1,
    Queue = 2,
    Resources = 3,
    Clock = 4,
    Storage = 5,
    Registration = 6,
    Cleanup = 7,
    Internal = 8,
    Overhead = 9
};
const char *Name(Bus);
const char *Name(Hardware);
const char *Name(Outcome);
const char *Name(Role);
Hardware HardwareIds(const std::vector<std::wstring> &ids, bool valid = true);
bool DecodeMultiSz(const wchar_t *data, std::size_t characters, std::vector<std::wstring> &out);

struct Node {
    Id id = 0, parent = 0;
    Bus bus = Bus::Unknown;
    Hardware hardware = Hardware::Missing;
    Reason hardware_reason = Reason::None;
    std::uint32_t hardware_type = 0, hardware_bytes = 0;
    std::uint32_t enum_code = NotQueried, hw_code = NotQueried, compatible_code = NotQueried;
    std::uint32_t parent_code = NotQueried, status_code = NotQueried, status = 0, problem = 0;
    bool composite = false;
    bool enumerator_valid = false, hardware_valid = false, compatible_valid = false;
    bool resource_limited = false;
};
struct Interface {
    Id node = 0;
    std::uint32_t flags = 0, code = 0, detail_code = NotQueried;
};
struct Enumeration {
    std::vector<Id> nodes;
    std::vector<Interface> interfaces;
    std::uint32_t code = 0, cleanup_code = 0;
    std::uint32_t terminal_code = 259; // ERROR_NO_MORE_ITEMS; original terminal enum result.
    bool limit_hit = false;
    bool complete = true;
};
struct Lookup {
    Interface iface;
    std::uint32_t code = 0, cleanup_code = 0;
};
struct Key {
    std::wstring value;
    std::uint32_t code = 0;
};
struct Provider {
    virtual ~Provider() = default;
    virtual Enumeration Devnodes() = 0;
    virtual Enumeration Interfaces(Bus) = 0;
    virtual Lookup InterfaceNode(std::wstring_view opaque, Bus) = 0;
    virtual Node Properties(Id) = 0;
    virtual Key InstanceKey(Id) = 0;
};
struct Resolution {
    Outcome outcome = Outcome::Indeterminate;
    Role role = Role::Unresolved;
    Node node{};
    Node root_node{};
    Id root = 0;
    bool ancestry_complete = false;
    unsigned depth = 0;
    std::uint32_t ancestry_code = NotQueried;
    bool resource_limited = false;
    Reason reason = Reason::ParentUnresolved;
    Reason ancestry_property_reason = Reason::None;
};
Resolution Resolve(Provider &, Id);

struct Notice {
    Tick received = 0;
    std::uint64_t ordinal = 0;
    Bus bus = Bus::Unknown;
    unsigned action = 2; // 0 arrival, 1 removal, 2 unsupported/malformed.
    bool valid = false;
    std::array<wchar_t, PathCap> opaque{}; // Only transient lookup input.
};
struct QueueStats {
    std::array<std::uint64_t, 9> counts{}; // USB/HID/unknown x arrival/removal/other
    std::uint64_t dropped = 0, malformed = 0;
};
class Queue {
    std::mutex mutex;
    std::array<Notice, QueueCap> pending{};
    std::size_t count = 0;
    std::atomic<std::uint64_t> ordinal{0}, dropped{0}, malformed{0};
    std::array<std::atomic<std::uint64_t>, 9> counts{};

  public:
    void Receive(Bus, unsigned action, const wchar_t *, std::size_t available, Tick received,
                 bool payload_valid = true) noexcept;
    std::vector<Notice> Drain();
    QueueStats Stats() const;
};

class Trace {
    void *file = nullptr;
    std::uint64_t bytes = 0, rows = 0, byte_cap, row_cap;
    Tick last = 0;
    bool failed = false, broken = false, finished = false;
    void Append(std::string_view, const std::string &, bool reserved = false);
    friend class Collector;

  public:
    Trace(const std::filesystem::path &, bool host_test = false,
          std::uint64_t max_bytes = 8 * 1024 * 1024, std::uint64_t max_rows = 20000);
    ~Trace();
    Trace(const Trace &) = delete;
    Trace &operator=(const Trace &) = delete;
    void Registration(Bus, std::uint32_t code, bool unregister = false);
    void Session(unsigned duration_ms, Tick begin);
    void Stopped(Tick begin, Tick end, bool requested);
    void Fail(Failure);
    void Cleanup(std::uint32_t code);
    void Finish(bool coverage_complete, bool cleanup_ok);
    bool Failed() const { return failed || broken; }
};
class Collector {
    Provider &provider;
    Trace &trace;
    std::map<std::wstring, unsigned> tokens; // Relevant instance keys only; no output.
    bool coverage = true;
    bool detail_complete = true;
    bool ready = false;
    std::uint64_t processed = 0;
    unsigned sample = 0;
    Tick last_received = 0;
    Tick last_snapshot = 0;
    unsigned Token(Id, std::uint32_t &);
    void Incomplete(Failure = Failure::Coverage);
    std::string Fields(const Resolution &, int present, int root_present);

  public:
    Collector(Provider &p, Trace &t) : provider(p), trace(t) {}
    void Notifications(Queue &);
    void Snapshot();
    void QueueSummary(const Queue &);
    bool Complete() const { return coverage && sample > 0; }
    bool Ready() const { return Complete() && ready; }
};
} // namespace pnp_v2
