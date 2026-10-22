// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
#include "arrival_trace_v1.h"
#include <iostream>
int main() {
    using namespace arrival_v1;
    try {
        auto require=[](bool okay){if(!okay)throw std::runtime_error("Arrival policy mismatch");};
        require(IntendedPath(L"\\\\?\\USB#VID_054C&PID_0CE6#HOST_TEST"));
        require(IntendedPath(L"\\\\?\\hid#vid_054c&pid_0ce6&mi_03#HOST_TEST"));
        require(!IntendedPath(L"\\\\?\\USB#VID_054C&PID_0CE60#HOST_TEST"));
        require(!IntendedPath(L"\\\\?\\USB#VID_0001&PID_0002#HOST_TEST"));
        require(!IntendedPath(L"PRIVATE#VID_054C&PID_0CE6#HOST_TEST"));
        require(Candidate(1,1356,3302,6,false,2,1)=="candidate");
        require(Candidate(2,1356,3302,6,false,2,1)=="device_count");
        require(Candidate(0,0,0,0,false,0,1)=="device_count");
        require(Candidate(1,1356,3302,6,true,2,1)=="virtual_device");
        require(Candidate(1,1356,3302,0,false,2,1)=="wrong_device");
        require(Candidate(1,1356,3302,6,false,1,1)=="stale_instance");
        require(Candidate(1,1356,3302,6,false,0,0)=="stale_instance");
        require(RawAssessment(0x605,1,1,false,1)=="joystick_only");
        require(RawAssessment(0x606,1,1,false,1)=="joystick_only");
        require(RawAssessment(0x653,1,1,false,1)=="initial_announcement");
        require(RawAssessment(0x653,2,1,true,1)=="enumeration_required");
        require(RawAssessment(0x653,3,1,true,2)=="unexpected_addition");
        require(RawAssessment(0x654,1,1,false,1)=="selected_removal");
        require(RawAssessment(0x654,1,1,true,1)=="unexpected_removal");
        require(RawAssessment(0x655,1,1,false,1)=="remap_rejected");
        require(Quote("a\"b")=="\"a\\\"b\"");
        bool rejected=false;
        try {static_cast<void>(Quote("\n"));} catch(const std::runtime_error&) {rejected=true;}
        require(rejected);
        std::cout<<"Host-only classification checks passed; no hardware initialized\n";return 0;
    } catch(const std::exception& error) {std::cerr<<error.what()<<'\n';return 1;}
}
