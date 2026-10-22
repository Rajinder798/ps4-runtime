// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
#include "rejection_windows_v1.h"
#define NOMINMAX
#include <windows.h>
#include <cfgmgr32.h>
#include <devpkey.h>
#include <algorithm>

namespace rejection_v1 {
namespace {
Property ReadProperty(Id id, const DEVPROPKEY &key) {
    Property p;
    p.data.resize(PropertyBytes / sizeof(wchar_t));
    ULONG bytes = PropertyBytes;
    DEVPROPTYPE type = 0;
    p.code = CM_Get_DevNode_PropertyW(id, &key, &type, reinterpret_cast<PBYTE>(p.data.data()),
                                      &bytes, 0);
    p.type = type;
    p.bytes = bytes;
    return p; // Caller never serializes this transient buffer.
}
} // namespace
Enumeration WindowsSource::Devnodes() { return enumeration.Devnodes(); }
Enumeration WindowsSource::Interfaces(Bus b) { return enumeration.Interfaces(b); }
RawNode WindowsSource::Read(Id id) {
    RawNode n;
    n.enumerator = ReadProperty(id, DEVPKEY_Device_EnumeratorName);
    const auto &e = n.enumerator;
    std::wstring category;
    if (!e.code && e.type == DEVPROP_TYPE_STRING && e.bytes >= 2 && e.bytes <= PropertyBytes &&
        e.bytes % 2 == 0 && e.data[e.bytes / 2 - 1] == 0 &&
        std::find(e.data.begin(), e.data.begin() + e.bytes / 2 - 1, L'\0') ==
            e.data.begin() + e.bytes / 2 - 1) {
        category.assign(e.data.data(), e.bytes / 2 - 1);
        for (auto &c : category)
            if (c >= L'a' && c <= L'z')
                c -= 32;
    }
    if (category == L"USB" || category == L"HID") {
        n.hardware = ReadProperty(id, DEVPKEY_Device_HardwareIds);
        n.compatible = ReadProperty(id, DEVPKEY_Device_CompatibleIds);
        ULONG status = 0, problem = 0;
        n.status_code = CM_Get_DevNode_Status(&status, &problem, id, 0);
        n.status = status;
        n.problem = problem;
    }
    DEVINST parent = 0;
    n.parent_code = CM_Get_Parent(&parent, id, 0);
    n.parent = parent;
    return n;
}
Root WindowsSource::TreeRoot() {
    Root r;
    DEVINST id = 0;
    r.code = CM_Locate_DevNodeW(&id, nullptr, CM_LOCATE_DEVNODE_NORMAL);
    r.id = id;
    return r;
}
Key WindowsSource::InstanceKey(Id id) { return enumeration.InstanceKey(id); }
} // namespace rejection_v1
