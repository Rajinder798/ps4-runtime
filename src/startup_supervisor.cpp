// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
// See LICENSE in the project root for the full license text.

#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <tlhelp32.h>

#include <chrono>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
struct Handle {
    HANDLE value = nullptr;
    explicit Handle(HANDLE handle) : value(handle) {}
    ~Handle() { if (value && value != INVALID_HANDLE_VALUE) CloseHandle(value); }
    Handle(const Handle&) = delete;
    Handle& operator=(const Handle&) = delete;
};

void Check(BOOL result, const char* operation) {
    if (!result) throw std::runtime_error(std::string(operation) + ": Win32 " + std::to_string(GetLastError()));
}

std::wstring Quote(const std::wstring& argument) {
    std::wstring result = L"\"";
    size_t slashes = 0;
    for (wchar_t c : argument) {
        if (c == L'\\') { ++slashes; continue; }
        result.append(slashes * (c == L'"' ? 2 : 1), L'\\');
        slashes = 0;
        if (c == L'"') result += L'\\';
        result += c;
    }
    result.append(slashes * 2, L'\\');
    return result + L'"';
}

struct Attributes {
    std::vector<unsigned char> storage;
    LPPROC_THREAD_ATTRIBUTE_LIST list = nullptr;
    Attributes() {
        SIZE_T bytes = 0;
        InitializeProcThreadAttributeList(nullptr, 2, 0, &bytes);
        storage.resize(bytes);
        list = reinterpret_cast<LPPROC_THREAD_ATTRIBUTE_LIST>(storage.data());
        Check(InitializeProcThreadAttributeList(list, 2, 0, &bytes), "Initialize attributes");
    }
    ~Attributes() { DeleteProcThreadAttributeList(list); }
};

DWORD Active(HANDLE job) {
    JOBOBJECT_BASIC_ACCOUNTING_INFORMATION info{};
    Check(QueryInformationJobObject(job, JobObjectBasicAccountingInformation, &info, sizeof(info), nullptr), "Query job");
    return info.ActiveProcesses;
}

DWORD ParentPid() {
    Handle snapshot(CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0));
    Check(snapshot.value != INVALID_HANDLE_VALUE, "Snapshot parent");
    PROCESSENTRY32W entry{};
    entry.dwSize = sizeof(entry);
    Check(Process32FirstW(snapshot.value, &entry), "Read parent snapshot");
    do {
        if (entry.th32ProcessID == GetCurrentProcessId()) return entry.th32ParentProcessID;
    } while (Process32NextW(snapshot.value, &entry));
    throw std::runtime_error("Cannot identify supervisor parent");
}
} // namespace

// Internal helper: cwd stdout stderr stop-file report lifetime executable [args...].
// lifetime is timeout-ms, or until-exit:<inherited launcher process handle>.
int wmain(int argc, wchar_t* argv[]) {
    if (argc < 8) { std::cerr << "startup-supervisor: missing arguments\n"; return 2; }
    try {
        const std::wstring lifetime(argv[6]), prefix(L"until-exit:");
        const bool until_exit = lifetime.compare(0, prefix.size(), prefix) == 0;
        unsigned long timeout = 0;
        Handle owner(nullptr);
        size_t parsed = 0;
        if (until_exit) {
            const auto token = lifetime.substr(prefix.size());
            if (token.empty() || token.find_first_not_of(L"0123456789") != std::wstring::npos)
                throw std::runtime_error("until-exit requires an inherited owner handle");
            const auto raw = std::stoull(token, &parsed);
            if (parsed != token.size() || !raw || raw != static_cast<uintptr_t>(raw))
                throw std::runtime_error("Invalid owner handle");
            owner.value = reinterpret_cast<HANDLE>(static_cast<uintptr_t>(raw));
            if (owner.value == INVALID_HANDLE_VALUE || !GetProcessId(owner.value) ||
                GetProcessId(owner.value) != ParentPid() || WaitForSingleObject(owner.value, 0) != WAIT_TIMEOUT)
                throw std::runtime_error("Owner handle must identify the live supervisor parent");
            // Only stream handles are inherited by the engine, never this owner handle.
            Check(SetHandleInformation(owner.value, HANDLE_FLAG_INHERIT, 0), "Confine owner handle");
        } else {
            timeout = std::stoul(lifetime, &parsed);
            if (parsed != lifetime.size() || timeout < 100 || timeout > 120000)
                throw std::runtime_error("timeout must be 100..120000 milliseconds");
        }
        const std::filesystem::path cwd(argv[1]), stop(argv[4]), report(argv[5]);
        if (!cwd.is_absolute() || !report.is_absolute() || !stop.is_absolute() ||
            !std::filesystem::path(argv[7]).is_absolute() || std::filesystem::exists(report)) {
            throw std::runtime_error("absolute paths and a new report are required");
        }
        Handle job(CreateJobObjectW(nullptr, nullptr));
        Check(job.value != nullptr, "Create job");
        JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits{};
        limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        Check(SetInformationJobObject(job.value, JobObjectExtendedLimitInformation, &limits, sizeof(limits)), "Set job limits");
        SECURITY_ATTRIBUTES security{sizeof(SECURITY_ATTRIBUTES), nullptr, TRUE};
        Handle stdout_file(CreateFileW(argv[2], GENERIC_WRITE, FILE_SHARE_READ, &security, CREATE_NEW, FILE_ATTRIBUTE_NORMAL, nullptr));
        Handle stderr_file(CreateFileW(argv[3], GENERIC_WRITE, FILE_SHARE_READ, &security, CREATE_NEW, FILE_ATTRIBUTE_NORMAL, nullptr));
        Handle stdin_file(CreateFileW(L"NUL", GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE, &security, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr));
        Check(stdout_file.value != INVALID_HANDLE_VALUE && stderr_file.value != INVALID_HANDLE_VALUE && stdin_file.value != INVALID_HANDLE_VALUE, "Open child streams");
        Attributes attributes;
        HANDLE streams[]{stdin_file.value, stdout_file.value, stderr_file.value};
        Check(UpdateProcThreadAttribute(attributes.list, 0, PROC_THREAD_ATTRIBUTE_HANDLE_LIST, streams, sizeof(streams), nullptr, nullptr), "Set stream handles");
        // Windows 10+: bind the job at creation, avoiding an orphan window before assignment.
        HANDLE jobs[]{job.value};
        Check(UpdateProcThreadAttribute(attributes.list, 0, PROC_THREAD_ATTRIBUTE_JOB_LIST, jobs, sizeof(jobs), nullptr, nullptr), "Set process job");
        STARTUPINFOEXW startup{};
        startup.StartupInfo.cb = sizeof(startup);
        startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES;
        startup.StartupInfo.hStdInput = stdin_file.value;
        startup.StartupInfo.hStdOutput = stdout_file.value;
        startup.StartupInfo.hStdError = stderr_file.value;
        startup.lpAttributeList = attributes.list;
        std::wstring command_line;
        for (int i = 7; i < argc; ++i) {
            if (i != 7) command_line += L' ';
            command_line += Quote(argv[i]);
        }
        PROCESS_INFORMATION process{};
        Check(CreateProcessW(argv[7], command_line.data(), nullptr, nullptr, TRUE,
                             CREATE_SUSPENDED | CREATE_NO_WINDOW | EXTENDED_STARTUPINFO_PRESENT,
                             nullptr, cwd.c_str(), &startup.StartupInfo, &process), "Create child");
        Handle process_handle(process.hProcess), thread_handle(process.hThread);
        Check(ResumeThread(thread_handle.value) != static_cast<DWORD>(-1), "Resume child");
        const auto began = std::chrono::steady_clock::now();
        std::string reason;
        while (reason.empty()) {
            const DWORD wait = WaitForSingleObject(process_handle.value, 20);
            if (wait == WAIT_OBJECT_0) reason = "exited";
            else if (wait == WAIT_FAILED) Check(FALSE, "Wait child");
            else if (std::filesystem::exists(stop)) reason = "requested";
            else if (until_exit) {
                const DWORD owner_wait = WaitForSingleObject(owner.value, 0);
                if (owner_wait == WAIT_OBJECT_0) reason = "owner_exited";
                else if (owner_wait != WAIT_TIMEOUT) Check(FALSE, "Wait owner");
            } else if (std::chrono::steady_clock::now() - began >= std::chrono::milliseconds(timeout)) reason = "timeout";
        }
        // A root exit can leave descendants behind. Distinguish that fallback
        // from an independently empty job before claiming normal shutdown.
        // Windows can signal the root process before job accounting reaches
        // zero. Allow a bounded settle interval, without terminating anything.
        const auto settle_deadline = std::chrono::steady_clock::now() + std::chrono::milliseconds(250);
        while (reason == "exited" && Active(job.value) &&
               std::chrono::steady_clock::now() < settle_deadline) Sleep(10);
        const DWORD active_before_cleanup = Active(job.value);
        const bool forced_termination = active_before_cleanup != 0;
        if (forced_termination) Check(TerminateJobObject(job.value, 125), "Terminate job");
        const auto cleanup_deadline = std::chrono::steady_clock::now() + std::chrono::seconds(5);
        // Empty job accounting alone does not verify that our retained root
        // process object has signaled exit. Keep both checks in the same budget.
        DWORD root_wait = WaitForSingleObject(process_handle.value, 0);
        while ((Active(job.value) || root_wait == WAIT_TIMEOUT) &&
               std::chrono::steady_clock::now() < cleanup_deadline) {
            if (root_wait == WAIT_FAILED) Check(FALSE, "Verify root exit");
            Sleep(10);
            root_wait = WaitForSingleObject(process_handle.value, 0);
        }
        if (root_wait == WAIT_FAILED) Check(FALSE, "Verify root exit");
        const bool root_exited = root_wait == WAIT_OBJECT_0;
        const bool cleaned = Active(job.value) == 0 && root_exited;
        DWORD exit_code = STILL_ACTIVE;
        Check(GetExitCodeProcess(process_handle.value, &exit_code), "Read exit status");
        std::ofstream output(report, std::ios::binary);
        output << "{\"schema_version\":1,\"reason\":\"" << reason << "\",\"root_pid\":"
               << process.dwProcessId << ",\"exit_code\":" << exit_code
               << ",\"active_before_cleanup\":" << active_before_cleanup
               << ",\"forced_termination\":" << (forced_termination ? "true" : "false")
               << ",\"tree_cleanup\":" << (cleaned ? "true" : "false")
               << ",\"root_exit_verified\":" << (root_exited ? "true" : "false");
        if (until_exit) output << ",\"lifetime\":\"until_exit\",\"owner_watch_verified\":true";
        output << "}\n";
        output.close();
        if (!output || !cleaned) throw std::runtime_error("Cannot confirm process-tree cleanup/report");
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "startup-supervisor: " << error.what() << '\n';
        return 1;
    }
}
