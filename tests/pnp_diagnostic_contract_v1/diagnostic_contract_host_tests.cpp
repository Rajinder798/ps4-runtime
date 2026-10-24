// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
// Synthetic providers and owned files only. Never constructs WindowsProvider.
#include "diagnostic_contract_v1.h"
#include <chrono>
#include <fstream>
#include <iostream>
#include <limits>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <thread>
#include <tuple>

using namespace diagnostic_v1;
namespace {
void Check(bool b) { if (!b) throw std::runtime_error("HOST TEST contract assertion"); }
struct Fault : std::runtime_error { int code = 77; Fault() : std::runtime_error("PRIVATE synthetic native exception") {} };
struct TestClock : Clock {
    Tick tick = 100, step = 1, frequency = 10000000;
    unsigned calls = 0, throw_at = 0, reverse_at = 0, late_at = 0;
    Tick Now() override {
        ++calls;
        if (calls == throw_at) throw Fault();
        if (calls == reverse_at) return 0;
        if (calls == late_at) tick += frequency;
        const auto result = tick;
        if (tick <= std::numeric_limits<Tick>::max()-step) tick += step;
        return result;
    }
    Tick Frequency() override { return frequency; }
};
Node Make(Id id, Bus bus, Hardware hardware, Id parent = 0) {
    Node n; n.id=id; n.parent=parent; n.bus=bus; n.hardware=hardware;
    n.enum_code=n.hw_code=n.compatible_code=n.status_code=0;
    n.parent_code=parent ? 0 : 13; n.status=8;
    n.enumerator_valid=n.hardware_valid=n.compatible_valid=true;
    return n;
}
auto Signature(const Node &n) {
    return std::make_tuple(n.id,n.parent,n.bus,n.hardware,n.hardware_reason,n.hardware_type,n.hardware_bytes,
        n.enum_code,n.hw_code,n.compatible_code,n.parent_code,n.status_code,n.status,n.problem,
        n.composite,n.enumerator_valid,n.hardware_valid,n.compatible_valid,n.resource_limited);
}
struct Fake : Provider {
    std::vector<std::string> transcript;
    std::map<Id,unsigned> reads;
    std::string throw_kind;
    bool changing=false, bad=false, oversized=false, delay=false;
    void Call(const std::string &method, const std::string &argument) {
        transcript.push_back(method+":"+argument);
        if (throw_kind==method) throw Fault();
    }
    Enumeration Devnodes() override {
        Call("devnodes",""); Enumeration e; e.nodes={1,2,3};
        if (oversized) e.nodes.resize(NodeCap+1,1);
        return e;
    }
    Enumeration Interfaces(Bus b) override {
        Call("interfaces",std::to_string(static_cast<int>(b)));
        Enumeration e; e.interfaces={{b==Bus::Usb ? 1U : 3U,1,0,122}}; return e;
    }
    Lookup InterfaceNode(std::wstring_view path, Bus b) override {
        Check(path==L"PRIVATE-HARDWARE-INSTANCE-SERIAL");
        Call("lookup",std::to_string(static_cast<int>(b)));
        Lookup r; r.iface={3,1,0,122}; return r;
    }
    Node Properties(Id id) override {
        Call("properties",std::to_string(id));
        if (delay) { delay=false; std::this_thread::sleep_for(std::chrono::milliseconds(300)); }
        ++reads[id];
        auto n=id==1 ? Make(1,Bus::Usb,Hardware::UsbParent) : id==2 ?
            Make(2,Bus::Usb,Hardware::UsbFunction,1) : Make(id,Bus::Hid,Hardware::Hid,2);
        if (id==1) n.composite=true;
        if (bad && id==3) { n.hw_code=5; n.hardware_valid=false; }
        if (changing && reads[id]>1) { n.status=0; n.parent=99; n.parent_code=5; }
        return n;
    }
    Key InstanceKey(Id id) override {
        Call("key",std::to_string(id)); return {L"PRIVATE-SERIAL-"+std::to_wstring(id),0};
    }
};
void DirectCalls(Provider &p) {
    Check(!p.Devnodes().nodes.empty());
    Check(p.Interfaces(Bus::Usb).interfaces[0].flags==1);
    Check(p.Interfaces(Bus::Hid).interfaces[0].node==3);
    Check(p.InterfaceNode(L"PRIVATE-HARDWARE-INSTANCE-SERIAL",Bus::Hid).iface.node==3);
    Check(p.Properties(3).status==8);
    Check(p.Properties(3).parent==99);
    Check(p.InstanceKey(3).value==L"PRIVATE-SERIAL-3");
}
void Policy() {
    Fake plain, observed; plain.changing=observed.changing=true;
    TestClock clock; Recorder recorder(observed,clock);
    DirectCalls(plain); DirectCalls(recorder);
    Check(plain.transcript==observed.transcript);
    auto frozen=std::move(recorder).Freeze();
    const auto calls=observed.transcript.size(); Replay replay(frozen);
    auto nodes=replay.Observations(3); Check(nodes.size()==2 && nodes[0].status==8 && nodes[1].status==0);
    Check(nodes[1].parent==99 && nodes[1].parent_code==5);
    nodes[0].status=999; Check(replay.Observations(3)[0].status==8);
    Check(replay.Observations(9999).empty() && replay.Unknown()>0);
    Check(observed.transcript.size()==calls); // replay cannot call the Provider
    Fake reference; reference.changing=true;
    Check(Signature(reference.Properties(3))==Signature(std::get<Node>(frozen.View().records[4].value)));
    Check(Signature(reference.Properties(3))==Signature(std::get<Node>(frozen.View().records[5].value)));
    for (const auto &kind : {"devnodes","interfaces","lookup","properties","key"}) {
        Fake source; source.throw_kind=kind; TestClock time; Recorder r(source,time);
        bool caught=false;
        try {
            if (source.throw_kind=="devnodes") (void)r.Devnodes();
            else if (source.throw_kind=="interfaces") (void)r.Interfaces(Bus::Hid);
            else if (source.throw_kind=="lookup") (void)r.InterfaceNode(L"PRIVATE-HARDWARE-INSTANCE-SERIAL",Bus::Hid);
            else if (source.throw_kind=="properties") (void)r.Properties(3);
            else (void)r.InstanceKey(3);
        } catch (const Fault &e) { caught=e.code==77 && std::string(e.what())=="PRIVATE synthetic native exception"; }
        Check(caught && source.transcript.size()==1);
        auto f=std::move(r).Freeze(); Check(f.View().calls==1 && f.View().records[0].threw);
    }
    // Oversized typed results still forward intact; capture refuses the copy.
    Fake large; large.oversized=true; TestClock t; Recorder r(large,t);
    Check(r.Devnodes().nodes.size()==NodeCap+1);
    auto f=std::move(r).Freeze(); Check(f.View().dropped==1 && f.View().records.empty());
    // Deliberately unsafe cache negative control: a repeated ID loses a later fact.
    Fake mutable_source; mutable_source.changing=true;
    const auto early=mutable_source.Properties(3); const auto later=mutable_source.Properties(3);
    Check(early.status!=later.status && early.parent!=later.parent);
}
std::string Read(const std::filesystem::path &p) {
    std::ifstream f(p,std::ios::binary); return {std::istreambuf_iterator<char>(f),{}};
}
Tick Number(const std::string &line, const std::string &key) {
    const auto at=line.find("\""+key+"\":"); Check(at!=std::string::npos);
    return std::stoll(line.substr(at+key.size()+3));
}
Native Proof(const std::filesystem::path &p, bool threw) {
    Native n; n.exception=threw; std::ifstream f(p); std::string line;
    while (std::getline(f,line)) {
        if (line.find("\"event\":\"header\"")!=std::string::npos) n.frequency=Number(line,"qpc_frequency");
        if (line.find("\"event\":\"first_failure\"")!=std::string::npos) {
            n.first_reason=static_cast<unsigned>(Number(line,"reason")); n.first_qpc=Number(line,"qpc");
        }
        if (line.find("\"event\":\"snapshot\"")!=std::string::npos) n.ready=line.find("\"initial_ready\":true")!=std::string::npos;
        if (line.find("\"event\":\"summary\"")!=std::string::npos) n.coverage=line.find("\"coverage_complete\":true")!=std::string::npos;
    }
    Check(n.frequency>0); return n;
}
Native Collect(const std::filesystem::path &path, Provider &p) {
    bool threw=false;
    {
        Trace trace(path,true); Collector c(p,trace); auto queue=std::make_unique<Queue>();
        const auto begin=Ticks(); trace.Session(MaxDurationMs,begin);
        trace.Registration(Bus::Usb,0); trace.Registration(Bus::Hid,0);
        try { c.Snapshot(); } catch (const Fault &) { threw=true; }
        c.QueueSummary(*queue); trace.Registration(Bus::Usb,0,true); trace.Registration(Bus::Hid,0,true);
        trace.Stopped(begin,Ticks(),true); trace.Cleanup(0); trace.Finish(c.Complete(),true);
    }
    return Proof(path,threw);
}
void Fixture(const std::filesystem::path &root, const std::string &name) {
    const auto folder=root/name; std::filesystem::create_directory(folder);
    Fake raw, reference; TestClock clock; Limits limits; Options options; unsigned copy_fault=0;
    if (name=="native-failure") raw.bad=reference.bad=true;
    if (name=="changing") raw.changing=reference.changing=true;
    if (name=="records") limits.records=2;
    if (name=="payload") limits.payload=0;
    if (name=="events") limits.events=1;
    if (name=="copy-fault") copy_fault=2;
    if (name=="clock-throw") clock.throw_at=3;
    if (name=="clock-reverse") clock.reverse_at=3;
    if (name=="clock-overflow") clock.tick=std::numeric_limits<Tick>::max()-10;
    if (name=="clock-frequency") clock.frequency=41;
    if (name=="timeout") clock.step=50000;
    if (name=="missing") options.missing_request=true;
    if (name=="replay-fault") options.replay_fault=true;
    if (name=="cleanup-fault") options.cleanup_ok=false;
    if (name=="finalization-fault") options.finalization_ok=false;
    if (name=="write-fault") options.write_fault=true;
    if (name=="publish-fault") options.publish_fault=true;
    if (name=="row-cap") limits.rows=16;
    if (name=="byte-cap") limits.bytes=4096;
    if (name=="native-throw") raw.throw_kind=reference.throw_kind="properties";
    if (name=="native-overhead") raw.delay=true;
    const Native plain=Collect(folder/"plain-native.jsonl",reference);
    Recorder recorder(raw,clock,limits,copy_fault);
    const Native n=Collect(folder/"native.jsonl",recorder);
    auto frozen=std::move(recorder).Freeze();
    const auto count=raw.transcript.size();
    if (name=="late-close") clock.late_at=clock.calls+8;
    if (name=="late-publication") clock.late_at=clock.calls+4;
    if (name=="late-clock-throw") clock.throw_at=clock.calls+1;
    if (name=="clock-domain-change") clock.frequency=1000;
    const auto output=name=="open-fault" ? folder/"absent"/"contract.jsonl" : folder/"contract.jsonl";
    const auto result=Finish(output,frozen,n,clock,options);
    Check(raw.transcript==reference.transcript && raw.transcript.size()==count);
    // These are data/exception invariants, never equality of native wall-clock timestamps.
    if (name!="native-overhead" && plain.first_reason!=9 && n.first_reason!=9)
        Check(std::tie(plain.ready,plain.coverage,plain.first_reason,plain.exception)==
              std::tie(n.ready,n.coverage,n.first_reason,n.exception));
    if (name=="native-overhead") Check(n.first_reason==9 && !n.coverage);
    if (result.published) {
        const auto text=Read(folder/"contract.jsonl");
        Check(text.find("PRIVATE")==std::string::npos && text.find("SERIAL")==std::string::npos);
    }
    std::ofstream manifest(folder/"result.json");
    manifest << "{\"published\":" << (result.published?"true":"false")
             << ",\"complete\":" << (result.complete?"true":"false")
             << ",\"reason\":\"" << Name(result.diagnostic) << "\",\"calls\":" << count
             << ",\"native_first\":" << n.first_reason << ",\"plain_first\":" << plain.first_reason
             << ",\"transcripts_equal\":true,\"native_exception\":" << (n.exception?"true":"false") << "}\n";
}
}
int main(int argc, char **argv) {
    try {
        if (argc!=2) return 2;
        Policy();
        const std::filesystem::path root=argv[1];
        Check(!std::filesystem::exists(root)); std::filesystem::create_directories(root);
        for (const auto &name : {"good","native-failure","changing","records","payload","events","copy-fault",
             "clock-throw","clock-reverse","clock-overflow","clock-frequency","timeout","missing","replay-fault",
             "cleanup-fault","finalization-fault","write-fault","row-cap","byte-cap","late-close","late-publication",
             "native-throw","native-overhead","open-fault","publish-fault","late-clock-throw","clock-domain-change"}) Fixture(root,name);
        std::cout << "HOST TEST: forwarding, replay, native preservation and 27 fixture cases passed\n";
        return 0;
    } catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; }
}
