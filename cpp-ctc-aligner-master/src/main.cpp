#include <onnxruntime_cxx_api.h>

#include <nlohmann/json.hpp>

#include <algorithm>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <numeric>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

namespace fs = std::filesystem;
#include "cli_args.h"
#include "emissions.h"
#include "forced_align.h"
#include "json_io.h"
#include "logger.h"
#include "model_config.h"
#include "postprocess.h"
#include "span_align.h"
#include "srt_io.h"
#include "text_preprocess.h"
#include "vocab.h"
#include "vocab_json.h"
#include "audio_decode.h"
#include "kanji_pinyin.h"
#include "stacktrace.h"
#include "crash_handler.h"
#include "utf8_utils.h"

// Emissions generation now lives in emissions.cpp; keep main minimal.

// ---------------------------------------------------------------------------
// Sub-batch alignment: handles CTC "targets too long" by recursive splitting
// ---------------------------------------------------------------------------
static void align_and_map_batch(
    std::vector<SrtSegment>& segs,
    const float* all_log_probs,  // full emissions buffer
    int64_t frame_off,           // first frame index for this batch
    int64_t frame_cnt,           // number of frames for this batch
    int64_t classes,
    int stride_ms,
    const Vocab& vocab,
    const PreprocessConfig& prep_config,
    const ModelConfig& model_config,
    Logger& log,
    int depth = 0);

// Forward declaration
static int run_alignment(int argc, char** argv);

int main(int argc, char** argv) {
  crash_handler::install();
  try {
    return run_alignment(argc, argv);
  } catch (const Ort::Exception& e) {
    std::cerr << "\n[ERROR] ONNX Runtime error: " << e.what() << "\n";
    std::cerr << stacktrace::capture_string(0) << "\n";
    return 1;
  } catch (const std::exception& e) {
    std::cerr << "\n[ERROR] " << e.what() << "\n";
    std::cerr << stacktrace::capture_string(0) << "\n";
    return 1;
  } catch (...) {
    std::cerr << "\n[ERROR] Unknown exception occurred\n";
    std::cerr << stacktrace::capture_string(0) << "\n";
    return 1;
  }
}

// ---------------------------------------------------------------------------
// align_and_map_batch implementation
// ---------------------------------------------------------------------------
static void align_and_map_batch(
    std::vector<SrtSegment>& segs,
    const float* all_log_probs,
    int64_t frame_off,
    int64_t frame_cnt,
    int64_t classes,
    int stride_ms,
    const Vocab& vocab,
    const PreprocessConfig& prep_config,
    const ModelConfig& model_config,
    Logger& log,
    int depth) {
  if (segs.empty() || frame_cnt <= 0) return;

  // 1. Build full_text from this batch's segments
  std::string full_text;
  for (size_t i = 0; i < segs.size(); ++i) {
    std::string seg_text = segs[i].text;
    for (char& ch : seg_text) { if (ch == '\n') ch = ' '; }
    while (!seg_text.empty() && std::isspace(static_cast<unsigned char>(seg_text.front()))) seg_text.erase(seg_text.begin());
    while (!seg_text.empty() && std::isspace(static_cast<unsigned char>(seg_text.back()))) seg_text.pop_back();
    if (i) full_text.push_back(' ');
    full_text += seg_text;
  }

  // 2. Preprocess and tokenize
  const auto prep = preprocess_text(full_text, vocab, prep_config);
  const auto& tokens_starred = prep.tokens_starred;
  const auto& text_starred = prep.text_starred;

  // 3. Build targets
  const int64_t star_id = vocab.star_id;
  std::vector<int64_t> targets;
  targets.reserve(2000);
  std::string joined;
  for (const auto& t : tokens_starred) {
    if (!joined.empty()) joined.push_back(' ');
    joined += t;
  }
  size_t pos = 0;
  while (pos < joined.size()) {
    size_t next = joined.find(' ', pos);
    if (next == std::string::npos) next = joined.size();
    const auto piece = joined.substr(pos, next - pos);
    if (!piece.empty()) {
      if (piece == "<star>") {
        targets.push_back(star_id);
      } else {
        auto it = vocab.token_to_id.find(piece);
        if (it != vocab.token_to_id.end()) targets.push_back(it->second);
      }
    }
    pos = next + 1;
  }

  // 4. Check CTC constraint: T >= L + R
  const int64_t T = frame_cnt;
  const int64_t L = int64_t(targets.size());
  int64_t R = 0;
  for (int64_t i = 1; i < L; ++i) {
    if (targets[i] == targets[i - 1]) ++R;
  }

  if (T < L + R) {
    // Need to split — can't fit all targets in available frames
    if (segs.size() <= 1 || frame_cnt < 2) {
      // Can't split further — skip alignment, keep original timestamps
      log.info("[sub-batch] Cannot split further for CTC, skipping alignment");
      return;
    }

    const size_t mid = segs.size() / 2;

    // Determine frame split point from segment timestamps
    const double t_end_first = segs[mid - 1].end_sec;
    const double t_start_second = segs[mid].start_sec;
    const double split_time = (t_end_first + t_start_second) / 2.0;
    int64_t split_frame = static_cast<int64_t>(split_time * 1000.0 / stride_ms) - frame_off;
    split_frame = std::max<int64_t>(1, std::min<int64_t>(split_frame, frame_cnt - 1));

    {
      std::ostringstream ss;
      ss << "[sub-batch depth=" << depth << "] Splitting " << segs.size()
         << " segments (T=" << T << " < L+R=" << (L + R)
         << ") at seg " << mid << ", frame " << split_frame;
      log.info(ss.str());
    }

    std::vector<SrtSegment> first_half(segs.begin(), segs.begin() + mid);
    std::vector<SrtSegment> second_half(segs.begin() + mid, segs.end());

    align_and_map_batch(first_half, all_log_probs, frame_off, split_frame,
                        classes, stride_ms, vocab, prep_config, model_config, log, depth + 1);
    align_and_map_batch(second_half, all_log_probs, frame_off + split_frame,
                        frame_cnt - split_frame, classes, stride_ms, vocab, prep_config,
                        model_config, log, depth + 1);

    // Merge results back
    for (size_t i = 0; i < mid; ++i) segs[i] = first_half[i];
    for (size_t i = 0; i < second_half.size(); ++i) segs[mid + i] = second_half[i];
    return;
  }

  // 5. Run forced alignment on the emission slice
  const float* slice_ptr = all_log_probs + frame_off * classes;
  std::vector<int64_t> path;
  std::vector<float> scores;
  forced_align(slice_ptr, T, classes, targets.data(), L, /*blank=*/0, path, scores);

  // 6. Post-process: merge repeats → spans → word timestamps
  std::unordered_map<int64_t, std::string> idx_to_token;
  for (const auto& kv : vocab.token_to_id) idx_to_token[kv.second] = kv.first;
  idx_to_token[star_id] = "<star>";

  const auto merged = merge_repeats_str(path, idx_to_token);
  const std::string blank_token = (model_config.type == ModelType::MMS_300M) ? "<blank>" : "<s>";
  const auto spans = get_spans_str(tokens_starred, merged, blank_token);
  auto word_ts = postprocess_results(text_starred, spans, stride_ms, scores);

  // Apply time offset for this slice
  const double time_offset = double(frame_off) * double(stride_ms) / 1000.0;
  for (auto& w : word_ts) {
    w.start_sec += time_offset;
    w.end_sec += time_offset;
  }

  // 7. Map word timestamps back to SRT segments
  const float log_vocab = std::log(static_cast<float>(vocab.vocab_size()));
  size_t char_idx = 0;
  for (auto& seg : segs) {
    std::string seg_text = seg.text;
    for (char& ch : seg_text) { if (ch == '\n') ch = ' '; }
    while (!seg_text.empty() && std::isspace(static_cast<unsigned char>(seg_text.front()))) seg_text.erase(seg_text.begin());
    while (!seg_text.empty() && std::isspace(static_cast<unsigned char>(seg_text.back()))) seg_text.pop_back();

    const size_t num_chars = utf8::codepoint_count(seg_text);
    if (num_chars == 0 || char_idx >= word_ts.size()) continue;

    if (char_idx > 0 && char_idx < word_ts.size()) {
      std::string t = word_ts[char_idx].text;
      size_t l = 0;
      while (l < t.size() && std::isspace(static_cast<unsigned char>(t[l]))) l++;
      size_t r2 = t.size();
      while (r2 > l && std::isspace(static_cast<unsigned char>(t[r2 - 1]))) r2--;
      if (r2 <= l) char_idx += 1;
    }
    if (char_idx >= word_ts.size()) continue;

    const size_t start_idx = char_idx;
    seg.start_sec = word_ts[char_idx].start_sec;
    const size_t end_idx = std::min(char_idx + num_chars - 1, word_ts.size() - 1);
    seg.end_sec = word_ts[end_idx].end_sec;

    // Confidence score
    auto has_content_char = [&vocab](const std::string& s) {
      const auto chars = utf8::split_chars(s);
      for (const auto& ch : chars) {
        if (vocab.token_to_id.count(ch)) return true;
        if (ch.size() == 1 && ch[0] >= 'A' && ch[0] <= 'Z') {
          std::string lower(1, static_cast<char>(ch[0] - 'A' + 'a'));
          if (vocab.token_to_id.count(lower)) return true;
        }
      }
      for (const auto& ch : chars) {
        if (ch.size() == 1) {
          char c = ch[0];
          if ((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9')) return true;
          continue;
        }
        uint32_t cp = utf8::to_codepoint(std::string_view(ch.data(), ch.size()));
        if ((cp >= 0x2000 && cp <= 0x206F) || (cp >= 0x3000 && cp <= 0x303F) ||
            (cp >= 0xFE30 && cp <= 0xFE6F) || (cp >= 0xFF01 && cp <= 0xFF0F) ||
            (cp >= 0xFF1A && cp <= 0xFF20) || (cp >= 0xFF3B && cp <= 0xFF40) ||
            (cp >= 0xFF5B && cp <= 0xFF65))
          continue;
        return true;
      }
      return false;
    };
    std::vector<float> token_probs;
    token_probs.reserve(end_idx - start_idx + 1);
    for (size_t wi = start_idx; wi <= end_idx && wi < word_ts.size(); ++wi) {
      const auto& wt = word_ts[wi];
      if (!has_content_char(wt.text)) continue;
      float tlp = wt.score;
      if (tlp >= 0.0f) { token_probs.push_back(0.0f); continue; }
      float dur = static_cast<float>(wt.end_sec - wt.start_sec);
      int nf = std::max(1, static_cast<int>(dur / 0.02f));
      float avg = tlp / static_cast<float>(nf);
      token_probs.push_back(std::max(0.0f, std::min(1.0f, 1.0f + avg / log_vocab)));
    }
    if (!token_probs.empty()) {
      float sum = 0.0f;
      for (float p : token_probs) sum += p;
      seg.score = sum / static_cast<float>(token_probs.size());
    } else {
      seg.score = 0.0f;
    }
    char_idx = end_idx + 1;
  }
}

static int run_alignment(int argc, char** argv) {
  CliArgs args;
  int exit_code = 0;
  if (!parse_cli_args(argc, argv, args, exit_code)) {
    return exit_code;
  }

  Logger log;
  log.set_debug(args.debug);
  if (args.debug && !args.debug_dir.empty()) {
    std::error_code ec;
    fs::create_directories(args.debug_dir, ec);
    log.enable_file(args.debug_dir / "alignment.log");
  }

  const fs::path wav_path = args.audio;
  const std::string language = args.language;
  const int batch_size = args.batch_size;

  // Detect model type and configuration
  const auto model_config = detect_model_config(args.model_dir);
  log.info(std::string("Detected model: ") + model_config.description);

  // Determine if romanization is needed
  // - MMS models require romanization for CJK languages
  // - Omnilingual models do NOT need romanization (native CJK support)
  const bool romanize = model_config.requires_romanization && args.romanize;

  // Load kanji pinyin table only if using romanization (MMS model)
  if (romanize) {
    const fs::path& pinyin_table_path = args.pinyin_table;
    log.info(std::string("Loading kanji pinyin table from: ") + pinyin_table_path.string());
    if (!kanji::load_pinyin_table(pinyin_table_path.string())) {
      throw std::runtime_error("Failed to load kanji pinyin table from: " + pinyin_table_path.string());
    }
    log.info("Kanji pinyin table loaded successfully");
  }

  const auto audio_samples = decode_audio_to_16k_mono(wav_path);
  {
    std::ostringstream ss;
    ss << "Loaded audio: " << audio_samples.size() << " samples (" << (audio_samples.size() / 16000.0) << " seconds)";
    log.info(ss.str());
  }
  Ort::Env env(ORT_LOGGING_LEVEL_WARNING, "cpp-ort-aligner");
  Ort::SessionOptions opts;
  int num_threads = args.threads;
  if (num_threads <= 0) {
    num_threads = static_cast<int>(std::thread::hardware_concurrency());
    if (num_threads <= 0) num_threads = 4;
    num_threads = std::max(4, (num_threads + 1) / 2);
  }
  opts.SetIntraOpNumThreads(num_threads);
  opts.SetInterOpNumThreads(1);  // Keep inter-op at 1 for better cache locality
  opts.SetGraphOptimizationLevel(GraphOptimizationLevel::ORT_ENABLE_ALL);
  {
    std::ostringstream ss;
    ss << "ORT threads: " << num_threads << ", graph optimization: ALL";
    log.info(ss.str());
  }

  // Use model path from config (supports both model.onnx and model.int8.onnx)
  const fs::path& model_onnx = model_config.model_path;
#ifdef _WIN32
  Ort::Session session(env, model_onnx.wstring().c_str(), opts);
#else
  Ort::Session session(env, model_onnx.string().c_str(), opts);
#endif

  auto emissions = generate_emissions_ort(
      session,
      audio_samples,
      /*window_seconds=*/30,
      /*context_seconds=*/2,
      /*batch_size=*/batch_size,
      /*star_logp=*/0.0f);

  {
    std::ostringstream ss;
    ss << "emissions shape: [" << emissions.frames << "," << emissions.classes << "] stride_ms=" << emissions.stride_ms;
    log.info(ss.str());
  }

  std::vector<SrtSegment> srt_segments;

  // Read segments from JSON or SRT input
  if (!args.json_input.empty()) {
    if (args.json_input.string() == "-") {
      // Read from stdin
      std::ostringstream ss;
      ss << std::cin.rdbuf();
      srt_segments = parse_json_input(ss.str());
    } else {
      srt_segments = read_json_input(args.json_input);
    }
    {
      std::ostringstream ss;
      ss << "Read " << srt_segments.size() << " segments from JSON input";
      log.info(ss.str());
    }
  } else {
    srt_segments = read_srt_utf8(args.srt);
  }
  const std::vector<SrtSegment> original_segments_for_debug = args.debug ? srt_segments : std::vector<SrtSegment>{};

  // Load vocab
  const auto vocab = load_vocab(args.model_dir);
  {
    std::ostringstream ss;
    ss << "Loaded vocab: " << vocab.vocab_size() << " tokens (format: "
       << (vocab.format == VocabFormat::JSON ? "JSON" : "TXT") << ")";
    log.info(ss.str());
  }
  if (vocab.star_id != emissions.classes - 1) {
    throw std::runtime_error(
        "vocab size mismatch: emissions classes=" + std::to_string(emissions.classes) + ", vocab+star=" +
        std::to_string(vocab.star_id + 1) + " (check matching model + vocab file)");
  }

  // Run alignment with automatic sub-batching for CTC constraint violations
  PreprocessConfig prep_config;
  prep_config.romanize = romanize;
  prep_config.language = language;

  try {
    align_and_map_batch(srt_segments, emissions.log_probs.data(), 0, emissions.frames,
                        emissions.classes, emissions.stride_ms, vocab, prep_config, model_config, log);

    // Write output in JSON or SRT format
    if (!args.json_output.empty()) {
      if (args.json_output.string() == "-") {
        std::cout << format_json_output(srt_segments, 0.0);
      } else {
        write_json_output(args.json_output, srt_segments, 0.0);
        log.info(std::string("Wrote aligned JSON: ") + args.json_output.string());
      }
    } else {
      write_srt_utf8(args.output, srt_segments);
      log.info(std::string("Wrote aligned SRT: ") + args.output.string());
    }

    if (args.debug && !args.debug_dir.empty()) {
      fs::create_directories(args.debug_dir);
      using json = nlohmann::json;

      // 01_original_segments.json
      {
        json j = json::array();
        for (size_t i = 0; i < original_segments_for_debug.size(); ++i) {
          const auto& seg = original_segments_for_debug[i];
          j.push_back({{"index", i + 1}, {"start", seg.start_sec}, {"end", seg.end_sec},
                        {"text", seg.text}, {"score", seg.score}});
        }
        std::ofstream f(args.debug_dir / "01_original_segments.json", std::ios::binary);
        f << j.dump(2) << "\n";
      }
      // 06_aligned_segments.json
      {
        json j = json::array();
        for (size_t i = 0; i < srt_segments.size(); ++i) {
          const auto& seg = srt_segments[i];
          j.push_back({{"index", i + 1}, {"start", seg.start_sec}, {"end", seg.end_sec},
                        {"text", seg.text}, {"score", seg.score}});
        }
        std::ofstream f(args.debug_dir / "06_aligned_segments.json", std::ios::binary);
        f << j.dump(2) << "\n";
      }
      // 00_summary.json
      {
        json j = {
          {"audio_path", args.audio.string()},
          {"srt_path", args.srt.string()},
          {"language", language},
          {"romanize", romanize},
          {"audio_duration", audio_samples.size() / 16000.0},
          {"num_segments", srt_segments.size()},
          {"processing_time", 0.0}
        };
        std::ofstream f(args.debug_dir / "00_summary.json", std::ios::binary);
        f << j.dump(2) << "\n";
      }
    }
  } catch (const std::exception& e) {
    log.error(std::string("Alignment failed: ") + e.what());
    throw;
  }

  return 0;
}
