#pragma once

#include <vector>

#include <onnxruntime_cxx_api.h>

struct Emissions {
  // T x C (row-major). C includes appended star column.
  int64_t frames = 0;
  int64_t classes = 0;
  std::vector<float> log_probs;
  int stride_ms = 20;
};

// Replicate ctc_forced_aligner.generate_emissions(window=30, context=2, stride=20ms)
Emissions generate_emissions_ort(
    Ort::Session& session,
    const std::vector<float>& waveform_16k_mono,
    int window_seconds,
    int context_seconds,
    int batch_size,
    float star_logp);
