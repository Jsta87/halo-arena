cmake_minimum_required(VERSION 3.16)
project(halo_obj_viewer C)

set(CMAKE_C_STANDARD 99)
set(CMAKE_C_STANDARD_REQUIRED ON)

find_package(raylib REQUIRED)

add_executable(halo_obj_viewer main.c)
target_link_libraries(halo_obj_viewer PRIVATE raylib m)
