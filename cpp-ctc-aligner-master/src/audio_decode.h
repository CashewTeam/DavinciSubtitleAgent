#pragma once

#include <filesystem>
#include <vector>
#include <cstdint>

// Decode any supported audio file (MP3, WAV, FLAC, etc.) to 16kHz mono float samples
// Returns samples in range [-1.0, 1.0]
// Throws on decode failure
std::vector<float> decode_audio_to_16k_mono(const std::filesystem::path& audio_path);
