#pragma once

#include <cstdint>
#include <string>
#include <vector>

#include "span_align.h"

struct WordTimestamp {
  double start_sec = 0.0;
  double end_sec = 0.0;
  std::string text;
  float score = 0.0f;  // sum of frame log-probs over [start,end)
};

// Replicate ctc_forced_aligner.text_utils.postprocess_results
// - text_starred: parallel to tokens_starred, includes "<star>" and original chunks
// - spans: output of get_spans_str(tokens_starred, segments, "<blank>"), same length as tokens_starred
// - stride_ms: frame stride in ms (python uses ceil(stride) but effectively 20ms)
// - scores: per-frame log-prob for the chosen path token (length T)
std::vector<WordTimestamp> postprocess_results(
    const std::vector<std::string>& text_starred,
    const std::vector<std::vector<SegmentSpanStr>>& spans,
    int stride_ms,
    const std::vector<float>& scores);

