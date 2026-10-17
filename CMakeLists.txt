# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

cmake_minimum_required(VERSION 3.24)
project(ps4_runtime VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

add_library(ps4_inspector src/elf_inspector.cpp)
target_include_directories(ps4_inspector PUBLIC include)
add_library(ps4_probe_loader src/probe_loader.cpp)
target_link_libraries(ps4_probe_loader PUBLIC ps4_inspector)
add_executable(ps4-runtime src/main.cpp)
target_link_libraries(ps4-runtime PRIVATE ps4_probe_loader)
if(MINGW)
    target_link_options(ps4-runtime PRIVATE -municode -static)
endif()

function(runtime_warnings target)
    if(MSVC)
        target_compile_options(${target} PRIVATE /W4 /WX /permissive-)
    else()
        target_compile_options(${target} PRIVATE -Wall -Wextra -Wpedantic -Werror)
    endif()
endfunction()
runtime_warnings(ps4_inspector)
runtime_warnings(ps4_probe_loader)
runtime_warnings(ps4-runtime)

include(CTest)
if(BUILD_TESTING)
    add_executable(inspector-tests tests/inspector_tests.cpp)
    target_link_libraries(inspector-tests PRIVATE ps4_inspector)
    runtime_warnings(inspector-tests)
    add_test(NAME elf-validation COMMAND inspector-tests)
    add_executable(probe-loader-tests tests/probe_loader_tests.cpp)
    target_link_libraries(probe-loader-tests PRIVATE ps4_probe_loader)
    runtime_warnings(probe-loader-tests)
    add_test(NAME probe-mapping COMMAND probe-loader-tests)
    find_package(Python3 3.9 REQUIRED COMPONENTS Interpreter)
    add_test(NAME cli-contract COMMAND ${Python3_EXECUTABLE}
        ${CMAKE_CURRENT_SOURCE_DIR}/tests/cli_tests.py $<TARGET_FILE:ps4-runtime>)
    set_tests_properties(elf-validation probe-mapping cli-contract PROPERTIES TIMEOUT 30)
endif()
