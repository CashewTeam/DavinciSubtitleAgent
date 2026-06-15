#include "span_align.h"

#include <algorithm>
#include <cmath>
#include <sstream>
#include <stdexcept>

static std::vector<std::string> split_spaces(const std::string& s) {
  std::vector<std::string> out;
  size_t i = 0;
  while (i <= s.size()) {
    size_t j = s.find(' ', i);
    if (j == std::string::npos) j = s.size();
    out.push_back(s.substr(i, j - i));
    i = j + 1;
    if (j == s.size()) break;
  }
  // Python's split(" ") keeps empties; our loop does too.
  return out;
}

static std::string debug_printable(const std::string& s) {
  std::string out;
  out.reserve(s.size() + 8);
  out.push_back('\'');
  for (unsigned char c : s) {
    if (c == '\n') {
      out += "\\n";
    } else if (c == '\r') {
      out += "\\r";
    } else if (c == '\t') {
      out += "\\t";
    } else if (c == '\'') {
      out += "\\'";
    } else if (c < 32 || c == 127) {
      char buf[8];
      std::snprintf(buf, sizeof(buf), "\\x%02X", unsigned(c));
      out += buf;
    } else {
      out.push_back(char(c));
    }
  }
  out.push_back('\'');
  return out;
}

std::vector<SegmentStr> merge_repeats_str(
    const std::vector<int64_t>& path,
    const std::unordered_map<int64_t, std::string>& idx_to_token) {
  std::vector<SegmentStr> segs;
  if (path.empty()) return segs;
  int64_t i1 = 0;
  while (i1 < int64_t(path.size())) {
    int64_t i2 = i1;
    while (i2 < int64_t(path.size()) && path[size_t(i2)] == path[size_t(i1)]) ++i2;
    SegmentStr s;
    const int64_t lbl = path[size_t(i1)];
    auto it = idx_to_token.find(lbl);
    s.label = (it != idx_to_token.end()) ? it->second : std::to_string(lbl);
    s.start = i1;
    s.end = i2 - 1;
    segs.push_back(std::move(s));
    i1 = i2;
  }
  return segs;
}

std::vector<std::vector<SegmentSpanStr>> get_spans_str(
    const std::vector<std::string>& tokens,
    const std::vector<SegmentStr>& segments,
    const std::string& blank) {
  int64_t ltr_idx = 0;
  int64_t tokens_idx = 0;
  std::vector<std::pair<int64_t, int64_t>> intervals;
  int64_t start = 0;

  for (int64_t seg_idx = 0; seg_idx < int64_t(segments.size()); ++seg_idx) {
    const auto& seg = segments[size_t(seg_idx)];

    if (tokens_idx == int64_t(tokens.size())) {
      // Python asserts this is last blank; ignore.
      continue;
    }

    const auto cur_token = split_spaces(tokens[size_t(tokens_idx)]);
    const std::string ltr = cur_token[size_t(ltr_idx)];

    if (seg.label == blank) {
      continue;
    }

    // Python: assert seg.label == ltr
    if (seg.label != ltr) {
      std::ostringstream oss;
      oss << "get_spans mismatch: seg.label=" << debug_printable(seg.label)
          << " != ltr=" << debug_printable(ltr)
          << " (tokens_idx=" << tokens_idx << " ltr_idx=" << ltr_idx
          << " token=" << debug_printable(tokens[size_t(tokens_idx)]) << ")";
      throw std::runtime_error(oss.str());
    }

    if (ltr_idx == 0) {
      start = seg_idx;
    }

    if (ltr_idx == int64_t(cur_token.size()) - 1) {
      ltr_idx = 0;
      tokens_idx += 1;
      intervals.push_back({start, seg_idx});
      while (tokens_idx < int64_t(tokens.size()) && tokens[size_t(tokens_idx)].empty()) {
        intervals.push_back({seg_idx, seg_idx});
        tokens_idx += 1;
      }
    } else {
      ltr_idx += 1;
    }
  }

  std::vector<std::vector<SegmentSpanStr>> spans;
  spans.reserve(intervals.size());

  for (size_t idx = 0; idx < intervals.size(); ++idx) {
    const auto [start_idx, end_idx] = intervals[idx];

    std::vector<SegmentSpanStr> span;
    span.reserve(size_t(end_idx - start_idx + 1 + 2));

    for (int64_t si = start_idx; si <= end_idx; ++si) {
      SegmentSpanStr s;
      s.label = segments[size_t(si)].label;
      s.start = segments[size_t(si)].start;
      // IMPORTANT: ctc_forced_aligner's Segment.end is inclusive.
      // Their get_spans keeps Segment objects as-is (inclusive end), and postprocess_results
      // uses span[-1].end directly for both score slicing and time conversion.
      // So keep `end` inclusive here.
      s.end = segments[size_t(si)].end;
      span.push_back(std::move(s));
    }

    if (start_idx > 0) {
      const auto& prev = segments[size_t(start_idx - 1)];
      if (prev.label == blank) {
        const int64_t pad_start = (idx == 0) ? prev.start : int64_t((prev.start + prev.end) / 2);
        SegmentSpanStr pad;
        pad.label = blank;
        pad.start = pad_start;
        pad.end = span.front().start;
        span.insert(span.begin(), std::move(pad));
      }
    }

    if (end_idx + 1 < int64_t(segments.size())) {
      const auto& next = segments[size_t(end_idx + 1)];
      if (next.label == blank) {
        const int64_t pad_end =
            (idx == intervals.size() - 1) ? next.end + 1 : int64_t(std::floor((next.start + next.end) / 2.0));
        SegmentSpanStr pad;
        pad.label = blank;
        pad.start = span.back().end;
        pad.end = pad_end;
        span.push_back(std::move(pad));
      }
    }

    spans.push_back(std::move(span));
  }

  return spans;
}
