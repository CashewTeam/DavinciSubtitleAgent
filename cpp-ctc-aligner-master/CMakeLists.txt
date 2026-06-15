cmake_minimum_required(VERSION 3.20)
project(cpp_ort_aligner VERSION 0.2.2 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)

# Get git hash for version info
find_package(Git QUIET)
if(GIT_FOUND)
  execute_process(
    COMMAND ${GIT_EXECUTABLE} rev-parse --short HEAD
    WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
    OUTPUT_VARIABLE GIT_HASH
    OUTPUT_STRIP_TRAILING_WHITESPACE
    ERROR_QUIET
  )
  execute_process(
    COMMAND ${GIT_EXECUTABLE} status --porcelain
    WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
    OUTPUT_VARIABLE GIT_STATUS
    OUTPUT_STRIP_TRAILING_WHITESPACE
    ERROR_QUIET
  )
  if(NOT "${GIT_STATUS}" STREQUAL "")
    set(GIT_HASH "${GIT_HASH}-dirty")
  endif()
else()
  set(GIT_HASH "unknown")
endif()

configure_file(
  ${CMAKE_SOURCE_DIR}/src/version.h.in
  ${CMAKE_BINARY_DIR}/generated/version.h
  @ONLY
)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

option(USE_SYSTEM_ORT "Use system-installed ONNX Runtime" ON)

# Include directory for nlohmann/json and other headers
include_directories(${CMAKE_SOURCE_DIR}/include)
include_directories(${CMAKE_SOURCE_DIR}/src)
include_directories(${CMAKE_BINARY_DIR}/generated)

add_executable(cpp-ort-aligner
  src/cli_args.cpp
  src/main.cpp
  src/audio_decode.cpp
  src/emissions.cpp
  src/forced_align.cpp
  src/hangul_romaji.cpp
  src/json_io.cpp
  src/kana_romaji.cpp
  src/kanji_pinyin.cpp
  src/model_config.cpp
  src/span_align.cpp
  src/postprocess.cpp
  src/srt_io.cpp
  src/stacktrace.cpp
  src/crash_handler.cpp
  src/text_preprocess.cpp
  src/vocab.cpp
  src/vocab_json.cpp
)

if (USE_SYSTEM_ORT)
  # Expect user sets ONNXRUNTIME_DIR to the extracted onnxruntime package root.
  # If not set, default to the bundled ORT under cpp-ort-aligner/models/.
  if (NOT DEFINED ONNXRUNTIME_DIR)
    set(ONNXRUNTIME_DIR "${CMAKE_SOURCE_DIR}/models/onnxruntime-win-x64-1.23.2")
  endif()

  # Use absolute paths to avoid generator-dependent relative path quirks on Windows.
  get_filename_component(ONNXRUNTIME_DIR_ABS "${ONNXRUNTIME_DIR}" ABSOLUTE BASE_DIR "${CMAKE_SOURCE_DIR}")
  target_include_directories(cpp-ort-aligner PRIVATE "${ONNXRUNTIME_DIR_ABS}/include")
  target_link_directories(cpp-ort-aligner PRIVATE "${ONNXRUNTIME_DIR_ABS}/lib")
  target_link_libraries(cpp-ort-aligner PRIVATE onnxruntime)
endif()

# Set RPATH for Linux so the executable can find libonnxruntime.so in the same directory
if (NOT WIN32 AND NOT APPLE)
  set(CMAKE_BUILD_WITH_INSTALL_RPATH TRUE)
  set(CMAKE_INSTALL_RPATH "$ORIGIN")
  set_target_properties(cpp-ort-aligner PROPERTIES
    BUILD_RPATH "$ORIGIN"
    INSTALL_RPATH "$ORIGIN"
  )
endif()

if (MSVC)
  target_compile_options(cpp-ort-aligner PRIVATE /W4 /permissive- /utf-8)
  target_compile_definitions(cpp-ort-aligner PRIVATE _CRT_SECURE_NO_WARNINGS)
  target_link_libraries(cpp-ort-aligner PRIVATE dbghelp)
  # Generate debug info even in Release for better stack traces
  target_compile_options(cpp-ort-aligner PRIVATE $<$<CONFIG:Release>:/Zi>)
  target_link_options(cpp-ort-aligner PRIVATE $<$<CONFIG:Release>:/DEBUG>)
else()
  target_compile_options(cpp-ort-aligner PRIVATE -Wall -Wextra -Wpedantic)
  # Enable -rdynamic for better stack traces on Linux/macOS
  if (NOT APPLE)
    target_link_options(cpp-ort-aligner PRIVATE -rdynamic)
  endif()
  # Generate debug info even in Release for better stack traces
  target_compile_options(cpp-ort-aligner PRIVATE $<$<CONFIG:Release>:-g>)
endif()
