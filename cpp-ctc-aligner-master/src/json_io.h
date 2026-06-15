#pragma once

#include "srt_io.h"
#include <filesystem>
#include <string>
#include <vector>

// Parse JSON input file into SrtSegment vector
// Supports: {"segments": [...]} or direct array [...]
// Fields: index (optional), start (optional), end (optional), text (required)
std::vector<SrtSegment> read_json_input(const std::filesystem::path& path);

// Parse JSON from string (for stdin support)
std::vector<SrtSegment> parse_json_input(const std::string& content);

// Write segments to JSON output file
// Format: {"segments": [...], "metadata": {"count": N, "processing_time": T}}
void write_json_output(
    const std::filesystem::path& path,
    const std::vector<SrtSegment>& segments,
    double processing_time = 0.0);

// Write segments to JSON string (for stdout support)
std::string format_json_output(
    const std::vector<SrtSegment>& segments,
    double processing_time = 0.0);
