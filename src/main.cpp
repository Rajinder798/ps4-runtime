#include "ps4/elf_inspector.h"

#include <filesystem>
#include <fstream>
#include <iostream>
#include <vector>

namespace {
void usage(std::ostream& out) {
    out << "PS4 Runtime 0.1.0 - executable inspection\n"
           "Usage: ps4-runtime inspect <file> [--json]\n"
           "       ps4-runtime --help | --version\n"
           "No guest execution or SELF unpacking is implemented.\n";
}
}

int run(const std::vector<std::filesystem::path>& args) {
    const auto argc = args.size();
    if (argc == 2 && args[1] == "--help") { usage(std::cout); return 0; }
    if (argc == 2 && args[1] == "--version") {
        std::cout << "ps4-runtime 0.1.0\n"; return 0;
    }
    if ((argc != 3 && argc != 4) || args[1] != "inspect" ||
        (argc == 4 && args[3] != "--json")) {
        usage(std::cerr); return 2;
    }
    try {
        std::ifstream input(args[2], std::ios::binary);
        if (!input) throw ps4::InspectionError("open_failed", "Could not open input file.");
        const auto result = ps4::inspect_elf(input);
        std::cout << (argc == 4 ? ps4::to_json(result) : ps4::to_text(result));
        return 0;
    } catch (const ps4::InspectionError& error) {
        std::cerr << "error[" << error.code() << "]: " << error.what() << '\n';
        return 1;
    } catch (const std::exception&) {
        std::cerr << "error[internal_error]: Unexpected inspection failure.\n";
        return 1;
    }
}

#ifdef _WIN32
int wmain(int argc, wchar_t** argv) {
#else
int main(int argc, char** argv) {
#endif
    // Preserve native Unicode paths on Windows through its wide-character entry point.
    return run(std::vector<std::filesystem::path>(argv, argv + argc));
}
