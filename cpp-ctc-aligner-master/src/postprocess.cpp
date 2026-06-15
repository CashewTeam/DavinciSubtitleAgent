#include "postprocess.h"

#include <algorithm>
#include <stdexcept>

std::vector<WordTimestamp> postprocess_results(
    const std::vector<std::string>& text_starred,
    const std::vector<std::vector<SegmentSpanStr>>& spans,
    int stride_ms,
    const std::vector<float>& scores) {
  if (text_starred.size() != spans.size()) {
    throw std::runtime_error("text_starred and spans length mismatch");
  }
  if (stride_ms <= 0) throw std::runtime_error("invalid stride_ms");

  std::vector<WordTimestamp> results;
  results.reserve(text_starred.size());

  for (size_t i = 0; i < text_starred.size(); ++i) {
    const auto& t = text_starred[i];
    if (t == "<star>") continue;
    const auto& span = spans[i];
    if (span.empty()) continue;

    const int64_t seg_start_idx = span.front().start;
    const int64_t seg_end_idx_incl = span.back().end;  // inclusive
    if (seg_start_idx < 0 || seg_end_idx_incl < 0) continue;

    WordTimestamp w;
    w.start_sec = double(seg_start_idx) * double(stride_ms) / 1000.0;
    w.end_sec = double(seg_end_idx_incl) * double(stride_ms) / 1000.0;
    w.text = t;

    // Python: score = scores[seg_start_idx:seg_end_idx].sum()
    float sum = 0.0f;
    // Python uses slice [start:end] where end is inclusive in Segment, but Python slice is exclusive,
    // so it's effectively [start, end).
    const int64_t end_excl = std::min<int64_t>(seg_end_idx_incl + 1, int64_t(scores.size()));
    for (int64_t j = std::max<int64_t>(0, seg_start_idx); j < end_excl; ++j) {
      sum += scores[size_t(j)];
    }
    w.score = sum;

    results.push_back(std::move(w));
  }

  return results;
}
