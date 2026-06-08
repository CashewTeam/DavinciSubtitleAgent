# Environment Setup for Subtitle Agent

This guide walks through manually setting up Subtitle Agent's runtime environment on macOS without using a pre-packaged environment bundle.

Scope:
- macOS
- DaVinci Resolve with scripts already placed in the correct directory

## 1. Install Python from python.org

Do NOT use Homebrew Python as the external worker environment.

Download from: [https://www.python.org/downloads/](https://www.python.org/downloads/)

Recommended version: Python 3.11 or 3.12.

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

## 3. Create virtual environment and install dependencies

```bash
mkdir -p ~/Documents/subtitle_agent
python3 -m venv ~/Documents/subtitle_agent/venv
source ~/Documents/subtitle_agent/venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install openai dashscope
```

## 4. Configure Subtitle Agent

The config file is generated on first run at:

```text
/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility/subtitle_agent/subtitle_agent_config.json
```

Key fields:

```json
{
  "python_path": "~/Documents/subtitle_agent/venv/bin/python",
  "dashscope_api_key": "your-dashscope-api-key"
}
```

For LLM features (proofreading / translation / text optimization):

```json
{
  "llm_model": "deepseek-v4-flash",
  "llm_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1"
}
```

## 5. Verify

1. `Workspace -> Scripts -> SubtitleAgent` opens the UI.
2. Go to Settings and confirm `python_path` is set correctly.
3. Test with `远程 ASR` or `Resolve 内置字幕生成`.

## Dependencies

Only two Python packages are needed:

```
openai       — LLM proofreading / translation
dashscope    — cloud ASR via Alibaba Cloud DashScope
```

No FunASR, no PyTorch, no forced alignment models.
