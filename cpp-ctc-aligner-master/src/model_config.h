#pragma once

#include <filesystem>
#include <string>

enum class ModelType {
  MMS_300M,         // vocab.json + 31 tokens (requires romanization for CJK)
  OMNILINGUAL_300M, // tokens.txt + 9,812 tokens (native CJK support)
  OMNILINGUAL_1B,   // tokens.txt + 9,812 tokens (larger model)
  UNKNOWN
};

struct ModelConfig {
  ModelType type = ModelType::UNKNOWN;
  std::filesystem::path model_path;  // model.onnx or model.int8.onnx
  std::filesystem::path vocab_path;  // vocab.json or tokens.txt
  int64_t vocab_size = 0;            // 31 (MMS) or 9812 (Omnilingual)
  bool requires_romanization = true; // MMS: true, Omnilingual: false
  std::string description;
};

// Auto-detect model type from model directory contents
ModelConfig detect_model_config(const std::filesystem::path& model_dir);

// Get human-readable model type name
std::string model_type_to_string(ModelType type);
