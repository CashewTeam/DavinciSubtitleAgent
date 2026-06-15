#pragma once

#include <filesystem>
#include <string>

struct CliArgs {
  std::filesystem::path audio;
  std::filesystem::path srt;
  std::filesystem::path output;
  std::filesystem::path model_dir;  // Python align.py expects a model directory
  std::filesystem::path json_input;
  std::filesystem::path json_output;
  std::filesystem::path pinyin_table;  // Optional: kanji-to-pinyin table for romanization

  std::string language = "eng";
  bool romanize = false;
  int batch_size = 4;
  int threads = 0;  // 0 means auto

  bool debug = false;
  std::filesystem::path debug_dir;
};

// Parse align.py-compatible flags.
// Returns true on success; on failure writes usage to stderr and returns false (and sets exit_code).
bool parse_cli_args(int argc, char** argv, CliArgs& out, int& exit_code);

void print_usage();
void print_version();

