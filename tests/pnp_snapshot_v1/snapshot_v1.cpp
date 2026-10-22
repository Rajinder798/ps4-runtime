// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
#include "snapshot_v1.h"
#include <fstream>
#include <stdexcept>

namespace snapshot_v1 {
void BoundedSource::Check() {
    if (++calls > QueryCap || Ticks() > deadline)
        throw std::runtime_error("Snapshot query limit");
}
Enumeration BoundedSource::Devnodes() {
    return Query([&] { return source.Devnodes(); });
}
Enumeration BoundedSource::Interfaces(Bus b) {
    return Query([&] { return source.Interfaces(b); });
}
RawNode BoundedSource::Read(Id id) {
    return Query([&] { return source.Read(id); });
}
Root BoundedSource::TreeRoot() {
    return Query([&] { return source.TreeRoot(); });
}
Key BoundedSource::InstanceKey(Id id) {
    return Query([&] { return source.InstanceKey(id); });
}
namespace {
unsigned First(const std::filesystem::path &path) {
    std::ifstream f(path);
    std::string line;
    unsigned rows = 0;
    const std::string prefix = "\"event\":\"first_failure\",\"reason\":";
    while (rows++ < 20000 && std::getline(f, line)) {
        if (line.size() > 16384)
            throw std::runtime_error("Original evidence line limit");
        auto at = line.find(prefix);
        if (at != std::string::npos)
            return static_cast<unsigned>(std::stoul(line.substr(at + prefix.size())));
    }
    return 0;
}
} // namespace
int Run(Source &source, const std::filesystem::path &folder, bool host, unsigned fault,
        bool cleanup_fault) {
    if ((!host && (fault || cleanup_fault)) || !std::filesystem::is_directory(folder))
        throw std::runtime_error("Invalid snapshot configuration");
    const auto native = folder / "pnp-v2.jsonl", detail = folder / "rejection-v1.jsonl";
    // Both are exclusive append-only writers. Failure creating either occurs
    // before the first Source call; a partial header is retained, never removed.
    Trace trace(native, host);
    Writer writer(detail, host, ByteCap, RowCap, fault);
    BoundedSource bounded(source);
    Acquisition acquisition(bounded);
    Companion companion(acquisition, writer);
    Collector collector(companion, trace);
    const auto begin = Ticks();
    trace.Session(1000, begin);
    bool scan_returned = false;
    try {
        collector.Snapshot();
        scan_returned = true;
        companion.EndSnapshot(collector.Ready());
        if (!collector.Ready())
            trace.Fail(Failure::Coverage);
    } catch (const std::exception &) {
        trace.Fail(Failure::Resources);
    }
    // First failure is recorded before these cleanup records. A good explanatory
    // companion cannot change the original failure, including complete/no-HID.
    if (cleanup_fault)
        trace.Fail(Failure::Cleanup);
    trace.Stopped(begin, Ticks(), false);
    trace.Cleanup(cleanup_fault ? 1U : 0U);
    // Notification registration is intentionally absent. The unchanged v2
    // observer validator must never certify this as a complete observer session.
    trace.Finish(false, !cleanup_fault);
    writer.Finish(First(native), !cleanup_fault);
    if (!scan_returned || trace.Failed() || !collector.Ready())
        return 1;
    return writer.Good() ? 0 : 3;
}
} // namespace snapshot_v1
