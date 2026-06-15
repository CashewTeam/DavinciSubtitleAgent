#pragma once

#include <cstdint>
#include <string>
#include <unordered_map>
#include <vector>

#include "forced_align.h"

// Span segment uses half-open interval [start, end) like Python Segment in ctc_forced_aligner.
struct SpanSegment {
  int64_t label = -1;
  int64_t start = 0;  // inclusive
  int64_t end = 0;    // exclusive
};

// Convert merge_repeats (inclusive end) to half-open segments.
std::vector<SpanSegment> to_half_open(const std::vector<Segment>& segments_inclusive);

// Replicate ctc_forced_aligner.get_spans(tokens, segments, blank_label_string)
std::vector<std::vector<SpanSegment>> get_spans(
    const std::vector<std::string>& tokens,                // tokens_starred (romanized pieces like "r e")
    const std::vector<SpanSegment>& segments,              // merged segments in label-string space
    const std::string& blank_label);

