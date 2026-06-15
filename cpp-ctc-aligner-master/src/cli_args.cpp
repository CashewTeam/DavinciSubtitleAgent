#include "cli_args.h"
#include "version.h"

#include <algorithm>
#include <cstdlib>
#include <iostream>
#include <stdexcept>
#include <vector>

#ifdef _WIN32
#include <windows.h>
#elif defined(__APPLE__)
#include <mach-o/dyld.h>
#else
#include <unistd.h>
#include <limits.h>
#endif

namespace fs = std::filesystem;

static fs::path get_exe_dir() {
#ifdef _WIN32
  wchar_t path[MAX_PATH];
  GetModuleFileNameW(nullptr, path, MAX_PATH);
  return fs::path(path).parent_path();
#elif defined(__APPLE__)
  char path[PATH_MAX];
  uint32_t size = sizeof(path);
  if (_NSGetExecutablePath(path, &size) == 0) {
    return fs::canonical(path).parent_path();
  }
  return fs::current_path();
#else
  char path[PATH_MAX];
  ssize_t len = readlink("/proc/self/exe", path, sizeof(path) - 1);
  if (len != -1) {
    path[len] = '\0';
    return fs::path(path).parent_path();
  }
  return fs::current_path();
#endif
}

static bool is_flag(const std::string& s) { return !s.empty() && s[0] == '-'; }

void print_version() {
  std::cout << "cpp-ort-aligner " << PROJECT_VERSION << " (" << GIT_HASH << ")\n";
}

void print_usage() {
  std::cerr << "Usage:\n";
  std::cerr << "  cpp-ort-aligner --audio <path> --model <model_dir> [--srt <path> | --json-input <path|-}] [options]\n";
  std::cerr << "\nInput/Output:\n";
  std::cerr << "  --audio, -a           Audio file path\n";
  std::cerr << "  --model, -m           Local model directory (contains model.onnx + vocab.json)\n";
  std::cerr << "  --srt, -s             Input SRT file (required unless using --json-input)\n";
  std::cerr << "  --output, -o          Output SRT path (default: <input>_aligned.srt)\n";
  std::cerr << "  --json-input, -ji     JSON input path (use '-' for stdin)\n";
  std::cerr << "  --json-output, -jo    JSON output path (use '-' for stdout)\n";
  std::cerr << "\nAlignment options:\n";
  std::cerr << "  --language, -l        ISO 639-3 code (default: eng)\n";
  std::cerr << "  --romanize, -r        Enable romanization\n";
  std::cerr << "  --pinyin-table        Kanji-to-pinyin table path (default: <exe_dir>/Chinese_to_Pinyin.txt)\n";
  std::cerr << "  --batch-size, -b      Inference batch size (default: 4)\n";
  std::cerr << "  --threads             ORT intra-op threads (default: auto)\n";
  std::cerr << "\nDebug:\n";
  std::cerr << "  --debug, -d           Enable debug mode and save intermediate files\n";
  std::cerr << "  --debug-dir           Debug output directory (default: <base>_debug)\n";
  std::cerr << "\nOther:\n";
  std::cerr << "  --version, -v         Show version and exit\n";
}

static std::string require_value(int& i, int argc, char** argv, const std::string& flag) {
  if (i + 1 >= argc) throw std::runtime_error("Missing value for " + flag);
  return std::string(argv[++i]);
}

static fs::path default_debug_dir(const CliArgs& a) {
  if (!a.srt.empty()) {
    const auto base = a.srt.parent_path() / a.srt.stem();
    return fs::path(base.string() + "_debug");
  }
  // JSON mode: base on audio (match align.py)
  const auto base = a.audio.parent_path() / a.audio.stem();
  return fs::path(base.string() + "_debug");
}

static fs::path default_output_srt(const fs::path& input_srt) {
  const auto base = input_srt.parent_path() / input_srt.stem();
  return fs::path(base.string() + "_aligned.srt");
}

bool parse_cli_args(int argc, char** argv, CliArgs& out, int& exit_code) {
  exit_code = 0;
  if (argc <= 1) {
    print_usage();
    exit_code = 2;
    return false;
  }

  for (int i = 1; i < argc; ++i) {
    const std::string a = argv[i];
    if (a == "--version" || a == "-v") {
      print_version();
      exit_code = 0;
      return false;
    } else if (a == "--audio" || a == "-a") {
      out.audio = fs::path(require_value(i, argc, argv, a));
    } else if (a == "--model" || a == "-m") {
      out.model_dir = fs::path(require_value(i, argc, argv, a));
    } else if (a == "--srt" || a == "-s") {
      out.srt = fs::path(require_value(i, argc, argv, a));
    } else if (a == "--output" || a == "-o") {
      out.output = fs::path(require_value(i, argc, argv, a));
    } else if (a == "--language" || a == "-l") {
      out.language = require_value(i, argc, argv, a);
    } else if (a == "--romanize" || a == "-r") {
      out.romanize = true;
    } else if (a == "--pinyin-table") {
      out.pinyin_table = fs::path(require_value(i, argc, argv, a));
    } else if (a == "--batch-size" || a == "-b") {
      out.batch_size = std::stoi(require_value(i, argc, argv, a));
    } else if (a == "--threads") {
      out.threads = std::stoi(require_value(i, argc, argv, a));
    } else if (a == "--keep-wav") {
      // Python-only feature (ffmpeg conversion). No-op in C++ version for CLI compatibility.
    } else if (a == "--debug" || a == "-d") {
      out.debug = true;
    } else if (a == "--debug-dir") {
      out.debug_dir = fs::path(require_value(i, argc, argv, a));
    } else if (a == "--json-input" || a == "-ji") {
      out.json_input = fs::path(require_value(i, argc, argv, a));
    } else if (a == "--json-output" || a == "-jo") {
      out.json_output = fs::path(require_value(i, argc, argv, a));
    } else if (is_flag(a)) {
      std::cerr << "Unknown arg: " << a << "\n\n";
      print_usage();
      exit_code = 2;
      return false;
    } else {
      std::cerr << "Unexpected positional arg: " << a << "\n\n";
      print_usage();
      exit_code = 2;
      return false;
    }
  }

  // Validate required
  if (out.audio.empty()) {
    std::cerr << "ERROR: --audio is required\n\n";
    print_usage();
    exit_code = 2;
    return false;
  }
  if (out.model_dir.empty()) {
    std::cerr << "ERROR: --model is required\n\n";
    print_usage();
    exit_code = 2;
    return false;
  }

  const bool json_mode = !out.json_input.empty();
  if (!json_mode && out.srt.empty()) {
    std::cerr << "ERROR: Either --srt or --json-input is required\n\n";
    print_usage();
    exit_code = 2;
    return false;
  }

  if (out.batch_size < 1) out.batch_size = 1;

  if (out.output.empty() && !out.srt.empty()) {
    out.output = default_output_srt(out.srt);
  }

  if (out.debug && out.debug_dir.empty()) {
    out.debug_dir = default_debug_dir(out);
  }

  // Default pinyin table path: <exe_dir>/Chinese_to_Pinyin.txt
  if (out.pinyin_table.empty() && out.romanize) {
    out.pinyin_table = get_exe_dir() / "Chinese_to_Pinyin.txt";
  }

  return true;
}

