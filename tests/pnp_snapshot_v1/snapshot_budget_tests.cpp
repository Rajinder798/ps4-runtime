// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
// HOST TEST; no Windows adapter linked.
#include "snapshot_v1.h"
using namespace snapshot_v1;
struct Fake final : Source {
    unsigned calls = 0;
    Enumeration Devnodes() override { return {}; }
    Enumeration Interfaces(Bus) override { return {}; }
    RawNode Read(Id) override { return {}; }
    Root TreeRoot() override {
        ++calls;
        return {};
    }
    Key InstanceKey(Id) override { return {}; }
};
int main() {
    Fake fake;
    BoundedSource bounded(fake);
    bool rejected = false;
    try {
        for (unsigned i = 0; i <= QueryCap; ++i)
            bounded.TreeRoot();
    } catch (const std::runtime_error &) {
        rejected = true;
    }
    return rejected && fake.calls <= QueryCap ? 0 : 1;
}
