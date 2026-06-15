#pragma once

#include <filesystem>
#include <string>
#include <vector>

struct SrtSegment {
  int index = 0;
  double start_sec = 0.0;
  double end_sec = 0.0;
  std::string text;
  float score = 0.0f;  // alignment confidence score
};

std::vector<SrtSegment> read_srt_utf8(const std::filesystem::path& path);
void write_srt_utf8(const std::filesystem::path& path, const std::vector<SrtSegment>& segs);

