# cpp-ort-aligner

A standalone C++ tool for CTC forced alignment of subtitles to audio.

## Features

- **Native audio decoding**: Supports MP3, WAV, FLAC, and other formats via miniaudio (no FFmpeg required)
- **Pure C++ romanization**: Built-in kana/kanji romanization for CJK languages (no Python required)
- **ONNX Runtime inference**: Fast Wav2Vec2-CTC inference with multi-threading support
- **JSON I/O**: Supports both SRT and JSON input/output formats
- **Confidence scores**: Outputs alignment confidence scores for each segment

## Prerequisites (Windows)

1. **Visual Studio Build Tools** (Desktop development with C++)
   - MSVC build tools (x64)
   - Windows 10/11 SDK
   - CMake + Ninja (comes with VS Build Tools)

2. **ONNX Runtime package** (vendored in this repo)
   - `cpp-ort-aligner/models/onnxruntime-win-x64-1.23.2/`

3. **Model files** (placed in this repo)
   - `cpp-ort-aligner/models/mms-300m-1130-forced-aligner/model.onnx`
   - `cpp-ort-aligner/models/mms-300m-1130-forced-aligner/model.onnx.data`
   - `cpp-ort-aligner/models/mms-300m-1130-forced-aligner/vocab.json`

4. **Kanji pinyin table** (for CJK romanization)
   - `<exe_dir>/Chinese_to_Pinyin.txt` (default location, bundled in release packages)
   - Or specify custom path with `--pinyin-table`

## Build

### Option A (recommended): PowerShell build script

```powershell
cd D:\onedrive\codelab\ctc-forced-aligner
powershell -ExecutionPolicy Bypass -File cpp-ort-aligner\scripts\build_windows.ps1
```

### Option B: Manual (Developer Command Prompt)

```bat
cd D:\onedrive\codelab\ctc-forced-aligner\cpp-ort-aligner

cmake -S . -B build -G Ninja ^
  -DUSE_SYSTEM_ORT=ON ^
  -DONNXRUNTIME_DIR=D:\onedrive\codelab\ctc-forced-aligner\cpp-ort-aligner\models\onnxruntime-win-x64-1.23.2

cmake --build build -j 8
```

Output: `cpp-ort-aligner/build-Release-Ninja-Multi-Config/Release/cpp-ort-aligner.exe`

## CI (GitHub Actions)

The repo includes a GitHub Actions workflow that builds `cpp-ort-aligner` in a small OS matrix and performs a basic smoke test
(invoking the binary without args and expecting the usage exit code).

## Usage

```
Usage:
  cpp-ort-aligner --audio <path> --model <model_dir> [--srt <path> | --json-input <path|-}] [options]

Input/Output:
  --audio, -a           Audio file path
  --model, -m           Local model directory (contains model.onnx + vocab.json)
  --srt, -s             Input SRT file (required unless using --json-input)
  --output, -o          Output SRT path (default: <input>_aligned.srt)
  --json-input, -ji     JSON input path (use '-' for stdin)
  --json-output, -jo    JSON output path (use '-' for stdout)

Alignment options:
  --language, -l        ISO 639-3 code (default: eng)
  --romanize, -r        Enable romanization
  --pinyin-table        Kanji-to-pinyin table path (default: <exe_dir>/Chinese_to_Pinyin.txt)
  --batch-size, -b      Inference batch size (default: 4)
  --threads             ORT intra-op threads (default: auto)

Debug:
  --debug, -d           Enable debug mode and save intermediate files
  --debug-dir           Debug output directory (default: <base>_debug)
```

### Examples

**SRT mode (Japanese with romanization):**
```bat
cpp-ort-aligner.exe ^
  --audio audio.mp3 ^
  --model models\mms-300m-1130-forced-aligner ^
  --srt subtitles.srt ^
  --output aligned.srt ^
  --language jpn ^
  --romanize
```

**JSON mode (Chinese):**
```bat
cpp-ort-aligner.exe ^
  --audio audio.wav ^
  --model models\mms-300m-1130-forced-aligner ^
  --json-input input.json ^
  --json-output output.json ^
  --language cmn ^
  --romanize
```

**Pipe mode (stdin/stdout):**
```bat
echo {"segments":[{"text":"Hello world"}]} | cpp-ort-aligner.exe ^
  --audio audio.wav ^
  --model models\mms-300m-1130-forced-aligner ^
  --json-input - ^
  --json-output -
```

## JSON Format

### Input
```json
{
  "segments": [
    {"text": "First subtitle line"},
    {"text": "Second subtitle line"}
  ]
}
```

### Output
```json
{
  "segments": [
    {
      "text": "First subtitle line",
      "start": 1.23,
      "end": 4.56,
      "score": -0.123
    }
  ],
  "audio_duration": 60.0
}
```

## Language Support

- **English** (`eng`): Word-level alignment
- **Japanese** (`jpn`): Character-level with kana romanization
- **Chinese** (`cmn`, `zho`, `chi`): Character-level with pinyin romanization
- **Korean** (`kor`): Character-level alignment

For CJK languages, use `--romanize` to enable romanization.

## Troubleshooting

- **Missing DLLs**: Ensure `onnxruntime.dll` is next to the executable
- **Kanji table not found**: Place `Chinese_to_Pinyin.txt` next to the executable, or use `--pinyin-table` to specify a custom path
- **Audio decode fails**: Verify the audio file is not corrupted and is a supported format
