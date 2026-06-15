#include "vocab.h"

#include <nlohmann/json.hpp>

#include <fstream>
#include <stdexcept>

Vocab load_vocab_json(const std::filesystem::path& vocab_json_path) {
  std::ifstream f(vocab_json_path, std::ios::binary);
  if (!f) throw std::runtime_error("Failed to open vocab.json: " + vocab_json_path.string());

  const auto j = nlohmann::json::parse(f);
  if (!j.is_object()) throw std::runtime_error("vocab.json must be a JSON object");

  Vocab v;
  v.format = VocabFormat::JSON;
  int64_t max_id = -1;

  for (const auto& [key, val] : j.items()) {
    const int64_t id = val.get<int64_t>();
    v.token_to_id[key] = id;
    v.id_to_token[id] = key;
    if (id > max_id) max_id = id;
  }

  // Append <star> as an extra label (torchaudio style)
  v.star_id = max_id + 1;
  v.token_to_id["<star>"] = v.star_id;
  v.id_to_token[v.star_id] = "<star>";
  v.blank_id = 0;  // MMS uses ID 0 for <blank>

  return v;
}

Vocab load_vocab_txt(const std::filesystem::path& tokens_txt_path) {
  Vocab v;
  v.format = VocabFormat::TXT;

  std::ifstream f(tokens_txt_path, std::ios::binary);
  if (!f) throw std::runtime_error("Failed to open tokens.txt: " + tokens_txt_path.string());

  std::string line;
  int64_t max_id = -1;

  while (std::getline(f, line)) {
    // Remove trailing CR/LF (handle both Unix and Windows line endings)
    while (!line.empty() && (line.back() == '\r' || line.back() == '\n')) {
      line.pop_back();
    }

    if (line.empty()) continue;

    // tokens.txt format: "token ID" (space-separated)
    // Find the last space to split token and ID
    size_t last_space = line.rfind(' ');
    if (last_space == std::string::npos || last_space == 0) {
      throw std::runtime_error("Invalid tokens.txt format: " + line);
    }

    std::string token = line.substr(0, last_space);
    int64_t id = std::stoll(line.substr(last_space + 1));

    v.token_to_id[token] = id;
    v.id_to_token[id] = token;
    if (id > max_id) max_id = id;
  }

  // Append <star> token (torchaudio style)
  v.star_id = max_id + 1;
  v.token_to_id["<star>"] = v.star_id;
  v.id_to_token[v.star_id] = "<star>";

  // blank is typically ID 0 (<s> token in Omnilingual, which serves as blank)
  v.blank_id = 0;

  return v;
}

Vocab load_vocab(const std::filesystem::path& model_dir) {
  namespace fs = std::filesystem;

  const fs::path vocab_json = model_dir / "vocab.json";
  const fs::path tokens_txt = model_dir / "tokens.txt";

  if (fs::exists(vocab_json)) {
    return load_vocab_json(vocab_json);
  }
  if (fs::exists(tokens_txt)) {
    return load_vocab_txt(tokens_txt);
  }

  throw std::runtime_error(
      "No vocab file found in model directory: " + model_dir.string() +
      " (expected vocab.json or tokens.txt)");
}
