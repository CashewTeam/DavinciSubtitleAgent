# Environment Setup for Subtitle Agent

This guide explains how to prepare a macOS environment for Subtitle Agent **without** using a prebuilt app bundle.

Scope:

- macOS
- Subtitle Agent source checkout
- DaVinci Resolve installed locally

## 1. Install Python from python.org

Do not use Homebrew Python as the primary worker environment.

Download from:

[https://www.python.org/downloads/](https://www.python.org/downloads/)

Recommended: Python 3.11 or 3.12.

Verify:

```bash
python3 --version
which python3
```

## 2. Install ffmpeg

```bash
brew install ffmpeg
```

Verify:

```bash
ffmpeg -version
ffprobe -version
```

## 3. Create a virtual environment

```bash
mkdir -p ~/Documents/asr
python3 -m venv ~/Documents/asr/venv
source ~/Documents/asr/venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
```

This installs the source-mode dependencies used by:

- CustomTkinter GUI
- DashScope remote ASR
- FunASR forced alignment
- OpenAI-compatible LLM proofreading / translation / text optimization
- PyInstaller packaging

## 4. Configure Subtitle Agent

The app stores runtime configuration at:

```text
~/Library/Application Support/SubtitleAgent/subtitle_agent_config.json
```

Minimum recommended fields:

```json
{
  "python_path": "~/Documents/asr/venv/bin/python",
  "custom_output_dir": "~/Documents/asr",
  "cache_dir": "~/Documents/asr",
  "dashscope_api_key": "your-dashscope-api-key"
}
```

LLM defaults:

```json
{
  "llm_model": "deepseek-v4-flash",
  "llm_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1"
}
```

Forced alignment defaults:

```json
{
  "align_model": "fa-zh",
  "align_device": "cpu"
}
```

## 5. Verify source mode

Run the app:

```bash
python3 subtitle_agent_app.py
```

Check the following:

1. The app opens normally.
2. Settings can be saved.
3. `远程 ASR` works after filling API key.
4. `强制对齐（Beta）` works after providing WAV + reference text.
5. `Resolve 原生识别` works when Resolve is running and scripting is available.

## 6. Verify Resolve bridge

Place the repo in:

```text
/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility/
```

Then restart Resolve and click:

```text
Workspace -> Scripts -> SubtitleAgent
```

Expected behavior:

- If `dist/Subtitle Agent.app` exists, Resolve launches that app.
- Otherwise Resolve launches `subtitle_agent_app.py`.

## 7. Build the macOS app

```bash
./build_macos_app.sh
```

Expected output:

```text
dist/Subtitle Agent.app
```

## Dependency summary

Required runtime packages from `requirements.txt`:

- `customtkinter`
- `dashscope`
- `funasr`
- `openai`
- `requests`
- `zhconv`

Build-time package:

- `pyinstaller`
