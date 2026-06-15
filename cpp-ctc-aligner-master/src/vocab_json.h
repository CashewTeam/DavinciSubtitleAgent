#pragma once

#include "vocab.h"

// Legacy API for backward compatibility
// Use load_vocab() from vocab.h instead for new code
Vocab load_vocab_json_with_star(const std::filesystem::path& vocab_json_path);
