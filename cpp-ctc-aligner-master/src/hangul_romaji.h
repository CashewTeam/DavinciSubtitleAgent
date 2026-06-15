#pragma once

#include <string>
#include <string_view>

namespace hangul {

// Check if a character is a Hangul syllable (U+AC00 to U+D7A3)
bool is_hangul(std::string_view ch);

// Convert a single Hangul syllable to romanized form
// Uses algorithmic decomposition (not table-based)
std::string hangul_to_romaji(std::string_view hangul_char);

// Romanize a string containing Hangul characters
std::string romanize_hangul(const std::string& text);

}  // namespace hangul
