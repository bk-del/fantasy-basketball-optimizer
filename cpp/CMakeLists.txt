cmake_minimum_required(VERSION 3.22)
project(fantasy_optimizer VERSION 0.0.1 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

find_program(CLANG_TIDY NAMES clang-tidy-14 clang-tidy REQUIRED)
set(CMAKE_CXX_CLANG_TIDY "${CLANG_TIDY};--warnings-as-errors=*")

add_library(fantasy_optimizer STATIC src/foundation.cpp)
target_include_directories(fantasy_optimizer PUBLIC include)

include(CTest)
if(BUILD_TESTING)
    add_executable(foundation_smoke tests/test_foundation.cpp)
    target_link_libraries(foundation_smoke PRIVATE fantasy_optimizer)
    add_test(NAME foundation_smoke COMMAND foundation_smoke)
endif()

foreach(target fantasy_optimizer foundation_smoke)
    if(TARGET ${target} AND CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
        target_compile_options(${target} PRIVATE -Wall -Wextra -Wpedantic -Werror)
        target_compile_options(${target} PRIVATE
            "$<$<CONFIG:Debug>:-fsanitize=address,undefined;-fno-omit-frame-pointer>")
        target_link_options(${target} PUBLIC
            "$<$<CONFIG:Debug>:-fsanitize=address,undefined>")
    endif()
endforeach()
