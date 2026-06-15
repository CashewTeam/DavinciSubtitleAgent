#include "emissions.h"

#include <algorithm>
#include <cmath>
#include <chrono>
#include <numeric>
#include <stdexcept>
#include <iostream>

static void log_softmax_row_into(const float* row, size_t n, float* out) {
  float m = row[0];
  for (size_t i = 1; i < n; ++i) m = std::max(m, row[i]);
  double sum = 0.0;
  for (size_t i = 0; i < n; ++i) sum += std::exp(double(row[i] - m));
  const float lse = float(double(m) + std::log(sum));
  for (size_t i = 0; i < n; ++i) out[i] = row[i] - lse;
}

static int time_to_frame(float seconds) {
  const int stride_msec = 20;
  const float frames_per_sec = 1000.0f / float(stride_msec);
  return int(seconds * frames_per_sec);
}

Emissions generate_emissions_ort(
    Ort::Session& session,
    const std::vector<float>& waveform_16k_mono,
    int window_seconds,
    int context_seconds,
    int batch_size,
    float star_logp) {
  const bool profile = std::getenv("CPP_ORT_ALIGNER_PROFILE") != nullptr;
  const auto t0 = std::chrono::steady_clock::now();
  auto t_last = t0;
  auto mark = [&](const char* label) {
    if (!profile) return;
    const auto now = std::chrono::steady_clock::now();
    const auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(now - t_last).count();
    const auto total = std::chrono::duration_cast<std::chrono::milliseconds>(now - t0).count();
    std::cerr << "[profile] " << label << ": +" << ms << "ms (total " << total << "ms)\n";
    t_last = now;
  };

  if (batch_size < 1) batch_size = 1;
  const int sample_rate = 16000;
  const int window = window_seconds * sample_rate;
  const int context = context_seconds * sample_rate;

  std::vector<std::vector<float>> chunks;
  int extension = 0;
  int used_context = 0;

  if (int(waveform_16k_mono.size()) < window) {
    used_context = 0;
    extension = 0;
    chunks.push_back(waveform_16k_mono);
  } else {
    used_context = context;
    const int t = int(waveform_16k_mono.size());
    const int nwin = int(std::ceil(double(t) / double(window)));
    extension = nwin * window - t;

    std::vector<float> padded;
    padded.reserve(size_t(used_context + t + used_context + extension));
    padded.insert(padded.end(), size_t(used_context), 0.0f);
    padded.insert(padded.end(), waveform_16k_mono.begin(), waveform_16k_mono.end());
    padded.insert(padded.end(), size_t(used_context + extension), 0.0f);

    const int chunk_samples = window + 2 * used_context;
    const int stride = window;
    const int num_chunks = (int(padded.size()) - chunk_samples) / stride + 1;
    chunks.reserve(size_t(num_chunks));
    for (int i = 0; i < num_chunks; ++i) {
      const int start = i * stride;
      chunks.emplace_back(padded.begin() + start, padded.begin() + start + chunk_samples);
    }
  }
  mark("chunking");

  // ORT names
  Ort::AllocatorWithDefaultOptions allocator;
  auto input_name = session.GetInputNameAllocated(0, allocator);
  auto output_name = session.GetOutputNameAllocated(0, allocator);
  const char* input_names[] = {input_name.get()};
  const char* output_names[] = {output_name.get()};

  Ort::MemoryInfo mem = Ort::MemoryInfo::CreateCpu(OrtArenaAllocator, OrtMemTypeDefault);

  std::vector<std::vector<float>> logits_chunks;  // each: frames x 31 (row-major)
  int64_t classes = -1;

  if (profile) {
    std::cerr << "[profile] chunks=" << chunks.size() << " window_s=" << window_seconds << " context_s=" << context_seconds
              << " batch_size=" << batch_size << "\n";
  }

  for (size_t i = 0; i < chunks.size(); i += size_t(batch_size)) {
    const size_t end = std::min(chunks.size(), i + size_t(batch_size));
    // Process each chunk separately for simplicity (batch_size currently only affects loop chunking).
    for (size_t j = i; j < end; ++j) {
      auto& x = chunks[j];
      std::vector<int64_t> input_shape{1, int64_t(x.size())};
      Ort::Value input_tensor = Ort::Value::CreateTensor<float>(
          mem, x.data(), x.size(), input_shape.data(), input_shape.size());
      auto outputs = session.Run(Ort::RunOptions{nullptr}, input_names, &input_tensor, 1, output_names, 1);
      if (outputs.empty()) throw std::runtime_error("ORT returned no outputs");

      auto& out0 = outputs[0];
      auto ti = out0.GetTensorTypeAndShapeInfo();
      auto shape = ti.GetShape();  // [1, frames, 31]
      if (shape.size() != 3) throw std::runtime_error("Unexpected logits rank");
      const int64_t frames = shape[1];
      const int64_t c = shape[2];
      if (classes < 0) classes = c;
      if (classes != c) throw std::runtime_error("Inconsistent class dim across chunks");

      const float* logits = out0.GetTensorData<float>();
      logits_chunks.emplace_back(logits, logits + size_t(frames * c));
    }
  }
  mark("ort_run+copy_logits");

  if (classes <= 0) throw std::runtime_error("No logits produced");

  // Remove context frames per chunk and flatten.
  const int cf = used_context > 0 ? time_to_frame(float(context_seconds)) : 0;
  // We can compute total frames after trimming without materializing trimmed chunks.
  int64_t total_frames = 0;
  {
    for (const auto& chunk_logits : logits_chunks) {
      const int64_t frames = int64_t(chunk_logits.size()) / classes;
      int64_t start = 0;
      int64_t stop = frames;
      if (cf > 0) {
        start = cf;
        stop = frames - cf + 1;  // python: -cf + 1
        if (stop < start) stop = start;
      }
      total_frames += (stop - start);
    }
  }

  std::vector<float> flat_logits;
  flat_logits.reserve(size_t(total_frames * classes));
  for (const auto& chunk_logits : logits_chunks) {
    const int64_t frames = int64_t(chunk_logits.size()) / classes;
    int64_t start = 0;
    int64_t stop = frames;
    if (cf > 0) {
      start = cf;
      stop = frames - cf + 1;  // python: -cf + 1
      if (stop < start) stop = start;
    }
    for (int64_t t = start; t < stop; ++t) {
      const float* row = chunk_logits.data() + size_t(t * classes);
      flat_logits.insert(flat_logits.end(), row, row + classes);
    }
  }
  mark("trim+flatten");

  // Remove extension frames.
  const int ext_frames = extension > 0 ? time_to_frame(float(extension) / float(sample_rate)) : 0;
  if (ext_frames > 0) {
    const int64_t keep_frames = total_frames - ext_frames;
    if (keep_frames > 0) {
      flat_logits.resize(size_t(keep_frames * classes));
      total_frames = keep_frames;
    }
  }
  mark("remove_extension");

  // log_softmax + append star.
  const int64_t classes_with_star = classes + 1;
  std::vector<float> log_probs;
  log_probs.resize(size_t(total_frames * classes_with_star));
  float* outp = log_probs.data();
  for (int64_t t = 0; t < total_frames; ++t) {
    const float* row = flat_logits.data() + size_t(t * classes);
    log_softmax_row_into(row, size_t(classes), outp);
    outp += classes;
    *outp++ = star_logp;
  }
  mark("log_softmax+star");

  Emissions out;
  out.frames = total_frames;
  out.classes = classes_with_star;
  out.log_probs = std::move(log_probs);
  out.stride_ms = 20;
  mark("done");
  return out;
}
