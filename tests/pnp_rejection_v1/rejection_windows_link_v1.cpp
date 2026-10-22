// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
#include "rejection_windows_v1.h"
// HOST TEST: compile/link/vtable/inert lifetime only. No Source method is called.
int main(int argc, char **) {
    if (argc != 1)
        return 2;
    rejection_v1::WindowsSource inert;
    return 0;
}
