#pragma once
#include <string>
#include <string_view>

namespace kanji {

// Initialize the kanji-to-pinyin lookup table from data file
// Call once at startup. Returns true on success.
bool load_pinyin_table(const std::string& data_path);

// Check if the pinyin table is loaded
bool is_loaded();

// Look up a single kanji character and return its pinyin
// Returns empty string if not found or not a kanji
std::string kanji_to_pinyin(std::string_view kanji_char);

// Convert text, replacing kanji with pinyin, keeping other chars as-is
std::string romanize_kanji(const std::string& text);

}  // namespace kanji
