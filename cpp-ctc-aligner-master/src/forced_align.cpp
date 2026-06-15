#include "forced_align.h"

#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>

std::vector<Segment> merge_repeats(const std::vector<int64_t>& path) {
  std::vector<Segment> segments;
  if (path.empty()) return segments;
  int64_t i1 = 0;
  while (i1 < int64_t(path.size())) {
    int64_t i2 = i1;
    while (i2 < int64_t(path.size()) && path[size_t(i2)] == path[size_t(i1)]) ++i2;
    Segment s;
    s.label = path[size_t(i1)];
    s.start = i1;
    s.end = i2 - 1;
    segments.push_back(s);
    i1 = i2;
  }
  return segments;
}

void forced_align(
    const float* log_probs,
    int64_t T,
    int64_t C,
    const int64_t* targets,
    int64_t L,
    int64_t blank,
    std::vector<int64_t>& out_path,
    std::vector<float>& out_scores) {
  if (T <= 0 || C <= 0) throw std::runtime_error("invalid log_probs shape");
  if (L <= 0) throw std::runtime_error("empty targets");
  const float neg_inf = -std::numeric_limits<float>::infinity();

  const int64_t S = 2 * L + 1;

  // Count repeats.
  int64_t R = 0;
  for (int64_t i = 1; i < L; ++i) {
    if (targets[i] == targets[i - 1]) ++R;
  }
  if (T < L + R) throw std::runtime_error("targets length is too long for CTC");

  std::vector<float> alphas(size_t(2 * S), neg_inf);
  std::vector<int8_t> back_ptr(size_t(T * S), int8_t(-1));

  int64_t start = (T - (L + R) > 0) ? 0 : 1;
  int64_t end = (S == 1) ? 1 : 2;
  for (int64_t i = start; i < end; ++i) {
    const int64_t label_idx = (i % 2 == 0) ? blank : targets[i / 2];
    alphas[size_t(i)] = log_probs[size_t(0 * C + label_idx)];
  }

  for (int64_t t = 1; t < T; ++t) {
    if (T - t <= L + R) {
      if ((start % 2 == 1) && (targets[start / 2] != targets[start / 2 + 1])) start = start + 1;
      start = start + 1;
    }
    if (t <= L + R) {
      if (end % 2 == 0 && end < 2 * L && (targets[end / 2 - 1] != targets[end / 2])) end = end + 1;
      end = end + 1;
    }

    const int64_t cur_off = t % 2;
    const int64_t prev_off = (t - 1) % 2;
    // reset
    for (int64_t j = 0; j < S; ++j) {
      alphas[size_t(cur_off * S + j)] = neg_inf;
    }

    int64_t startloop = start;
    if (start == 0) {
      alphas[size_t(cur_off * S)] = alphas[size_t(prev_off * S)] + log_probs[size_t(t * C + blank)];
      back_ptr[size_t(t * S)] = 0;
      startloop += 1;
    }

    for (int64_t i = startloop; i < end; ++i) {
      const float x0 = alphas[size_t(prev_off * S + i)];
      const float x1 = alphas[size_t(prev_off * S + i - 1)];
      float x2 = neg_inf;
      const int64_t label_idx = (i % 2 == 0) ? blank : targets[i / 2];
      if (i % 2 != 0 && i != 1 && (targets[i / 2] != targets[i / 2 - 1])) {
        x2 = alphas[size_t(prev_off * S + i - 2)];
      }
      float best = x0;
      int8_t bp = 0;
      if (x2 > x1 && x2 > x0) {
        best = x2;
        bp = 2;
      } else if (x1 > x0 && x1 > x2) {
        best = x1;
        bp = 1;
      }
      back_ptr[size_t(t * S + i)] = bp;
      alphas[size_t(cur_off * S + i)] = best + log_probs[size_t(t * C + label_idx)];
    }
  }

  const int64_t idx1 = (T - 1) % 2;
  int64_t ltr_idx =
      (alphas[size_t(idx1 * S + S - 1)] > alphas[size_t(idx1 * S + S - 2)]) ? (S - 1) : (S - 2);

  out_path.assign(size_t(T), blank);
  out_scores.assign(size_t(T), 0.0f);

  for (int64_t t = T - 1; t >= 0; --t) {
    const int64_t lbl_idx = (ltr_idx % 2 == 0) ? blank : targets[ltr_idx / 2];
    out_path[size_t(t)] = lbl_idx;
    out_scores[size_t(t)] = log_probs[size_t(t * C + lbl_idx)];
    const int8_t off = back_ptr[size_t(t * S + ltr_idx)];
    ltr_idx -= int64_t(off);
  }
}

