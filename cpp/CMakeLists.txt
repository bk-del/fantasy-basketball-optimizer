cmake_minimum_required(VERSION 3.22)
project(fantasy_optimizer VERSION 0.0.1 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

find_program(CLANG_TIDY NAMES clang-tidy-14 clang-tidy REQUIRED)
set(CMAKE_CXX_CLANG_TIDY "${CLANG_TIDY};--warnings-as-errors=*")

add_library(fantasy_optimizer STATIC src/foundation.cpp src/matchup_kernel.cpp)
target_include_directories(fantasy_optimizer PUBLIC include)

include(CTest)
if(BUILD_TESTING)
    add_executable(foundation_smoke tests/test_foundation.cpp)
    target_link_libraries(foundation_smoke PRIVATE fantasy_optimizer)
    add_test(NAME foundation_smoke COMMAND foundation_smoke)
    find_package(Catch2 2.13.8 REQUIRED)
    add_executable(matchup_kernel_test tests/test_matchup.cpp)
    target_link_libraries(matchup_kernel_test PRIVATE fantasy_optimizer Catch2::Catch2)
    add_test(NAME matchup_kernel COMMAND matchup_kernel_test)
endif()

foreach(target fantasy_optimizer foundation_smoke matchup_kernel_test)
    if(TARGET ${target} AND CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
        target_compile_options(${target} PRIVATE -Wall -Wextra -Wpedantic -Werror)
        target_compile_options(${target} PRIVATE
            "$<$<CONFIG:Debug>:-fsanitize=address,undefined;-fno-omit-frame-pointer>")
        target_link_options(${target} PUBLIC
            "$<$<CONFIG:Debug>:-fsanitize=address,undefined>")
    endif()
endforeach()

if(NOT DEFINED Python_EXECUTABLE AND EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/../.venv/bin/python")
    set(Python_EXECUTABLE "${CMAKE_CURRENT_SOURCE_DIR}/../.venv/bin/python")
endif()
find_package(Python 3.12 COMPONENTS Interpreter Development.Module REQUIRED)
execute_process(COMMAND "${Python_EXECUTABLE}" -m nanobind --cmake_dir
    OUTPUT_VARIABLE nanobind_DIR OUTPUT_STRIP_TRAILING_WHITESPACE
    COMMAND_ERROR_IS_FATAL ANY)
find_package(nanobind CONFIG REQUIRED)
execute_process(COMMAND "${Python_EXECUTABLE}" -m nanobind --include_dir
    OUTPUT_VARIABLE nanobind_INCLUDE OUTPUT_STRIP_TRAILING_WHITESPACE
    COMMAND_ERROR_IS_FATAL ANY)
nanobind_add_module(_matchup src/matchup.cpp src/matchup_kernel.cpp)
target_include_directories(_matchup PRIVATE include)
target_include_directories(_matchup SYSTEM PRIVATE "${nanobind_INCLUDE}")
# Do not impose repository lint policy on third-party nanobind implementation.
set_target_properties(nanobind-static PROPERTIES CXX_CLANG_TIDY "")
install(TARGETS _matchup LIBRARY DESTINATION .)
# Python owns the interpreter: keep ASan/UBSan in the standalone Debug target.
# This module is checked by parity/validation tests and clang-tidy.
if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
    target_compile_options(_matchup PRIVATE -Wall -Wextra -Wpedantic -Werror)
endif()
if(BUILD_TESTING)
    add_test(NAME matchup_parity COMMAND "${Python_EXECUTABLE}"
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/run_parity.py"
        "$<TARGET_FILE:_matchup>"
        "${CMAKE_CURRENT_SOURCE_DIR}/../tests/test_simulation.py")
endif()
