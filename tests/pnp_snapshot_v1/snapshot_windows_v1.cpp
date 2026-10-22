// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
#include "snapshot_v1.h"
#include "snapshot_build_v1.h"
#include "../pnp_rejection_v1/rejection_windows_v1.h"
#include <fstream>
#include <iostream>
// Supported entry point is tools/pnp_snapshot_v1.py, which verifies and pins
// source/binary/preserved evidence before minting this single-use work permit.
// This internal worker never creates its own authorization.
int wmain(int argc, wchar_t **argv) {
    if (argc == 2 && std::wstring_view(argv[1]) == L"--identity-only") {
        std::cout << "{\"schema\":\"pnp-snapshot-worker-v1\",\"source_commit\":\""
                  << SNAPSHOT_SOURCE_COMMIT << "\",\"device_queries\":0}\n";
        return 0;
    }
    if (argc == 2 && std::wstring_view(argv[1]) == L"--inert-link-check") {
        rejection_v1::WindowsSource inert;
        return 0; // No Source method, registration or device query.
    }
    if (argc != 3 || std::wstring_view(argv[1]) != L"--authorized-one-initial-snapshot-v1")
        return 2;
    try {
        const auto folder = std::filesystem::absolute(argv[2]).lexically_normal();
        const auto permit = folder / "query-permit-v1.txt";
        std::ifstream input(permit, std::ios::binary);
        std::string content(128, '\0');
        input.read(content.data(), static_cast<std::streamsize>(content.size()));
        content.resize(static_cast<std::size_t>(input.gcount()));
        if (content != "pnp-snapshot-v1\nAUTHORIZE EXACTLY ONE INITIAL SNAPSHOT\n" ||
            std::filesystem::exists(folder / "query-permit-v1.consumed"))
            return 2;
        input.close();
        // Same-directory atomic consumption; a second worker cannot reuse it.
        std::filesystem::rename(permit, folder / "query-permit-v1.consumed");
        rejection_v1::WindowsSource source;
        return snapshot_v1::Run(source, folder, false);
    } catch (const std::exception &) {
        std::cerr << "One-shot snapshot failed; retain evidence and supervisor cleanup\n";
        return 1;
    }
}
