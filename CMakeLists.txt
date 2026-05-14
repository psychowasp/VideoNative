cmake_minimum_required(VERSION 3.15)
project(videonative LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

set(PYBIND11_FINDPYTHON ON)
find_package(pybind11 CONFIG REQUIRED)

find_package(Threads REQUIRED)

if(WIN32)
    if(DEFINED ENV{DEFAULT_FFMPEG_DIR})
        set(DEFAULT_FFMPEG_DIR "$ENV{DEFAULT_FFMPEG_DIR}")
    else()
        set(DEFAULT_FFMPEG_DIR "$ENV{USERPROFILE}/Downloads/ffmpeg")
    endif()

    set(FFMPEG_DIR "${DEFAULT_FFMPEG_DIR}" CACHE PATH "Path to FFmpeg root directory.")

    set(FFMPEG_INCLUDE_DIRS "${FFMPEG_DIR}/include")
    set(FFMPEG_LIB_DIR "${FFMPEG_DIR}/lib")

    add_compile_definitions(NOMINMAX)
elseif(ANDROID)
    if(DEFINED ANDROID_FFMPEG_INCLUDE)
        set(FFMPEG_INCLUDE_DIRS "${ANDROID_FFMPEG_INCLUDE}")
        set(FFMPEG_LIB_DIR "${ANDROID_FFMPEG_LIB}")
    else()
        if(CMAKE_SYSTEM_PROCESSOR STREQUAL "aarch64")
            set(_libffmpeg_platform "android_24_arm64_v8a")
        elseif(CMAKE_SYSTEM_PROCESSOR STREQUAL "x86_64")
            set(_libffmpeg_platform "android_24_x86_64")
        else()
            message(FATAL_ERROR "Unsupported Android processor for libffmpeg: ${CMAKE_SYSTEM_PROCESSOR}")
        endif()

        set(_libffmpeg_dir "${CMAKE_CURRENT_BINARY_DIR}/_libffmpeg")

        if(NOT EXISTS "${_libffmpeg_dir}/.includes")
            set(_libffmpeg_ver "8.0.1")
            set(_libffmpeg_whl "${_libffmpeg_dir}/libffmpeg.whl")
            set(_libffmpeg_url
                "https://api.anaconda.org/download/PySwift/libffmpeg/${_libffmpeg_ver}/libffmpeg-${_libffmpeg_ver}-py3-none-${_libffmpeg_platform}.whl")
            message(STATUS "Downloading libffmpeg ${_libffmpeg_ver} for ${_libffmpeg_platform} ...")
            file(MAKE_DIRECTORY "${_libffmpeg_dir}")
            file(DOWNLOAD "${_libffmpeg_url}" "${_libffmpeg_whl}"
                STATUS _dl_status
                TLS_VERIFY ON
            )
            list(GET _dl_status 0 _dl_code)
            list(GET _dl_status 1 _dl_msg)
            if(NOT _dl_code EQUAL 0)
                message(FATAL_ERROR "Failed to download libffmpeg: ${_dl_msg}\n  URL: ${_libffmpeg_url}")
            endif()
            file(ARCHIVE_EXTRACT INPUT "${_libffmpeg_whl}" DESTINATION "${_libffmpeg_dir}")
            file(REMOVE "${_libffmpeg_whl}")
        endif()

        set(FFMPEG_INCLUDE_DIRS "${_libffmpeg_dir}/.includes/ffmpeg")
        set(FFMPEG_LIB_DIR      "${_libffmpeg_dir}/.libs")
    endif()
else()
    find_package(PkgConfig REQUIRED)
    pkg_check_modules(FFMPEG REQUIRED IMPORTED_TARGET 
        libavformat 
        libavcodec 
        libavutil 
        libswscale 
        libswresample
    )
endif()

pybind11_add_module(videonative src/media_decoder.cpp)

target_include_directories(videonative PRIVATE 
    ${CMAKE_CURRENT_SOURCE_DIR}/src/include
)

if(WIN32 OR ANDROID)
    target_include_directories(videonative PRIVATE ${FFMPEG_INCLUDE_DIRS})
    target_link_directories(videonative PRIVATE ${FFMPEG_LIB_DIR})
    target_link_libraries(videonative PRIVATE
        avformat
        avcodec
        avutil
        swscale
        swresample
    )
    if(ANDROID)
        target_link_libraries(videonative PRIVATE OpenSLES log)
    endif()
else()
    target_link_libraries(videonative PRIVATE 
        PkgConfig::FFMPEG
        Threads::Threads
    )
endif()

if(CMAKE_CXX_COMPILER_ID MATCHES "MSVC")
    target_compile_options(videonative PRIVATE /O2)
else()
    target_compile_options(videonative PRIVATE -O3)
endif()

install(TARGETS videonative DESTINATION .)
