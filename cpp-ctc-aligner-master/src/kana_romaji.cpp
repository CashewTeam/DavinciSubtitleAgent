#include "kana_romaji.h"
#include "kanji_pinyin.h"
#include "hangul_romaji.h"
#include "utf8_utils.h"

#include <unordered_map>
#include <cstdint>

namespace kana {

namespace {

// Build the kana-to-romaji lookup table
const std::unordered_map<std::string, std::string>& get_kana_map() {
    static const std::unordered_map<std::string, std::string> kana_map = {
        // Basic Hiragana (46 characters)
        {"\xe3\x81\x82", "a"}, {"\xe3\x81\x84", "i"}, {"\xe3\x81\x86", "u"}, {"\xe3\x81\x88", "e"}, {"\xe3\x81\x8a", "o"},
        {"\xe3\x81\x8b", "ka"}, {"\xe3\x81\x8d", "ki"}, {"\xe3\x81\x8f", "ku"}, {"\xe3\x81\x91", "ke"}, {"\xe3\x81\x93", "ko"},
        {"\xe3\x81\x95", "sa"}, {"\xe3\x81\x97", "shi"}, {"\xe3\x81\x99", "su"}, {"\xe3\x81\x9b", "se"}, {"\xe3\x81\x9d", "so"},
        {"\xe3\x81\x9f", "ta"}, {"\xe3\x81\xa1", "chi"}, {"\xe3\x81\xa4", "tsu"}, {"\xe3\x81\xa6", "te"}, {"\xe3\x81\xa8", "to"},
        {"\xe3\x81\xaa", "na"}, {"\xe3\x81\xab", "ni"}, {"\xe3\x81\xac", "nu"}, {"\xe3\x81\xad", "ne"}, {"\xe3\x81\xae", "no"},
        {"\xe3\x81\xaf", "ha"}, {"\xe3\x81\xb2", "hi"}, {"\xe3\x81\xb5", "fu"}, {"\xe3\x81\xb8", "he"}, {"\xe3\x81\xbb", "ho"},
        {"\xe3\x81\xbe", "ma"}, {"\xe3\x81\xbf", "mi"}, {"\xe3\x82\x80", "mu"}, {"\xe3\x82\x81", "me"}, {"\xe3\x82\x82", "mo"},
        {"\xe3\x82\x84", "ya"}, {"\xe3\x82\x86", "yu"}, {"\xe3\x82\x88", "yo"},
        {"\xe3\x82\x89", "ra"}, {"\xe3\x82\x8a", "ri"}, {"\xe3\x82\x8b", "ru"}, {"\xe3\x82\x8c", "re"}, {"\xe3\x82\x8d", "ro"},
        {"\xe3\x82\x8f", "wa"}, {"\xe3\x82\x92", "o"}, {"\xe3\x82\x93", "n"},  // を → o (modern pronunciation)

        // Voiced Hiragana (20 characters)
        {"\xe3\x81\x8c", "ga"}, {"\xe3\x81\x8e", "gi"}, {"\xe3\x81\x90", "gu"}, {"\xe3\x81\x92", "ge"}, {"\xe3\x81\x94", "go"},
        {"\xe3\x81\x96", "za"}, {"\xe3\x81\x98", "ji"}, {"\xe3\x81\x9a", "zu"}, {"\xe3\x81\x9c", "ze"}, {"\xe3\x81\x9e", "zo"},
        {"\xe3\x81\xa0", "da"}, {"\xe3\x81\xa2", "ji"}, {"\xe3\x81\xa5", "zu"}, {"\xe3\x81\xa7", "de"}, {"\xe3\x81\xa9", "do"},
        {"\xe3\x81\xb0", "ba"}, {"\xe3\x81\xb3", "bi"}, {"\xe3\x81\xb6", "bu"}, {"\xe3\x81\xb9", "be"}, {"\xe3\x81\xbc", "bo"},
        {"\xe3\x81\xb1", "pa"}, {"\xe3\x81\xb4", "pi"}, {"\xe3\x81\xb7", "pu"}, {"\xe3\x81\xba", "pe"}, {"\xe3\x81\xbd", "po"},

        // Combination Hiragana (拗音) - 2-character sequences
        {"\xe3\x81\x8d\xe3\x82\x83", "kya"}, {"\xe3\x81\x8d\xe3\x82\x85", "kyu"}, {"\xe3\x81\x8d\xe3\x82\x87", "kyo"},
        {"\xe3\x81\x97\xe3\x82\x83", "sha"}, {"\xe3\x81\x97\xe3\x82\x85", "shu"}, {"\xe3\x81\x97\xe3\x82\x87", "sho"},
        {"\xe3\x81\xa1\xe3\x82\x83", "cha"}, {"\xe3\x81\xa1\xe3\x82\x85", "chu"}, {"\xe3\x81\xa1\xe3\x82\x87", "cho"},
        {"\xe3\x81\xab\xe3\x82\x83", "nya"}, {"\xe3\x81\xab\xe3\x82\x85", "nyu"}, {"\xe3\x81\xab\xe3\x82\x87", "nyo"},
        {"\xe3\x81\xb2\xe3\x82\x83", "hya"}, {"\xe3\x81\xb2\xe3\x82\x85", "hyu"}, {"\xe3\x81\xb2\xe3\x82\x87", "hyo"},
        {"\xe3\x81\xbf\xe3\x82\x83", "mya"}, {"\xe3\x81\xbf\xe3\x82\x85", "myu"}, {"\xe3\x81\xbf\xe3\x82\x87", "myo"},
        {"\xe3\x82\x8a\xe3\x82\x83", "rya"}, {"\xe3\x82\x8a\xe3\x82\x85", "ryu"}, {"\xe3\x82\x8a\xe3\x82\x87", "ryo"},
        {"\xe3\x81\x8e\xe3\x82\x83", "gya"}, {"\xe3\x81\x8e\xe3\x82\x85", "gyu"}, {"\xe3\x81\x8e\xe3\x82\x87", "gyo"},
        {"\xe3\x81\x98\xe3\x82\x83", "ja"}, {"\xe3\x81\x98\xe3\x82\x85", "ju"}, {"\xe3\x81\x98\xe3\x82\x87", "jo"},
        {"\xe3\x81\xb3\xe3\x82\x83", "bya"}, {"\xe3\x81\xb3\xe3\x82\x85", "byu"}, {"\xe3\x81\xb3\xe3\x82\x87", "byo"},
        {"\xe3\x81\xb4\xe3\x82\x83", "pya"}, {"\xe3\x81\xb4\xe3\x82\x85", "pyu"}, {"\xe3\x81\xb4\xe3\x82\x87", "pyo"},

        // Special hiragana characters
        {"\xe3\x81\xa3", "tsu"},  // っ (small tsu) - romanize as tsu for alignment
        {"\xe3\x83\xbc", ""},  // ー (long vowel mark) - repeat previous vowel, output empty for now

        // Small hiragana vowels (ぁぃぅぇぉ)
        {"\xe3\x81\x81", "a"}, {"\xe3\x81\x83", "i"}, {"\xe3\x81\x85", "u"}, {"\xe3\x81\x87", "e"}, {"\xe3\x81\x89", "o"},
        // Small hiragana ya/yu/yo (ゃゅょ)
        {"\xe3\x82\x83", "ya"}, {"\xe3\x82\x85", "yu"}, {"\xe3\x82\x87", "yo"},
        // Small hiragana wa (ゎ)
        {"\xe3\x82\x8e", "wa"},

        // Basic Katakana (46 characters) - same as hiragana + 0x60 offset
        {"\xe3\x82\xa2", "a"}, {"\xe3\x82\xa4", "i"}, {"\xe3\x82\xa6", "u"}, {"\xe3\x82\xa8", "e"}, {"\xe3\x82\xaa", "o"},
        {"\xe3\x82\xab", "ka"}, {"\xe3\x82\xad", "ki"}, {"\xe3\x82\xaf", "ku"}, {"\xe3\x82\xb1", "ke"}, {"\xe3\x82\xb3", "ko"},
        {"\xe3\x82\xb5", "sa"}, {"\xe3\x82\xb7", "shi"}, {"\xe3\x82\xb9", "su"}, {"\xe3\x82\xbb", "se"}, {"\xe3\x82\xbd", "so"},
        {"\xe3\x82\xbf", "ta"}, {"\xe3\x83\x81", "chi"}, {"\xe3\x83\x84", "tsu"}, {"\xe3\x83\x86", "te"}, {"\xe3\x83\x88", "to"},
        {"\xe3\x83\x8a", "na"}, {"\xe3\x83\x8b", "ni"}, {"\xe3\x83\x8c", "nu"}, {"\xe3\x83\x8d", "ne"}, {"\xe3\x83\x8e", "no"},
        {"\xe3\x83\x8f", "ha"}, {"\xe3\x83\x92", "hi"}, {"\xe3\x83\x95", "fu"}, {"\xe3\x83\x98", "he"}, {"\xe3\x83\x9b", "ho"},
        {"\xe3\x83\x9e", "ma"}, {"\xe3\x83\x9f", "mi"}, {"\xe3\x83\xa0", "mu"}, {"\xe3\x83\xa1", "me"}, {"\xe3\x83\xa2", "mo"},
        {"\xe3\x83\xa4", "ya"}, {"\xe3\x83\xa6", "yu"}, {"\xe3\x83\xa8", "yo"},
        {"\xe3\x83\xa9", "ra"}, {"\xe3\x83\xaa", "ri"}, {"\xe3\x83\xab", "ru"}, {"\xe3\x83\xac", "re"}, {"\xe3\x83\xad", "ro"},
        {"\xe3\x83\xaf", "wa"}, {"\xe3\x83\xb2", "o"}, {"\xe3\x83\xb3", "n"},  // ヲ → o (modern pronunciation)

        // Voiced Katakana (20 characters)
        {"\xe3\x82\xac", "ga"}, {"\xe3\x82\xae", "gi"}, {"\xe3\x82\xb0", "gu"}, {"\xe3\x82\xb2", "ge"}, {"\xe3\x82\xb4", "go"},
        {"\xe3\x82\xb6", "za"}, {"\xe3\x82\xb8", "ji"}, {"\xe3\x82\xba", "zu"}, {"\xe3\x82\xbc", "ze"}, {"\xe3\x82\xbe", "zo"},
        {"\xe3\x83\x80", "da"}, {"\xe3\x83\x82", "ji"}, {"\xe3\x83\x85", "zu"}, {"\xe3\x83\x87", "de"}, {"\xe3\x83\x89", "do"},
        {"\xe3\x83\x90", "ba"}, {"\xe3\x83\x93", "bi"}, {"\xe3\x83\x96", "bu"}, {"\xe3\x83\x99", "be"}, {"\xe3\x83\x9c", "bo"},
        {"\xe3\x83\x91", "pa"}, {"\xe3\x83\x94", "pi"}, {"\xe3\x83\x97", "pu"}, {"\xe3\x83\x9a", "pe"}, {"\xe3\x83\x9d", "po"},

        // Combination Katakana (拗音) - 2-character sequences
        {"\xe3\x82\xad\xe3\x83\xa3", "kya"}, {"\xe3\x82\xad\xe3\x83\xa5", "kyu"}, {"\xe3\x82\xad\xe3\x83\xa7", "kyo"},
        {"\xe3\x82\xb7\xe3\x83\xa3", "sha"}, {"\xe3\x82\xb7\xe3\x83\xa5", "shu"}, {"\xe3\x82\xb7\xe3\x83\xa7", "sho"},
        {"\xe3\x83\x81\xe3\x83\xa3", "cha"}, {"\xe3\x83\x81\xe3\x83\xa5", "chu"}, {"\xe3\x83\x81\xe3\x83\xa7", "cho"},
        {"\xe3\x83\x8b\xe3\x83\xa3", "nya"}, {"\xe3\x83\x8b\xe3\x83\xa5", "nyu"}, {"\xe3\x83\x8b\xe3\x83\xa7", "nyo"},
        {"\xe3\x83\x92\xe3\x83\xa3", "hya"}, {"\xe3\x83\x92\xe3\x83\xa5", "hyu"}, {"\xe3\x83\x92\xe3\x83\xa7", "hyo"},
        {"\xe3\x83\x9f\xe3\x83\xa3", "mya"}, {"\xe3\x83\x9f\xe3\x83\xa5", "myu"}, {"\xe3\x83\x9f\xe3\x83\xa7", "myo"},
        {"\xe3\x83\xaa\xe3\x83\xa3", "rya"}, {"\xe3\x83\xaa\xe3\x83\xa5", "ryu"}, {"\xe3\x83\xaa\xe3\x83\xa7", "ryo"},
        {"\xe3\x82\xae\xe3\x83\xa3", "gya"}, {"\xe3\x82\xae\xe3\x83\xa5", "gyu"}, {"\xe3\x82\xae\xe3\x83\xa7", "gyo"},
        {"\xe3\x82\xb8\xe3\x83\xa3", "ja"}, {"\xe3\x82\xb8\xe3\x83\xa5", "ju"}, {"\xe3\x82\xb8\xe3\x83\xa7", "jo"},
        {"\xe3\x83\x93\xe3\x83\xa3", "bya"}, {"\xe3\x83\x93\xe3\x83\xa5", "byu"}, {"\xe3\x83\x93\xe3\x83\xa7", "byo"},
        {"\xe3\x83\x94\xe3\x83\xa3", "pya"}, {"\xe3\x83\x94\xe3\x83\xa5", "pyu"}, {"\xe3\x83\x94\xe3\x83\xa7", "pyo"},

        // Special katakana characters
        {"\xe3\x83\x83", "tsu"},  // ッ (small tsu) - romanize as tsu for alignment

        // Small katakana vowels (ァィゥェォ)
        {"\xe3\x82\xa1", "a"}, {"\xe3\x82\xa3", "i"}, {"\xe3\x82\xa5", "u"}, {"\xe3\x82\xa7", "e"}, {"\xe3\x82\xa9", "o"},
        // Small katakana ya/yu/yo (ャュョ)
        {"\xe3\x83\xa3", "ya"}, {"\xe3\x83\xa5", "yu"}, {"\xe3\x83\xa7", "yo"},
        // Small katakana wa (ヮ)
        {"\xe3\x83\xae", "wa"},

        // Foreign loanword combinations (外来語) - from uroman override rules
        // ェ combinations
        {"\xe3\x83\x81\xe3\x82\xa7", "che"},  // チェ → che
        {"\xe3\x82\xb8\xe3\x82\xa7", "je"},   // ジェ → je
        {"\xe3\x83\x95\xe3\x82\xa7", "fe"},   // フェ → fe
        {"\xe3\x83\xb4\xe3\x82\xa7", "ve"},   // ヴェ → ve
        // ィ combinations
        {"\xe3\x83\x95\xe3\x82\xa3", "fi"},   // フィ → fi
        {"\xe3\x82\xa6\xe3\x82\xa3", "wi"},   // ウィ → wi
        {"\xe3\x83\xb4\xe3\x82\xa3", "vi"},   // ヴィ → vi
        {"\xe3\x83\x86\xe3\x82\xa3", "ti"},   // ティ → ti
        {"\xe3\x83\x87\xe3\x82\xa3", "di"},   // ディ → di
        // ヴ (vu) - used in loanwords
        {"\xe3\x83\xb4", "vu"},               // ヴ → vu
        // Katakana middle dot (・) - word separator in loanwords
        {"\xe3\x83\xbb", " "},                // ・ → space
    };
    return kana_map;
}

// Check if a UTF-8 character is kanji (CJK Unified Ideograph)
bool is_kanji(std::string_view ch) {
    uint32_t cp = utf8::to_codepoint(ch);
    // CJK Unified Ideographs: U+4E00 to U+9FFF
    return cp >= 0x4E00 && cp <= 0x9FFF;
}

}  // anonymous namespace

std::string romanize_kana(const std::string& text) {
    const auto& kana_map = get_kana_map();
    std::string result;
    result.reserve(text.size() * 2);  // Romaji is typically longer

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

        // Try 2-character combination first (for 拗音 like きゃ)
        if (char_len == 3 && i + 6 <= text.size()) {
            std::string two_char = text.substr(i, 6);
            auto it = kana_map.find(two_char);
            if (it != kana_map.end()) {
                result += it->second;
                i += 6;
                continue;
            }
        }

        // Try single character
        std::string one_char = text.substr(i, char_len);
        auto it = kana_map.find(one_char);
        if (it != kana_map.end()) {
            result += it->second;
        } else {
            // Not a kana character, check if it's kanji or Hangul
            std::string_view char_view(text.data() + i, char_len);
            if (is_kanji(char_view)) {
                // Try to convert kanji to pinyin
                std::string pinyin = kanji::kanji_to_pinyin(char_view);
                if (!pinyin.empty()) {
                    result += pinyin;
                } else {
                    // Kanji not found in table, keep as-is
                    result += one_char;
                }
            } else if (hangul::is_hangul(char_view)) {
                // Convert Hangul to romanized form
                result += hangul::hangul_to_romaji(char_view);
            } else {
                // Not kana, kanji, or Hangul, keep as-is
                result += one_char;
            }
        }
        i += char_len;
    }

    return result;
}

}  // namespace kana
