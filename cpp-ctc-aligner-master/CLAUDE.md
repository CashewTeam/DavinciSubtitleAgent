# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

cpp-ort-aligner is a standalone C++ tool for CTC forced alignment of subtitles to audio. It uses ONNX Runtime for Wav2Vec2-CTC inference and supports multiple audio formats via miniaudio.

## Build Commands

### Windows (recommended)
```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1
```

### Manual build (Developer Command Prompt)
```bat
cmake -S . -B build -G Ninja -DUSE_SYSTEM_ORT=ON -DONNXRUNTIME_DIR=models\onnxruntime-win-x64-1.23.2
cmake --build build -j 8
```

Output: `build-Release-Ninja-Multi-Config/Release/cpp-ort-aligner.exe`

### CI smoke test
The binary returns exit code 2 when invoked without arguments (usage message).

## Architecture

### Processing Pipeline
```
Audio File → decode_audio_to_16k_mono() → generate_emissions_ort() → forced_align() → merge_repeats_str() → get_spans_str() → postprocess_results() → Output SRT/JSON
```

### Key Components

**Audio Processing** (`audio_decode.cpp`)
- Uses miniaudio (header-only) for decoding MP3/WAV/FLAC
- Resamples to 16kHz mono float samples

**Emissions Generation** (`emissions.cpp`)
- Runs ONNX Runtime inference on Wav2Vec2-CTC model
- Windowed processing (30s windows, 2s context overlap)
- Batched inference support

**Forced Alignment** (`forced_align.cpp`)
- Viterbi-style CTC forced alignment
- Produces frame-level path and per-frame scores

**Span Alignment** (`span_align.cpp`)
- `merge_repeats_str()`: Collapses repeated tokens in path
- `get_spans_str()`: Maps tokens to frame spans

**Text Preprocessing** (`text_preprocess.cpp`)
- Tokenizes text for CTC alignment
- Handles `<star>` token insertion between segments

**Romanization** (CJK support)
- `kana_romaji.cpp`: Japanese kana → romaji
- `kanji_pinyin.cpp`: Chinese kanji → pinyin (requires `Chinese_to_Pinyin.txt`)
- `hangul_romaji.cpp`: Korean hangul → romaji

**I/O**
- `srt_io.cpp`: SRT file parsing/writing
- `json_io.cpp`: JSON input/output format
- `vocab_json.cpp`: Loads model vocabulary

### Data Structures

- `Emissions`: Frame-level log probabilities (T×C matrix)
- `SrtSegment`: Subtitle segment with timing and confidence score
- `WordTimestamp`: Per-word/character timing result
- `SegmentStr`/`SegmentSpanStr`: Intermediate alignment structures

## Dependencies

- **ONNX Runtime 1.23.2**: Bundled in `models/onnxruntime-win-x64-1.23.2/`
- **nlohmann/json**: Header-only in `include/nlohmann/json.hpp`
- **miniaudio**: Header-only in `include/miniaudio.h`

## Model Files

Two model families are supported, auto-detected by `detect_model_config()` in `model_config.cpp`:

| Model | Directory | Vocab | Tokens | Romanization | CJK Support |
|-------|-----------|-------|--------|-------------|-------------|
| MMS-300M | `models/mms-300m-1130-forced-aligner/` | `vocab.json` | 31 (a-z + special) | Required | Via kana→romaji, kanji→pinyin |
| Omnilingual-300M | `models/sherpa-onnx-omnilingual-...-int8-.../` | `tokens.txt` | 9,812 | Not needed | Native (hiragana/kanji in vocab) |

**MMS-300M files**: `model.onnx` + `model.onnx.data` + `vocab.json`
**Omnilingual files**: `model.int8.onnx` + `tokens.txt`
**CJK romanization data**: `data/Chinese_to_Pinyin.txt` (needed only for MMS + CJK languages)

## Scripts

| Script | Purpose |
|--------|---------|
| `scripts/build_windows.ps1` | One-click Windows build (sets up vcvars, cmake, ninja) |
| `scripts/compare_srt_timestamps.py` | Compare two SRT files with configurable time tolerance |
| `scripts/export_onnx.py` | Export PyTorch model to ONNX format |
| `scripts/quantize_model.py` | Quantize ONNX model to int8 |

## Regression Testing

### Smoke test (no model needed)

```bash
./build-Release-Ninja-Multi-Config/Release/cpp-ort-aligner.exe
# Expected: usage message, exit code 2
```

### Full regression test

Test data: `output.wav` (109.8s Japanese audio) + `output.wav.srt` (11 segments)

**MMS-300M** (romanization path — tests `align_and_map_batch` with token expansion):
```bash
./build-Release-Ninja-Multi-Config/Release/cpp-ort-aligner.exe \
  --audio output.wav \
  --model models/mms-300m-1130-forced-aligner \
  --srt output.wav.srt \
  --language jpn --romanize \
  --pinyin-table data/Chinese_to_Pinyin.txt \
  --output output_aligned.srt --debug --debug-dir output_debug
```

**Omnilingual-300M** (native CJK path — no romanization):
```bash
./build-Release-Ninja-Multi-Config/Release/cpp-ort-aligner.exe \
  --audio output.wav \
  --model models/sherpa-onnx-omnilingual-asr-1600-languages-300M-ctc-int8-2025-11-12 \
  --srt output.wav.srt \
  --language jpn \
  --output output_aligned_omni.srt --debug --debug-dir output_debug_omni
```

**Expected**: exit code 0, aligned SRT with `{score: ...}` per segment. Typical scores: MMS ~0.5-0.8, Omnilingual ~0.8-0.98 for Japanese.

### Compare results

```bash
python scripts/compare_srt_timestamps.py output.wav.srt output_aligned.srt
```

### What to verify after changes

| Change Area | Test |
|-------------|------|
| Any `main.cpp` change | Both model regression tests |
| `text_preprocess.cpp` | MMS test (romanize path) + Omnilingual test |
| `forced_align.cpp` / `span_align.cpp` | Both models |
| `emissions.cpp` | Both models (different vocab sizes: 32 vs 9813) |
| `model_config.cpp` / `vocab*.cpp` | Both models |
| Build system only | Smoke test sufficient |

## Key Design Decisions

### Sub-batch splitting (`align_and_map_batch`)

CTC forced alignment requires `T >= L + R` (frames >= targets + repeated-token count). When romanization expands CJK text (e.g., 320 Japanese segments → 19,000+ tokens > 12,383 frames), the function recursively splits segments at their midpoint using original Whisper timestamps for frame boundaries. Single-segment fallback prevents infinite recursion. Guard `frame_cnt < 2` prevents degenerate splits.

### Model auto-detection

`detect_model_config()` checks for `vocab.json` (MMS) vs `tokens.txt` (Omnilingual) and `model.onnx` vs `model.int8.onnx`. The `requires_romanization` flag controls whether CJK text goes through kana→romaji/kanji→pinyin conversion.
