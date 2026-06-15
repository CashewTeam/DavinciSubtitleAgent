#pragma once

#include <string>
#include <unordered_map>
#include <vector>

#include "vocab.h"

struct PreprocessResult {
  std::vector<std::string> tokens_starred;
  std::vector<std::string> text_starred;
  std::string full_text;
};

struct PreprocessConfig {
  bool romanize = false;           // MMS requires romanization, Omnilingual does not
  bool normalize_english = true;   // Convert uppercase to lowercase
  bool filter_punctuation = true;  // Filter out punctuation
  std::string language;            // ISO 639-3 code (e.g. "jpn", "eng")
};

// Preprocess text for CTC alignment with vocab lookup.
// For Omnilingual models: UTF-8 character-level tokenization with direct vocab lookup.
// For MMS models: romanization + character-level tokenization.
PreprocessResult preprocess_text(
    const std::string& full_text,
    const Vocab& vocab,
    const PreprocessConfig& config);

// Legacy API for backward compatibility (MMS-style preprocessing)
// - full_text: already concatenated with single spaces between SRT segments
// - language: ISO 639-3 code (e.g. "jpn")
// - romanize: if true, use C++ romanization for CJK languages
PreprocessResult preprocess_text_cpp(const std::string& full_text, const std::string& language, bool romanize);
