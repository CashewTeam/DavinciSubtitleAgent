# Environment Setup for Subtitle Agent

This guide explains how to prepare Windows x64 and macOS environments for Subtitle Agent without relying on a prebuilt app.

Scope:

- Windows 10/11 x64
- macOS
- Subtitle Agent source checkout
- DaVinci Resolve installed locally

## Windows 10/11 x64

### 1. Install Python and project dependencies

Install 64-bit Python 3.12 and make sure the Python Launcher (`py.exe`) is available. In PowerShell, from the project directory:

```powershell
py -3.12 -m venv venv
.\venv\Scripts\python.exe -m pip install --upgrade pip setuptools wheel
.\venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 2. Install ffmpeg

Install a Windows ffmpeg build and add the directory containing `ffmpeg.exe` to the user or system `PATH`. Restart Resolve and Subtitle Agent after changing PATH. Verify in PowerShell:

```powershell
ffmpeg -version
ffprobe -version
```

The initialization panel checks for ffmpeg and displays setup instructions if it is missing; it does not install a Windows package manager or download ffmpeg.

### 3. Configure Resolve scripting

Enable external scripting in DaVinci Resolve preferences. The app uses these default locations:

```text
%PROGRAMDATA%\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting
%PROGRAMFILES%\Blackmagic Design\DaVinci Resolve\fusionscript.dll
```

On Windows, the scripting modules remain under `%PROGRAMDATA%`. The app locates `fusionscript.dll` beside a running Resolve process, then checks the standard Blackmagic folder on fixed drives. If an existing `RESOLVE_SCRIPT_LIB` points to a missing file, automatic detection continues. For an unusual folder layout or when automatic detection cannot find it, set user environment variables before starting Resolve. Example for a custom installation:

```powershell
[Environment]::SetEnvironmentVariable('RESOLVE_SCRIPT_API', "$env:ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting", 'User')
[Environment]::SetEnvironmentVariable('RESOLVE_SCRIPT_LIB', 'D:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll', 'User')
```

Restart Resolve and Subtitle Agent after changing these values. The app adds the `Modules` directory to Python's module search path and the library directory to the DLL search path.

### 4. Run from source

```powershell
.\run_ui_debug.ps1
```

Source CLI commands use the same Python environment:

```powershell
.\venv\Scripts\python.exe subtitle_agent_app.py --help
.\venv\Scripts\python.exe subtitle_agent_app.py read "D:\项目\字幕.srt"
```

The app stores its config and downloaded alignment model under:

```text
%LOCALAPPDATA%\SubtitleAgent
```

To expose the launcher in Resolve's Scripts menu, copy `SubtitleAgent.py` to Resolve's Utility Scripts directory:

```text
%PROGRAMDATA%\Blackmagic Design\DaVinci Resolve\Fusion\Scripts\Utility
```

Then point it to the packaged GUI and restart Resolve:

```powershell
[Environment]::SetEnvironmentVariable('SUBTITLE_AGENT_EXE', 'E:\Apps\Subtitle Agent\Subtitle Agent.exe', 'User')
```

For source mode, set `SUBTITLE_AGENT_SCRIPT` to the project's `subtitle_agent_app.py` and `SUBTITLE_AGENT_PYTHON` to its `venv\Scripts\python.exe` instead.

### 5. Build the Windows app

Run the build on Windows x64 from the project's virtual environment:

```powershell
.\build_windows.ps1
```

The onedir output is `dist\windows\Subtitle Agent\`. It contains `Subtitle Agent.exe` for the GUI and `Subtitle Agent CLI.exe` for console commands. The build also creates a versioned ZIP in `dist\windows\` containing both entry points and the Windows x64 aligner runtime.

## macOS

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
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
```

This installs the source-mode dependencies used by:

- CustomTkinter GUI
- DashScope remote ASR
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
  "custom_output_dir": "~/Documents/asr",
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

## 5. Verify source mode

Run the app:

```bash
python3 subtitle_agent_app.py
```

Check the following:

1. The app opens normally.
2. Settings can be saved.
3. `远程 ASR` works after filling API key.
4. `Resolve 原生识别` works when Resolve is running and scripting is available.

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
- `openai`
- `requests`
- `zhconv`

Build-time package:

- `pyinstaller`
