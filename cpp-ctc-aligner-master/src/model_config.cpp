#include "model_config.h"

#include <stdexcept>

namespace fs = std::filesystem;

std::string model_type_to_string(ModelType type) {
  switch (type) {
    case ModelType::MMS_300M:
      return "MMS-300M (Wav2Vec2-CTC, 31 tokens)";
    case ModelType::OMNILINGUAL_300M:
      return "Omnilingual-300M (FastConformer-CTC, 9812 tokens)";
    case ModelType::OMNILINGUAL_1B:
      return "Omnilingual-1B (FastConformer-CTC, 9812 tokens)";
    case ModelType::UNKNOWN:
    default:
      return "Unknown";
  }
}

ModelConfig detect_model_config(const std::filesystem::path& model_dir) {
  ModelConfig config;

  const fs::path vocab_json = model_dir / "vocab.json";
  const fs::path tokens_txt = model_dir / "tokens.txt";
  const fs::path model_onnx = model_dir / "model.onnx";
  const fs::path model_int8_onnx = model_dir / "model.int8.onnx";

  // Detect vocab file
  if (fs::exists(vocab_json)) {
    config.vocab_path = vocab_json;
    config.type = ModelType::MMS_300M;
    config.vocab_size = 31;  // MMS vocab: 26 letters + 5 special tokens
    config.requires_romanization = true;
    config.description = model_type_to_string(ModelType::MMS_300M);
  } else if (fs::exists(tokens_txt)) {
    config.vocab_path = tokens_txt;
    config.vocab_size = 9812;  // Omnilingual vocab
    config.requires_romanization = false;

    // Distinguish 300M vs 1B by model file size (if needed)
    // For now, default to 300M since it's the recommended variant
    config.type = ModelType::OMNILINGUAL_300M;
    config.description = model_type_to_string(ModelType::OMNILINGUAL_300M);
  } else {
    config.type = ModelType::UNKNOWN;
    config.description = "Unknown model type";
    throw std::runtime_error(
        "Cannot detect model type: no vocab.json or tokens.txt found in " +
        model_dir.string());
  }

  // Detect model file (prefer int8 for Omnilingual)
  if (fs::exists(model_int8_onnx)) {
    config.model_path = model_int8_onnx;
  } else if (fs::exists(model_onnx)) {
    config.model_path = model_onnx;
  } else {
    throw std::runtime_error(
        "No model file found in " + model_dir.string() +
        " (expected model.onnx or model.int8.onnx)");
  }

  return config;
}
