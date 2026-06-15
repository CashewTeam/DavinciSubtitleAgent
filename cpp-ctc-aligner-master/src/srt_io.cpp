#include "srt_io.h"

#include <fstream>
#include <regex>
#include <sstream>
#include <stdexcept>

static double parse_srt_time(const std::string& s) {
  // "00:00:05,440"
  int hh = 0, mm = 0, ss = 0, ms = 0;
  char c1, c2, c3;
  std::stringstream ssin(s);
  ssin >> hh >> c1 >> mm >> c2 >> ss >> c3 >> ms;
  if (!ssin || c1 != ':' || c2 != ':' || c3 != ',') return 0.0;
  return double(hh) * 3600.0 + double(mm) * 60.0 + double(ss) + double(ms) / 1000.0;
}

static std::string format_srt_time(double sec) {
  if (sec < 0) sec = 0;
  const int hh = int(sec / 3600.0);
  sec -= double(hh) * 3600.0;
  const int mm = int(sec / 60.0);
  sec -= double(mm) * 60.0;
  const int ss = int(sec);
  // Match Python align.py:format_srt_time: millis = int((seconds % 1) * 1000)
  // i.e. truncate rather than round.
  const int ms = int((sec - double(ss)) * 1000.0);
  char buf[32];
  std::snprintf(buf, sizeof(buf), "%02d:%02d:%02d,%03d", hh, mm, ss, ms);
  return std::string(buf);
}

std::vector<SrtSegment> read_srt_utf8(const std::filesystem::path& path) {
  std::ifstream f(path, std::ios::binary);
  if (!f) throw std::runtime_error("Failed to open " + path.string());
  std::string content((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>());

  // Handle UTF-8 BOM.
  if (content.size() >= 3 && (unsigned char)content[0] == 0xEF && (unsigned char)content[1] == 0xBB &&
      (unsigned char)content[2] == 0xBF) {
    content.erase(0, 3);
  }

  std::vector<SrtSegment> segs;
  std::stringstream ss(content);
  std::string line;
  std::regex idx_re(R"(^\d+$)");
  while (std::getline(ss, line)) {
    if (line.size() && line.back() == '\r') line.pop_back();
    if (!std::regex_match(line, idx_re)) continue;
    const int index = std::stoi(line);
    if (!std::getline(ss, line)) break;
    if (line.size() && line.back() == '\r') line.pop_back();
    const auto arrow = line.find("-->");
    if (arrow == std::string::npos) continue;
    const auto a = line.substr(0, arrow);
    const auto b = line.substr(arrow + 3);
    const double start = parse_srt_time(std::regex_replace(a, std::regex(R"(\s+)"), ""));
    const double end = parse_srt_time(std::regex_replace(b, std::regex(R"(\s+)"), ""));

    std::string text;
    bool first = true;
    std::regex score_re(R"(^\{score:\s*-?[\d.]+\}$)");
    while (std::getline(ss, line)) {
      if (line.size() && line.back() == '\r') line.pop_back();
      if (line.empty()) break;
      // Skip score lines from previous runs
      if (std::regex_match(line, score_re)) continue;
      if (!first) text.push_back('\n');
      first = false;
      text += line;
    }

    segs.push_back({index, start, end, text});
  }
  return segs;
}

void write_srt_utf8(const std::filesystem::path& path, const std::vector<SrtSegment>& segs) {
  std::ofstream f(path, std::ios::binary);
  if (!f) throw std::runtime_error("Failed to write " + path.string());
  for (size_t i = 0; i < segs.size(); ++i) {
    const auto& s = segs[i];
    f << (s.index ? s.index : int(i + 1)) << "\n";
    f << format_srt_time(s.start_sec) << " --> " << format_srt_time(s.end_sec) << "\n";
    f << s.text << "\n";
    // Output confidence score as a comment (score: X.XXX)
    char score_buf[32];
    std::snprintf(score_buf, sizeof(score_buf), "%.3f", s.score);
    f << "{score: " << score_buf << "}\n\n";
  }
}
