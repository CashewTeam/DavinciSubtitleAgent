#pragma once

#include <cstdint>
#include <filesystem>
#include <string>
#include <unordered_map>

enum class VocabFormat { JSON, TXT };

struct Vocab {
  std::unordered_map<std::string, int64_t> token_to_id;
  std::unordered_map<int64_t, std::string> id_to_token;
  int64_t blank_id = 0;
  int64_t star_id = -1;  // Dynamically appended <star> token (torchaudio style)
  VocabFormat format = VocabFormat::JSON;

  size_t vocab_size() const { return token_to_id.size(); }
};

// Auto-detect format and load vocab from model directory.
// Looks for vocab.json (MMS) or tokens.txt (Omnilingual).
Vocab load_vocab(const std::filesystem::path& model_dir);

// Explicitly load JSON format (MMS-style vocab.json)
Vocab load_vocab_json(const std::filesystem::path& vocab_json_path);

// Explicitly load TXT format (Omnilingual-style tokens.txt, line number = token ID)
Vocab load_vocab_txt(const std::filesystem::path& tokens_txt_path);
