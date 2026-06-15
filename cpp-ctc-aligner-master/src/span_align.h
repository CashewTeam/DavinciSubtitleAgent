#pragma once

#include <cstdint>
#include <string>
#include <unordered_map>
#include <vector>

struct SegmentStr {
  std::string label;
  int64_t start = 0;  // inclusive
  int64_t end = 0;    // inclusive (match python merge_repeats output)
};

struct SegmentSpanStr {
  std::string label;
  int64_t start = 0;  // inclusive
  int64_t end = 0;    // exclusive
};

// Merge repeats on a token path (T) but map token ids to string labels.
std::vector<SegmentStr> merge_repeats_str(
    const std::vector<int64_t>& path,
    const std::unordered_map<int64_t, std::string>& idx_to_token);

// Replicate ctc_forced_aligner.get_spans(tokens, segments, blank_label_string)
std::vector<std::vector<SegmentSpanStr>> get_spans_str(
    const std::vector<std::string>& tokens_starred,
    const std::vector<SegmentStr>& segments,
    const std::string& blank_label);

