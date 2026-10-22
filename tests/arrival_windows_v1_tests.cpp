// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
#include "arrival_windows_v1.h"
#include <iostream>
#include <iterator>
int main() {
    namespace fs=std::filesystem;
    const auto folder=fs::temp_directory_path()/("ps4-arrival-host-only-"+std::to_string(arrival_v1::Ticks()));
    try {
        if (!fs::create_directory(folder)) throw std::runtime_error("Fresh test folder required");
        const auto path=folder/"callback.jsonl";
        {arrival_v1::Trace trace(path,true);arrival_v1::WindowsCallbackHostTest(trace);trace.Finish(true);}
        std::ifstream in(path);std::string raw((std::istreambuf_iterator<char>(in)),{});
        if (raw.find("HOST_TEST_ONLY")!=std::string::npos || raw.find("VID_")!=std::string::npos ||
            raw.find("windows_notification")==std::string::npos || raw.find("host-test")==std::string::npos)
            throw std::runtime_error("Callback privacy/schema mismatch");
        {arrival_v1::Trace trace(folder/"failure.jsonl",true,2048,8);
         bool exhausted=false;
         try {for (int i=0;i<20;++i)trace.Emit("poll_heartbeat");}catch(const std::runtime_error&) {exhausted=true;}
         if(!exhausted)throw std::runtime_error("Missing resource failure");
         trace.Fail("first_test_error");trace.Fail("later_cleanup_error");trace.Finish(false);}
        std::ifstream failed(folder/"failure.jsonl");std::string failure((std::istreambuf_iterator<char>(failed)),{});
        if(failure.find("first_test_error")==std::string::npos || failure.find("later_cleanup_error")!=std::string::npos ||
           failure.find("\"status\":\"failed\"")==std::string::npos)
            throw std::runtime_error("First failure was replaced or suppressed");
        in.close();failed.close();
        std::cout<<"Controlled callback/parser/privacy/bounds checks passed. No Windows registration, enumeration or SDL initialization.\n";
        if (fs::canonical(folder).parent_path()!=fs::canonical(fs::temp_directory_path()) ||
            !folder.filename().string().starts_with("ps4-arrival-host-only-"))
            throw std::runtime_error("Host test cleanup target invalid");
        fs::remove_all(folder);return 0;
    } catch(const std::exception& error) {std::cerr<<error.what()<<"; host evidence retained: "<<folder<<'\n';return 1;}
}
