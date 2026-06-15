#include "text_preprocess.h"
#include "kana_romaji.h"
#include "utf8_utils.h"

#include <cctype>
#include <regex>
#include <string>
#include <unordered_map>
#include <vector>

namespace {

// Strip tone marks from pinyin (e.g., jīn → jin, fāng → fang)
static std::string strip_pinyin_tones(const std::string& s) {
  // Map of UTF-8 sequences for accented vowels to their base ASCII
  static const std::unordered_map<std::string, char> tone_map = {
    // ā á ǎ à → a
    {"\xc4\x81", 'a'}, {"\xc3\xa1", 'a'}, {"\xc7\x8e", 'a'}, {"\xc3\xa0", 'a'},
    // ē é ě è → e
    {"\xc4\x93", 'e'}, {"\xc3\xa9", 'e'}, {"\xc4\x9b", 'e'}, {"\xc3\xa8", 'e'},
    // ī í ǐ ì → i
    {"\xc4\xab", 'i'}, {"\xc3\xad", 'i'}, {"\xc7\x90", 'i'}, {"\xc3\xac", 'i'},
    // ō ó ǒ ò → o
    {"\xc5\x8d", 'o'}, {"\xc3\xb3", 'o'}, {"\xc7\x92", 'o'}, {"\xc3\xb2", 'o'},
    // ū ú ǔ ù → u
    {"\xc5\xab", 'u'}, {"\xc3\xba", 'u'}, {"\xc7\x94", 'u'}, {"\xc3\xb9", 'u'},
    // ǖ ǘ ǚ ǜ ü → v (pinyin convention)
    {"\xc7\x96", 'v'}, {"\xc7\x98", 'v'}, {"\xc7\x9a", 'v'}, {"\xc7\x9c", 'v'}, {"\xc3\xbc", 'v'},
    // ń ň ǹ → n
    {"\xc5\x84", 'n'}, {"\xc5\x88", 'n'}, {"\xc7\xb9", 'n'},
  };

  std::string result;
  result.reserve(s.size());

  for (size_t i = 0; i < s.size();) {
    unsigned char c = static_cast<unsigned char>(s[i]);

    // Check for 2-byte UTF-8 sequence (most pinyin tones are here)
    if ((c & 0xE0) == 0xC0 && i + 1 < s.size()) {
      std::string seq = s.substr(i, 2);
      auto it = tone_map.find(seq);
      if (it != tone_map.end()) {
        result.push_back(it->second);
        i += 2;
        continue;
      }
    }

    // Not a tone mark, copy as-is
    result.push_back(s[i]);
    ++i;
  }

  return result;
}

static std::string normalize_uroman_cpp(std::string s) {
  // First strip pinyin tone marks
  s = strip_pinyin_tones(s);
  for (char& c : s) c = char(std::tolower(static_cast<unsigned char>(c)));
  // Keep only a-z, apostrophe, and space. Anything else becomes space.
  for (char& c : s) {
    if ((c >= 'a' && c <= 'z') || c == '\'' || c == ' ') continue;
    c = ' ';
  }
  // collapse spaces
  std::string out;
  out.reserve(s.size());
  bool prev_space = true;
  for (char c : s) {
    if (c == ' ') {
      if (!prev_space) out.push_back(' ');
      prev_space = true;
    } else {
      out.push_back(c);
      prev_space = false;
    }
  }
  // trim
  while (!out.empty() && out.front() == ' ') out.erase(out.begin());
  while (!out.empty() && out.back() == ' ') out.pop_back();
  return out;
}


static std::vector<std::string> split_text_word_or_char(const std::string& text, bool force_char) {
  if (force_char) return utf8::split_chars(text);
  std::vector<std::string> out;
  std::string cur;
  for (size_t i = 0; i < text.size();) {
    unsigned char c = static_cast<unsigned char>(text[i]);
    if (c < 0x80 && std::isspace(c)) {
      if (!cur.empty()) out.push_back(cur);
      cur.clear();
      ++i;
      continue;
    }
    // utf8 char
    size_t n = 1;
    if (c < 0x80)
      n = 1;
    else if ((c >> 5) == 0x6)
      n = 2;
    else if ((c >> 4) == 0xE)
      n = 3;
    else if ((c >> 3) == 0x1E)
      n = 4;
    if (i + n > text.size()) n = 1;
    cur.append(text.substr(i, n));
    i += n;
  }
  if (!cur.empty()) out.push_back(cur);
  return out;
}

// Pure C++ romanization using kana_romaji module
static std::string romanize_text(const std::string& norm_text) {
  // 1. Convert kana to romaji
  std::string romanized = kana::romanize_kana(norm_text);

  // 2. Strip leading/trailing whitespace
  std::string stripped = romanized;
  while (!stripped.empty() && std::isspace(static_cast<unsigned char>(stripped.front()))) stripped.erase(stripped.begin());
  while (!stripped.empty() && std::isspace(static_cast<unsigned char>(stripped.back()))) stripped.pop_back();

  // 3. Join characters with spaces (like Python's " ".join(text.strip()))
  std::string joined;
  const auto chars = utf8::split_chars(stripped);
  for (size_t k = 0; k < chars.size(); ++k) {
    if (k) joined.push_back(' ');
    joined += chars[k];
  }

  // 4. Collapse whitespace to single spaces
  joined = std::regex_replace(joined, std::regex(R"(\s+)"), " ");
  while (!joined.empty() && joined.front() == ' ') joined.erase(joined.begin());
  while (!joined.empty() && joined.back() == ' ') joined.pop_back();

  // 5. Normalize (lowercase, keep only a-z, apostrophe, space)
  return normalize_uroman_cpp(joined);
}

// Tokenize UTF-8 text for Omnilingual model (direct vocab lookup, no romanization)
static std::vector<std::string> tokenize_utf8_for_omnilingual(
    const std::string& text,
    const Vocab& vocab) {
  std::vector<std::string> tokens;
  const auto chars = utf8::split_chars(text);

  for (const auto& ch : chars) {
    // Skip whitespace - CJK languages don't use space as word separator
    // and including space as token causes issues with space-separated token joining
    if (ch.size() == 1 && std::isspace(static_cast<unsigned char>(ch[0]))) {
      continue;
    }

    // Try direct lookup first
    if (vocab.token_to_id.count(ch)) {
      tokens.push_back(ch);
      continue;
    }

    // Try lowercase: ASCII and common Unicode uppercase ranges
    uint32_t cp = utf8::to_codepoint(std::string_view(ch.data(), ch.size()));
    uint32_t lower_cp = cp;
    if (cp >= 'A' && cp <= 'Z') {
      lower_cp = cp + 0x20;
    } else if ((cp >= 0x00C0 && cp <= 0x00D6) || (cp >= 0x00D8 && cp <= 0x00DE)) {
      lower_cp = cp + 0x20;  // Latin Extended uppercase (À-Ö, Ø-Þ)
    } else if (cp >= 0x0410 && cp <= 0x042F) {
      lower_cp = cp + 0x20;  // Cyrillic А-Я → а-я
    } else if (cp >= 0x0400 && cp <= 0x040F) {
      lower_cp = cp + 0x50;  // Cyrillic Ё etc. → ё etc.
    } else if ((cp >= 0x0391 && cp <= 0x03A1) || (cp >= 0x03A3 && cp <= 0x03A9)) {
      lower_cp = cp + 0x20;  // Greek Α-Ω → α-ω
    }
    if (lower_cp != cp) {
      std::string lower_ch = utf8::from_codepoint(lower_cp);
      if (vocab.token_to_id.count(lower_ch)) {
        tokens.push_back(lower_ch);
        continue;
      }
    }

    // Unknown character - silently skip (punctuation, etc.)
  }

  return tokens;
}

}  // namespace

PreprocessResult preprocess_text(
    const std::string& full_text,
    const Vocab& vocab,
    const PreprocessConfig& config) {
  PreprocessResult r;
  r.full_text = full_text;

  const bool force_char = (config.language == "jpn" || config.language == "chi" ||
                           config.language == "cmn" || config.language == "kor" ||
                           config.language == "zho");
  const auto text_split = split_text_word_or_char(full_text, force_char);

  std::vector<std::string> tokens;
  tokens.reserve(text_split.size());

  if (config.romanize) {
    // MMS-style: romanize then normalize
    for (const auto& chunk : text_split) {
      std::string out = chunk;
      out = std::regex_replace(out, std::regex(R"(\s+)"), " ");
      while (!out.empty() && std::isspace(static_cast<unsigned char>(out.front()))) out.erase(out.begin());
      while (!out.empty() && std::isspace(static_cast<unsigned char>(out.back()))) out.pop_back();
      tokens.push_back(romanize_text(out));
    }
  } else if (vocab.format == VocabFormat::TXT) {
    // Omnilingual-style: UTF-8 character-level tokenization with direct vocab lookup
    for (const auto& chunk : text_split) {
      const auto chunk_tokens = tokenize_utf8_for_omnilingual(chunk, vocab);
      // Join tokens with space separator
      std::string joined;
      for (size_t k = 0; k < chunk_tokens.size(); ++k) {
        if (k > 0) joined.push_back(' ');
        joined += chunk_tokens[k];
      }
      tokens.push_back(joined);
    }
  } else {
    // MMS non-romanized (English): normalize to a-z only
    for (const auto& chunk : text_split) {
      std::string out = chunk;
      out = std::regex_replace(out, std::regex(R"(\s+)"), " ");
      while (!out.empty() && std::isspace(static_cast<unsigned char>(out.front()))) out.erase(out.begin());
      while (!out.empty() && std::isspace(static_cast<unsigned char>(out.back()))) out.pop_back();

      const auto chars = utf8::split_chars(out);
      std::string joined;
      for (size_t k = 0; k < chars.size(); ++k) {
        if (chars[k].size() == 1) {
          char c = chars[k][0];
          if (c >= 'A' && c <= 'Z') {
            c = c - 'A' + 'a';
          }
          if ((c >= 'a' && c <= 'z') || c == '\'') {
            if (!joined.empty()) joined.push_back(' ');
            joined.push_back(c);
          }
        }
      }
      tokens.push_back(joined);
    }
  }

  // star_frequency = "segment" as used by align.py
  r.tokens_starred.reserve(tokens.size() * 2);
  r.text_starred.reserve(text_split.size() * 2);
  for (size_t i = 0; i < tokens.size(); ++i) {
    r.tokens_starred.push_back("<star>");
    r.tokens_starred.push_back(tokens[i]);
    r.text_starred.push_back("<star>");
    r.text_starred.push_back(text_split[i]);
  }
  return r;
}

// Legacy API for backward compatibility (MMS-style preprocessing)
PreprocessResult preprocess_text_cpp(const std::string& full_text, const std::string& language, bool romanize) {
  // Create a dummy MMS-style vocab for legacy API
  Vocab dummy_vocab;
  dummy_vocab.format = VocabFormat::JSON;

  PreprocessConfig config;
  config.romanize = romanize;
  config.language = language;

  return preprocess_text(full_text, dummy_vocab, config);
}
