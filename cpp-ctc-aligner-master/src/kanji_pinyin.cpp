#include "kanji_pinyin.h"
#include "utf8_utils.h"

#include <fstream>
#include <sstream>
#include <unordered_map>
#include <cstdint>

namespace kanji {

namespace {

// Global pinyin lookup table
std::unordered_map<std::string, std::string> g_pinyin_table;
bool g_loaded = false;

// Check if a code point is in CJK Unified Ideographs range
bool is_cjk_codepoint(uint32_t cp) {
    // CJK Unified Ideographs: U+4E00 to U+9FFF
    // CJK Extension A: U+3400 to U+4DBF
    // CJK Extension B-F and other ranges
    return (cp >= 0x4E00 && cp <= 0x9FFF) ||
           (cp >= 0x3400 && cp <= 0x4DBF) ||
           (cp >= 0x20000 && cp <= 0x2A6DF) ||
           (cp >= 0x2A700 && cp <= 0x2B73F) ||
           (cp >= 0x2B740 && cp <= 0x2B81F) ||
           (cp >= 0x2B820 && cp <= 0x2CEAF) ||
           (cp >= 0xF900 && cp <= 0xFAFF);  // CJK Compatibility Ideographs
}

}  // anonymous namespace

bool load_pinyin_table(const std::string& data_path) {
    std::ifstream file(data_path);
    if (!file.is_open()) {
        return false;
    }

    g_pinyin_table.clear();
    std::string line;

    while (std::getline(file, line)) {
        // Skip empty lines
        if (line.empty()) continue;

        // Find tab separator
        size_t tab_pos = line.find('\t');
        if (tab_pos == std::string::npos || tab_pos == 0) continue;

        // Extract character (before tab) and pinyin (after tab)
        std::string character = line.substr(0, tab_pos);
        std::string pinyin = line.substr(tab_pos + 1);

        // If there are multiple readings separated by space, use first one
        size_t space_pos = pinyin.find(' ');
        if (space_pos != std::string::npos) {
            pinyin = pinyin.substr(0, space_pos);
        }

        // Trim trailing whitespace from pinyin
        while (!pinyin.empty() && (pinyin.back() == ' ' || pinyin.back() == '\r' || pinyin.back() == '\n')) {
            pinyin.pop_back();
        }

        if (!character.empty() && !pinyin.empty()) {
            g_pinyin_table[character] = pinyin;
        }
    }

    g_loaded = !g_pinyin_table.empty();
    return g_loaded;
}

bool is_loaded() {
    return g_loaded;
}

std::string kanji_to_pinyin(std::string_view kanji_char) {
    if (!g_loaded || kanji_char.empty()) {
        return "";
    }

    std::string key(kanji_char);
    auto it = g_pinyin_table.find(key);
    if (it != g_pinyin_table.end()) {
        return it->second;
    }
    return "";
}

std::string romanize_kanji(const std::string& text) {
    if (!g_loaded) {
        return text;  // Return unchanged if table not loaded
    }

    std::string result;
    result.reserve(text.size() * 2);  // Pinyin is typically longer

    size_t i = 0;
    while (i < text.size()) {
        unsigned char c = static_cast<unsigned char>(text[i]);
        size_t char_len = utf8::char_len(c);

        // Ensure we don't read past the end
        if (i + char_len > text.size()) {
            result += text[i];
            ++i;
            continue;
        }

        std::string_view char_view(text.data() + i, char_len);
        uint32_t cp = utf8::to_codepoint(char_view);

        // Check if it's a CJK character
        if (is_cjk_codepoint(cp)) {
            std::string pinyin = kanji_to_pinyin(char_view);
            if (!pinyin.empty()) {
                result += pinyin;
            } else {
                // Not found in table, keep original
                result.append(char_view);
            }
        } else {
            // Not a CJK character, keep as-is
            result.append(char_view);
        }
        i += char_len;
    }

    return result;
}

}  // namespace kanji
