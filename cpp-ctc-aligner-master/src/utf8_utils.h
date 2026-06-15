#pragma once

#include <cstdint>
#include <string>
#include <string_view>
#include <vector>

namespace utf8 {

// Byte length of a UTF-8 character from its first byte.
inline size_t char_len(unsigned char first_byte) {
  if ((first_byte & 0x80) == 0) return 1;
  if ((first_byte & 0xE0) == 0xC0) return 2;
  if ((first_byte & 0xF0) == 0xE0) return 3;
  if ((first_byte & 0xF8) == 0xF0) return 4;
  return 1;  // Invalid, treat as 1
}

// Decode the first Unicode codepoint from a UTF-8 string.
inline uint32_t to_codepoint(std::string_view s) {
  if (s.empty()) return 0;
  unsigned char c0 = static_cast<unsigned char>(s[0]);

  if ((c0 & 0x80) == 0) return c0;
  if ((c0 & 0xE0) == 0xC0 && s.size() >= 2) {
    return ((c0 & 0x1F) << 6) | (static_cast<unsigned char>(s[1]) & 0x3F);
  }
  if ((c0 & 0xF0) == 0xE0 && s.size() >= 3) {
    return ((c0 & 0x0F) << 12) | ((static_cast<unsigned char>(s[1]) & 0x3F) << 6) |
           (static_cast<unsigned char>(s[2]) & 0x3F);
  }
  if ((c0 & 0xF8) == 0xF0 && s.size() >= 4) {
    return ((c0 & 0x07) << 18) | ((static_cast<unsigned char>(s[1]) & 0x3F) << 12) |
           ((static_cast<unsigned char>(s[2]) & 0x3F) << 6) | (static_cast<unsigned char>(s[3]) & 0x3F);
  }
  return 0;
}

// Encode a Unicode codepoint to a UTF-8 string.
inline std::string from_codepoint(uint32_t cp) {
  std::string s;
  if (cp < 0x80) {
    s.push_back(static_cast<char>(cp));
  } else if (cp < 0x800) {
    s.push_back(static_cast<char>(0xC0 | (cp >> 6)));
    s.push_back(static_cast<char>(0x80 | (cp & 0x3F)));
  } else if (cp < 0x10000) {
    s.push_back(static_cast<char>(0xE0 | (cp >> 12)));
    s.push_back(static_cast<char>(0x80 | ((cp >> 6) & 0x3F)));
    s.push_back(static_cast<char>(0x80 | (cp & 0x3F)));
  } else {
    s.push_back(static_cast<char>(0xF0 | (cp >> 18)));
    s.push_back(static_cast<char>(0x80 | ((cp >> 12) & 0x3F)));
    s.push_back(static_cast<char>(0x80 | ((cp >> 6) & 0x3F)));
    s.push_back(static_cast<char>(0x80 | (cp & 0x3F)));
  }
  return s;
}

// Split a UTF-8 string into individual characters.
inline std::vector<std::string> split_chars(const std::string& s) {
  std::vector<std::string> out;
  for (size_t i = 0; i < s.size();) {
    size_t n = char_len(static_cast<unsigned char>(s[i]));
    if (i + n > s.size()) n = 1;
    out.push_back(s.substr(i, n));
    i += n;
  }
  return out;
}

// Count the number of Unicode codepoints in a UTF-8 string.
inline size_t codepoint_count(const std::string& s) {
  size_t count = 0;
  for (size_t i = 0; i < s.size();) {
    size_t n = char_len(static_cast<unsigned char>(s[i]));
    if (i + n > s.size()) n = 1;
    i += n;
    ++count;
  }
  return count;
}

}  // namespace utf8
