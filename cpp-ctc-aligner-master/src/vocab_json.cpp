#include "vocab_json.h"
#include "vocab.h"

#include <fstream>
#include <sstream>
#include <stdexcept>

// Legacy API implementation - delegates to new unified vocab loader
Vocab load_vocab_json_with_star(const std::filesystem::path& vocab_json_path) {
  return load_vocab_json(vocab_json_path);
}

