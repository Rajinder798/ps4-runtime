# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
cmake_minimum_required(VERSION 3.24)
project(hid-list-assessment-v1 LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
enable_testing()
find_package(Python3 3.10 REQUIRED COMPONENTS Interpreter)
# Existing host regressions, including inert Windows ownership tests. No live mode.
add_subdirectory(../pnp_snapshot_v1 frozen-host)
add_library(hid-list-assessment-v1 assessment_v1.cpp)
warnings(hid-list-assessment-v1)
add_executable(hid-list-assessment-tests-v1 assessment_tests.cpp)
target_link_libraries(hid-list-assessment-tests-v1 PRIVATE hid-list-assessment-v1 pnp-core-v2)
warnings(hid-list-assessment-tests-v1)
add_test(NAME hid-list-property-v1 COMMAND hid-list-assessment-tests-v1)
add_test(NAME hid-list-privacy-v1 COMMAND ${Python3_EXECUTABLE} -B
    ${CMAKE_CURRENT_SOURCE_DIR}/assessment_tests.py $<TARGET_FILE:hid-list-assessment-tests-v1>)

# Test-only instrumented COPY: exactly two definition-name substitutions. All
# Collector/Trace call sites and all companion code remain the frozen source.
# No generated copy is used by an observer, worker, bundle or production target.
file(READ ../pnp_readiness_v2/pnp_coverage_v2.cpp core)
foreach(name Ticks Frequency)
    string(REGEX MATCHALL "Tick ${name}\\(\\) \\{" definitions "${core}")
    list(LENGTH definitions count)
    if(NOT count EQUAL 1)
        message(FATAL_ERROR "Frozen clock definition seam changed")
    endif()
    string(REPLACE "Tick ${name}() {" "Tick UncalledReal${name}() {" core "${core}")
endforeach()
file(WRITE ${CMAKE_CURRENT_BINARY_DIR}/frozen_core_fake_clock.cpp "${core}")
add_library(rejection-fake-clock-v1
    ${CMAKE_CURRENT_BINARY_DIR}/frozen_core_fake_clock.cpp
    ../pnp_readiness_v2/hardware_ids_v2.cpp ../pnp_rejection_v1/rejection_v1.cpp fake_clock.cpp)
target_include_directories(rejection-fake-clock-v1 PRIVATE ../pnp_readiness_v2)
warnings(rejection-fake-clock-v1)
add_executable(rejection-budget-tests-v1 budget_tests.cpp)
target_link_libraries(rejection-budget-tests-v1 PRIVATE rejection-fake-clock-v1)
warnings(rejection-budget-tests-v1)
add_test(NAME hid-diagnostic-budget-v1 COMMAND ${Python3_EXECUTABLE} -B
    ${CMAKE_CURRENT_SOURCE_DIR}/budget_tests.py $<TARGET_FILE:rejection-budget-tests-v1>)
set_tests_properties(hid-list-property-v1 hid-list-privacy-v1 hid-diagnostic-budget-v1 PROPERTIES TIMEOUT 45)
