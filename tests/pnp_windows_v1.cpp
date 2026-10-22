// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
#include "pnp_windows_v1.h"
#define NOMINMAX
#include <windows.h>
#include <setupapi.h>
#include <cfgmgr32.h>
#include <initguid.h>
#include <devpkey.h>

#include <algorithm>
#include <cstddef>
#include <stdexcept>

namespace pnp_v1 {
namespace {
constexpr GUID Usb = {0xa5dcbf10, 0x6530, 0x11d2, {0x90, 0x1f, 0x00, 0xc0, 0x4f, 0xb9, 0x51, 0xed}};
constexpr GUID Hid = {0x4d1e55b2, 0xf16f, 0x11cf, {0x88, 0xcb, 0x00, 0x11, 0x11, 0x00, 0x00, 0x30}};
const GUID &Guid(Bus b) {
    return b == Bus::Usb ? Usb : Hid;
}
struct InfoSet {
    HDEVINFO handle = INVALID_HANDLE_VALUE;
    ~InfoSet() {
        if (handle != INVALID_HANDLE_VALUE)
            SetupDiDestroyDeviceInfoList(handle);
    }
    std::uint32_t Close() {
        if (handle == INVALID_HANDLE_VALUE)
            return 0;
        auto h = handle;
        handle = INVALID_HANDLE_VALUE;
        return SetupDiDestroyDeviceInfoList(h) ? 0 : GetLastError();
    }
};
struct Property {
    std::array<wchar_t, PropertyBytes / sizeof(wchar_t)> data{};
    ULONG bytes = PropertyBytes;
    DEVPROPTYPE type = 0;
    CONFIGRET code = CR_SUCCESS;
    Property(DEVINST id, const DEVPROPKEY &key) {
        code = CM_Get_DevNode_PropertyW(id, &key, &type, reinterpret_cast<PBYTE>(data.data()),
                                        &bytes, 0);
        // No resizing/retry: changes and oversized properties are explicit gaps.
    }
    bool String(std::wstring &out) const {
        if (code || type != DEVPROP_TYPE_STRING || bytes < sizeof(wchar_t) ||
            bytes > PropertyBytes || bytes % sizeof(wchar_t))
            return false;
        const auto n = bytes / sizeof(wchar_t);
        if (!n || data[n - 1] != 0 ||
            std::find(data.begin(), data.begin() + n - 1, L'\0') != data.begin() + n - 1)
            return false;
        out.assign(data.data(), n - 1);
        return true;
    }
    bool List(std::vector<std::wstring> &out) const {
        return !code && bytes <= PropertyBytes && bytes % sizeof(wchar_t) == 0 &&
               type == DEVPROP_TYPE_STRING_LIST &&
               DecodeMultiSz(data.data(), bytes / sizeof(wchar_t), out);
    }
};
Interface Detail(HDEVINFO set, SP_DEVICE_INTERFACE_DATA &item) {
    Interface out;
    out.flags = item.Flags;
    SP_DEVINFO_DATA node{};
    node.cbSize = sizeof(node);
    DWORD needed = 0;
    const auto okay = SetupDiGetDeviceInterfaceDetailW(set, &item, nullptr, 0, &needed, &node);
    out.detail_code = okay ? ERROR_SUCCESS : GetLastError();
    // Documented metadata-only form: ERROR_INSUFFICIENT_BUFFER fills SP_DEVINFO_DATA.
    // No symbolic path buffer is requested, parsed or opened.
    out.code = out.detail_code == ERROR_INSUFFICIENT_BUFFER && node.DevInst
                   ? 0
                   : (out.detail_code ? out.detail_code : ERROR_INVALID_DATA);
    out.node = node.DevInst;
    return out;
}
DWORD CALLBACK Callback(HCMNOTIFICATION, void *context, CM_NOTIFY_ACTION action,
                        CM_NOTIFY_EVENT_DATA *data, DWORD bytes) noexcept {
    auto &q = *static_cast<Queue *>(context);
    Tick received = 0;
    try {
        received = Ticks();
    } catch (...) {
    }
    constexpr auto offset = offsetof(CM_NOTIFY_EVENT_DATA, u.DeviceInterface.SymbolicLink);
    const unsigned act = action == CM_NOTIFY_ACTION_DEVICEINTERFACEARRIVAL   ? 0U
                         : action == CM_NOTIFY_ACTION_DEVICEINTERFACEREMOVAL ? 1U
                                                                             : 2U;
    Bus bus = Bus::Unknown;
    const wchar_t *path = nullptr;
    std::size_t available = 0;
    const bool valid = data && bytes >= offset + sizeof(wchar_t) &&
                       bytes <= offset + PathCap * sizeof(wchar_t) &&
                       (bytes - offset) % sizeof(wchar_t) == 0 &&
                       data->FilterType == CM_NOTIFY_FILTER_TYPE_DEVICEINTERFACE;
    if (valid) {
        bus = IsEqualGUID(data->u.DeviceInterface.ClassGuid, Usb)   ? Bus::Usb
              : IsEqualGUID(data->u.DeviceInterface.ClassGuid, Hid) ? Bus::Hid
                                                                    : Bus::Unknown;
        path = data->u.DeviceInterface.SymbolicLink;
        available = (bytes - offset) / sizeof(wchar_t);
    }
    q.Receive(bus, act, path, available, received, valid && received > 0);
    return ERROR_SUCCESS; // Never veto, query properties, write files or open I/O handles here.
}
} // namespace
struct WindowsProvider::Impl {
    std::map<Id, Node> cache;
};
WindowsProvider::WindowsProvider() : state(std::make_unique<Impl>()) {}
WindowsProvider::~WindowsProvider() = default;
Enumeration WindowsProvider::Devnodes() {
    state->cache.clear();
    Enumeration out;
    InfoSet set;
    set.handle = SetupDiGetClassDevsW(nullptr, nullptr, nullptr, DIGCF_ALLCLASSES | DIGCF_PRESENT);
    if (set.handle == INVALID_HANDLE_VALUE) {
        out.code = GetLastError();
        out.terminal_code = NotQueried;
        out.complete = false;
        return out;
    }
    for (DWORD index = 0;; ++index) {
        SP_DEVINFO_DATA node{};
        node.cbSize = sizeof(node);
        if (!SetupDiEnumDeviceInfo(set.handle, index, &node)) {
            const auto code = GetLastError();
            out.terminal_code = code;
            if (code != ERROR_NO_MORE_ITEMS) {
                out.code = code;
                out.complete = false;
            }
            break;
        }
        if (index == NodeCap) {
            out.complete = false;
            out.limit_hit = true;
            out.terminal_code = 0;
            break;
        }
        out.nodes.push_back(node.DevInst);
    }
    out.cleanup_code = set.Close();
    return out;
}
Enumeration WindowsProvider::Interfaces(Bus bus) {
    Enumeration out;
    InfoSet set;
    // Includes inactive installed interfaces. Active is separately SPINT_ACTIVE;
    // devnode presence comes only from the independent ALLCLASSES|PRESENT set.
    set.handle = SetupDiGetClassDevsW(&Guid(bus), nullptr, nullptr, DIGCF_DEVICEINTERFACE);
    if (set.handle == INVALID_HANDLE_VALUE) {
        out.code = GetLastError();
        out.terminal_code = NotQueried;
        out.complete = false;
        return out;
    }
    for (DWORD index = 0;; ++index) {
        SP_DEVICE_INTERFACE_DATA item{};
        item.cbSize = sizeof(item);
        if (!SetupDiEnumDeviceInterfaces(set.handle, nullptr, &Guid(bus), index, &item)) {
            const auto code = GetLastError();
            out.terminal_code = code;
            if (code != ERROR_NO_MORE_ITEMS) {
                out.code = code;
                out.complete = false;
            }
            break;
        }
        if (index == InterfaceCap) {
            out.complete = false;
            out.limit_hit = true;
            out.terminal_code = 0;
            break;
        }
        out.interfaces.push_back(Detail(set.handle, item));
    }
    out.cleanup_code = set.Close();
    return out;
}
Lookup WindowsProvider::InterfaceNode(std::wstring_view opaque, Bus bus) {
    state->cache.clear();
    Lookup out;
    InfoSet set;
    set.handle = SetupDiCreateDeviceInfoList(nullptr, nullptr);
    if (set.handle == INVALID_HANDLE_VALUE) {
        out.code = GetLastError();
        return out;
    }
    SP_DEVICE_INTERFACE_DATA item{};
    item.cbSize = sizeof(item);
    const std::wstring path(opaque);
    // This opens an element in an in-memory information set, not a device handle.
    if (!SetupDiOpenDeviceInterfaceW(set.handle, path.c_str(), 0, &item))
        out.code = GetLastError();
    else {
        if (!IsEqualGUID(item.InterfaceClassGuid, Guid(bus))) {
            out.iface.code = ERROR_INVALID_DATA;
            out.iface.detail_code = NotQueried;
        } else
            out.iface = Detail(set.handle, item);
        // Deletes only the information-set element. It does not disable/remove hardware.
        if (!SetupDiDeleteDeviceInterfaceData(set.handle, &item))
            out.cleanup_code = GetLastError();
    }
    const auto code = set.Close();
    if (!out.cleanup_code)
        out.cleanup_code = code;
    return out;
}
Node WindowsProvider::Properties(Id id) {
    if (auto found = state->cache.find(id); found != state->cache.end())
        return found->second;
    Node out;
    out.id = id;
    if (state->cache.size() == NodeCap + 2 * InterfaceCap + ParentCap) {
        out.resource_limited = true;
        return out;
    }
    Property enumerator(id, DEVPKEY_Device_EnumeratorName);
    std::wstring name;
    out.enum_code = enumerator.code;
    out.enumerator_valid = enumerator.String(name) && !name.empty();
    if (out.enumerator_valid) {
        for (auto &c : name)
            if (c >= L'a' && c <= L'z')
                c -= 32;
        out.bus = name == L"USB" ? Bus::Usb : name == L"HID" ? Bus::Hid : Bus::Other;
    }
    if (out.bus == Bus::Usb || out.bus == Bus::Hid) {
        std::vector<std::wstring> ids;
        Property hardware(id, DEVPKEY_Device_HardwareIds);
        out.hw_code = hardware.code;
        out.hardware_valid = hardware.List(ids);
        out.hardware = hardware.code ? Hardware::Missing : HardwareIds(ids, out.hardware_valid);
        Property compatible(id, DEVPKEY_Device_CompatibleIds);
        out.compatible_code = compatible.code;
        if (!compatible.code) {
            out.compatible_valid = compatible.List(ids);
            if (out.compatible_valid)
                for (auto s : ids) {
                    for (auto &c : s)
                        if (c >= L'a' && c <= L'z')
                            c -= 32;
                    if (s == L"USB\\COMPOSITE")
                        out.composite = true;
                }
        }
        DEVINST parent = 0;
        out.parent_code = CM_Get_Parent(&parent, id, 0);
        out.parent = parent;
        ULONG status = 0, problem = 0;
        out.status_code = CM_Get_DevNode_Status(&status, &problem, id, 0);
        out.status = status;
        out.problem = problem;
    }
    state->cache.emplace(id, out);
    return out;
}
Key WindowsProvider::InstanceKey(Id id) {
    Property instance(id, DEVPKEY_Device_InstanceId);
    Key out;
    out.code = instance.code;
    if (!out.code && !instance.String(out.value))
        out.value.clear(); // Parse failure leaves the original API code intact.
    return out;
}
struct WindowsNotifications::Impl {
    std::shared_ptr<Queue> queue;
    Trace &trace;
    std::array<HCMNOTIFICATION, 2> handles{};
    bool started = false, closed = false, okay = false;
    Impl(std::shared_ptr<Queue> q, Trace &t) : queue(std::move(q)), trace(t) {}
};
WindowsNotifications::WindowsNotifications(std::shared_ptr<Queue> q, Trace &t)
    : state(std::make_unique<Impl>(std::move(q), t)) {}
WindowsNotifications::~WindowsNotifications() {
    if (!Close())
        static_cast<void>(state.release());
} // Failed unregister retains callback context.
void WindowsNotifications::Start() {
    if (state->started || state->closed)
        throw std::runtime_error("Repeated PnP lifecycle");
    state->started = true;
    for (unsigned i = 0; i < 2; ++i) {
        auto bus = i ? Bus::Hid : Bus::Usb;
        CM_NOTIFY_FILTER filter{};
        filter.cbSize = sizeof(filter);
        filter.FilterType = CM_NOTIFY_FILTER_TYPE_DEVICEINTERFACE;
        filter.u.DeviceInterface.ClassGuid = Guid(bus);
        const auto code =
            CM_Register_Notification(&filter, state->queue.get(), Callback, &state->handles[i]);
        state->trace.Registration(bus, code);
        if (code)
            throw std::runtime_error("PnP registration failed");
    }
}
bool WindowsNotifications::Close() {
    if (state->closed)
        return state->okay;
    state->closed = true;
    state->okay = true;
    for (unsigned i = 0; i < 2; ++i)
        if (auto &h = state->handles[i]; h) {
            const auto code = CM_Unregister_Notification(h);
            if (!code)
                h = nullptr;
            else
                state->okay = false;
            try {
                state->trace.Registration(i ? Bus::Hid : Bus::Usb, code, true);
            } catch (...) {
                state->okay = false;
            }
        }
    return state->okay;
}
void WindowsCallbackHostTests() {
    auto q = std::make_unique<Queue>();
    const std::wstring opaque = L"opaque HOST_TEST sentinel without any VID or PID";
    std::vector<std::uint64_t> buffer(
        (sizeof(CM_NOTIFY_EVENT_DATA) + (opaque.size() + 1) * sizeof(wchar_t) + 7) / 8);
    auto *data = reinterpret_cast<CM_NOTIFY_EVENT_DATA *>(buffer.data());
    data->FilterType = CM_NOTIFY_FILTER_TYPE_DEVICEINTERFACE;
    data->u.DeviceInterface.ClassGuid = Hid;
    std::copy_n(opaque.c_str(), opaque.size() + 1, data->u.DeviceInterface.SymbolicLink);
    const auto bytes =
        static_cast<DWORD>(offsetof(CM_NOTIFY_EVENT_DATA, u.DeviceInterface.SymbolicLink) +
                           (opaque.size() + 1) * sizeof(wchar_t));
    Callback(nullptr, q.get(), CM_NOTIFY_ACTION_DEVICEINTERFACEARRIVAL, data, bytes);
    auto batch = q->Drain();
    if (batch.size() != 1 || !batch[0].valid || batch[0].bus != Bus::Hid)
        throw std::runtime_error("Opaque callback was filtered");
    Callback(nullptr, q.get(), CM_NOTIFY_ACTION_DEVICEINTERFACEREMOVAL, data, bytes);
    if (q->Drain().at(0).action != 1)
        throw std::runtime_error("Removal missing");
    Callback(nullptr, q.get(), CM_NOTIFY_ACTION_DEVICEINTERFACEARRIVAL, data, 1);
    if (q->Drain().at(0).valid)
        throw std::runtime_error("Truncated callback accepted");
    data->u.DeviceInterface.SymbolicLink[opaque.size()] = L'x';
    Callback(nullptr, q.get(), CM_NOTIFY_ACTION_DEVICEINTERFACEARRIVAL, data, bytes);
    if (q->Drain().at(0).valid)
        throw std::runtime_error("Unterminated callback accepted");
    data->u.DeviceInterface.SymbolicLink[opaque.size()] = 0;
    data->u.DeviceInterface.ClassGuid = GUID{};
    Callback(nullptr, q.get(), CM_NOTIFY_ACTION_DEVICEINTERFACEARRIVAL, data, bytes);
    if (q->Drain().at(0).valid)
        throw std::runtime_error("Unknown class not accounted");
    data->u.DeviceInterface.ClassGuid = Hid;
    for (unsigned i = 0; i < QueueCap + 1; ++i)
        Callback(nullptr, q.get(), CM_NOTIFY_ACTION_DEVICEINTERFACEARRIVAL, data, bytes);
    if (q->Stats().dropped != 1 || q->Stats().malformed != 3)
        throw std::runtime_error("Callback exhaustion accounting failed");
}
} // namespace pnp_v1
