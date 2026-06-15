#include "hangul_romaji.h"
#include "utf8_utils.h"

#include <cstdint>

namespace hangul {

namespace {

// Hangul Jamo romanization tables (from uroman)
// Initial consonants (choseong) - 19 jamo
const char* const LEADS[] = {
    "g", "gg", "n", "d", "dd", "r", "m", "b", "bb", "s",
    "ss", "", "j", "jj", "c", "k", "t", "p", "h"  // index 14: c (not ch)
};

// Medial vowels (jungseong) - 21 jamo
const char* const VOWELS[] = {
    "a", "ae", "ya", "yae", "eo", "e", "yeo", "ye", "o", "wa",
    "wai", "oe", "yo", "u", "weo", "we", "wi", "yu", "eu", "yi", "i"  // index 10: wai (not wae)
};

// Final consonants (jongseong) - 28 jamo (including none)
const char* const TAILS[] = {
    "", "g", "gg", "gs", "n", "nj", "nh", "d", "l", "lg",
    "lm", "lb", "ls", "lt", "lp", "lh", "m", "b", "bs", "s",
    "ss", "ng", "j", "c", "k", "t", "p", "h"  // index 23: c (not ch)
};

}  // anonymous namespace

bool is_hangul(std::string_view ch) {
    uint32_t cp = utf8::to_codepoint(ch);
    // Hangul Syllables: U+AC00 to U+D7A3
    return cp >= 0xAC00 && cp <= 0xD7A3;
}

std::string hangul_to_romaji(std::string_view hangul_char) {
    uint32_t cp = utf8::to_codepoint(hangul_char);

    // Check if it's a Hangul syllable
    if (cp < 0xAC00 || cp > 0xD7A3) {
        return "";
    }

    // Decompose the syllable
    // Hangul syllable = (lead * 21 + vowel) * 28 + tail + 0xAC00
    uint32_t code = cp - 0xAC00;
    int lead_index = static_cast<int>(code / (28 * 21));
    int vowel_index = static_cast<int>((code / 28) % 21);
    int tail_index = static_cast<int>(code % 28);

    std::string result;
    result += LEADS[lead_index];
    result += VOWELS[vowel_index];
    result += TAILS[tail_index];

    return result;
}

std::string romanize_hangul(const std::string& text) {
    std::string result;
    result.reserve(text.size() * 2);

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

        if (is_hangul(char_view)) {
            result += hangul_to_romaji(char_view);
        } else {
            // Not Hangul, keep as-is
            result.append(char_view);
        }
        i += char_len;
    }

    return result;
}

}  // namespace hangul
