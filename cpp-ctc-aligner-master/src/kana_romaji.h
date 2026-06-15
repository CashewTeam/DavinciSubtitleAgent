#pragma once

#include <string>
#include <string_view>

namespace kana {

// Convert full text, replacing kana with romaji, keeping other chars as-is
std::string romanize_kana(const std::string& text);

}  // namespace kana
