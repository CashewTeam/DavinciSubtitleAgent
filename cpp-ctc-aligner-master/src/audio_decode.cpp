#define MINIAUDIO_IMPLEMENTATION
#include "miniaudio.h"
#include "audio_decode.h"
#include <stdexcept>
#include <string>
#include <cmath>

std::vector<float> decode_audio_to_16k_mono(const std::filesystem::path& audio_path) {
    ma_decoder_config config = ma_decoder_config_init(ma_format_f32, 1, 16000);
    ma_decoder decoder;

    ma_result result = ma_decoder_init_file(audio_path.string().c_str(), &config, &decoder);
    if (result != MA_SUCCESS) {
        throw std::runtime_error("Failed to open audio file: " + audio_path.string() +
                                 " (error: " + std::to_string(result) + ")");
    }

    // Get total frame count
    ma_uint64 total_frames;
    result = ma_decoder_get_length_in_pcm_frames(&decoder, &total_frames);
    if (result != MA_SUCCESS) {
        // If we can't get length, decode in chunks
        total_frames = 0;
    }

    std::vector<float> samples;
    if (total_frames > 0) {
        samples.reserve(static_cast<size_t>(total_frames));
    }

    // Decode in chunks
    const size_t chunk_size = 16000;  // 1 second at 16kHz
    std::vector<float> chunk(chunk_size);

    while (true) {
        ma_uint64 frames_read;
        result = ma_decoder_read_pcm_frames(&decoder, chunk.data(), chunk_size, &frames_read);
        if (frames_read == 0) break;

        samples.insert(samples.end(), chunk.begin(), chunk.begin() + frames_read);

        if (result != MA_SUCCESS) break;
    }

    ma_decoder_uninit(&decoder);
    return samples;
}
