#pragma once

#include <cstdint>
#include <string>
#include <unordered_map>
#include <vector>

struct Segment {
  int64_t label = -1;
  int64_t start = 0;
  int64_t end = 0;  // inclusive end to match Python segment format used earlier
};

std::vector<Segment> merge_repeats(const std::vector<int64_t>& path);

// Viterbi forced alignment (torchaudio/flashlight-style).
// log_probs: T x C (row-major) with C including star column.
// targets: length L
// blank: blank token id
void forced_align(
    const float* log_probs,
    int64_t T,
    int64_t C,
    const int64_t* targets,
    int64_t L,
    int64_t blank,
    std::vector<int64_t>& out_path,
    std::vector<float>& out_scores);

