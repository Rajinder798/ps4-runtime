# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
cmake_minimum_required(VERSION 3.24)
project(diagnostic-stage-ledger-v1 LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
enable_testing()
find_package(Python3 3.10 REQUIRED COMPONENTS Interpreter)
add_subdirectory(../hid_list_assessment_v1 frozen-host)
add_library(diagnostic-stage-ledger-v1 ledger_v1.cpp)
target_link_libraries(diagnostic-stage-ledger-v1 PUBLIC rejection-fake-clock-v1)
warnings(diagnostic-stage-ledger-v1)
add_executable(stage-ledger-host-v1 ledger_host_tests.cpp)
target_link_libraries(stage-ledger-host-v1 PRIVATE diagnostic-stage-ledger-v1)
warnings(stage-ledger-host-v1)
add_test(NAME stage-ledger-v1 COMMAND ${Python3_EXECUTABLE} -B
    ${CMAKE_CURRENT_SOURCE_DIR}/ledger_tests.py $<TARGET_FILE:stage-ledger-host-v1>)
set_tests_properties(stage-ledger-v1 PROPERTIES TIMEOUT 45)
