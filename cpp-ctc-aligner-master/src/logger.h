#pragma once

#include <filesystem>
#include <fstream>
#include <iostream>
#include <string>

class Logger {
 public:
  enum class Level { Debug, Info, Warn, Error };

  Logger() = default;

  void enable_file(const std::filesystem::path& path) {
    file_.open(path, std::ios::binary | std::ios::trunc);
  }

  void set_debug(bool enabled) { debug_enabled_ = enabled; }

  void log(Level level, const std::string& msg) {
    if (level == Level::Debug && !debug_enabled_) return;
    const std::string line = format(level, msg);
    std::cerr << line;
    if (file_.is_open()) file_ << line;
  }

  void info(const std::string& msg) { log(Level::Info, msg); }
  void warn(const std::string& msg) { log(Level::Warn, msg); }
  void error(const std::string& msg) { log(Level::Error, msg); }
  void debug(const std::string& msg) { log(Level::Debug, msg); }

 private:
  static const char* level_tag(Level l) {
    switch (l) {
      case Level::Debug:
        return "DEBUG";
      case Level::Info:
        return "INFO";
      case Level::Warn:
        return "WARN";
      case Level::Error:
        return "ERROR";
    }
    return "INFO";
  }

  static std::string format(Level l, const std::string& msg) {
    // Keep it simple: align.py uses timestamps; we omit time for now but keep [LEVEL] prefix.
    std::string out;
    out.reserve(msg.size() + 16);
    out += "[";
    out += level_tag(l);
    out += "] ";
    out += msg;
    if (out.empty() || out.back() != '\n') out.push_back('\n');
    return out;
  }

  bool debug_enabled_ = false;
  std::ofstream file_;
};

