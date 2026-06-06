# Subtitle Agent for DaVinci Resolve

Subtitle Agent 是一个运行在 DaVinci Resolve `Workspace -> Scripts` 菜单里的 macOS Python 字幕工具。它把音频导出、ASR 识别、文稿强制对齐、SRT 校对、翻译、参考文案优化和导入时间线集中到一个 Resolve UI 界面中。

目前仅面向 macOS。Windows 暂未适配。

## 主要功能

- 从当前 DaVinci Resolve 时间线导出音频。
- 使用参考文案进行强制对齐并生成 SRT。
- 使用 FunASR 云端 ASR 或本地 ASR 生成 SRT。
- 使用 Resolve 内置字幕识别并导出无格式 SRT。
- 使用 OpenAI 兼容接口接入 DashScope / DeepSeek 模型进行 SRT 校对。
- 将 SRT 翻译为指定目标语言，并按语言后缀保存文件。
- 优化参考文案，方便后续强制对齐。
- 预览、手动编辑 LLM 输出结果，再决定是否应用到主页 UI。
- 将最终 SRT 导入当前 DaVinci Resolve 时间线。

## 文件结构

```text
SubtitleAgent.py
subtitle_agent/
  subtitle_agent_core.tool
  subtitle_agent_config.json   # 本地配置，首次运行生成或由用户填写，不提交 git
README.md
.gitignore
```

`SubtitleAgent.py` 是 DaVinci Resolve 可识别的脚本入口。

`subtitle_agent/subtitle_agent_core.tool` 是核心模块和外部 worker。后缀使用 `.tool`，避免被 Resolve 当作脚本菜单项显示。

## 安装位置

把项目文件放到 DaVinci Resolve 的 Utility 脚本目录：

```text
/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility/
```

最终至少需要：

```text
/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility/SubtitleAgent.py
/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility/subtitle_agent/subtitle_agent_core.tool
```

重启 DaVinci Resolve 后，在：

```text
Workspace -> Scripts -> SubtitleAgent
```

打开脚本。

## 首次使用准备

### 1. 安装全局 Python

Resolve 内置 Python 只负责打开 UI 和调用 Resolve API。ASR、LLM、音频处理等重依赖任务会由外部 Python 环境执行。

请到 Python 官网下载 macOS installer：

[https://www.python.org/downloads/](https://www.python.org/downloads/)

不建议使用 Homebrew 安装的 Python 作为 DaVinci Resolve 脚本外部环境。DaVinci / Fusion 脚本环境在 macOS 上可能无法正确识别 brew Python 的路径和动态库布局。

确认可用：

```bash
python3 --version
```

### 2. 安装 ffmpeg

脚本会使用 ffmpeg 做音频转码、采样率转换和 WAV 兼容处理。

```bash
brew install ffmpeg
```

确认可用：

```bash
ffmpeg -version
ffprobe -version
```

脚本会自动把 `/opt/homebrew/bin` 和 `/usr/local/bin` 加入 worker 环境，解决 DaVinci 从 GUI 启动时找不到 Homebrew 命令的问题。

### 3. 解压打包好的 macOS ASR 环境

发布包会提供一个 macOS 版本的 `asr` 目录，里面包含：

- Python venv
- FunASR / OpenAI / DashScope 等依赖
- 模型缓存目录

推荐发布包按用户主目录结构打包，例如压缩包内包含：

```text
Documents/asr/
```

用户下载后解压到自己的用户主目录：

```text
~/
```

解压完成后实际路径应为：

```text
~/Documents/asr
```

结构类似：

```text
~/Documents/asr/
  venv/
    bin/python
  models/
```

配置中的默认路径为：

```text
python_path = ~/Documents/asr/venv/bin/python
cache_dir   = ~/Documents/asr
```

`cache_dir` 会被设置为 `MODELSCOPE_CACHE`。FunASR / ModelScope 会在这个缓存目录下自动查找和管理 `models` 子目录。

### 4. 配置 API Key

如果使用 FunASR 云端 ASR、LLM 校对、翻译、文案优化，需要配置 DashScope API Key。

首次运行后打开脚本里的 `设置`，填写：

```text
DashScope Key
```

也可以直接编辑：

```text
subtitle_agent/subtitle_agent_config.json
```

注意：该配置文件可能包含 API Key 和本机路径，已被 `.gitignore` 忽略，不应提交到 git。

## 推荐首次流程

1. 打开 DaVinci Resolve 项目和时间线。
2. 运行 `Workspace -> Scripts -> SubtitleAgent`。
3. 点击 `刷新状态`，确认当前项目、时间线和起始时码。
4. 如果时间线起始时码不是 `00:00:00:00`，点击 `修正起始时码`。
5. 设置输出目录。默认会输出到：

```text
~/Documents/asr/当前项目名称/
```

6. 选择当前模式：

```text
文稿匹配（强制对齐）
FunASR 云端 ASR
FunASR 本地 ASR
Resolve 内置字幕生成
```

7. 如果使用强制对齐，选择或粘贴参考文案。
8. 点击 `开始识别`。
9. 生成后可点击 `校对` 或 `翻译`，在右侧结果框中确认或手动修改，再点击 `应用结果`。
10. 点击 `导入 SRT 到时间线`。

## 输出文件命名

输出文件会带项目名前缀和处理方式后缀，例如：

```text
Project_audio_align.wav
Project_subtitles_align_raw.srt
Project_subtitles_asr_local_raw.srt
Project_subtitles_zh_cn.srt
Project_reference_optimized.txt
```

翻译结果会带目标语言后缀，避免多语言结果互相覆盖。

## 常见问题

### DaVinci 菜单里看不到脚本

确认 `SubtitleAgent.py` 直接位于 Resolve 的 `Utility` 脚本目录下，而不是嵌套在子文件夹里。

### 找不到 ffmpeg

确认已经安装：

```bash
brew install ffmpeg
```

并确认：

```bash
which ffmpeg
```

应该输出 `/opt/homebrew/bin/ffmpeg` 或 `/usr/local/bin/ffmpeg`。

### 本地 ASR 仍下载到 ~/.cache/modelscope

确认设置页里的 `cache_dir` 指向：

```text
~/Documents/asr
```

运行时日志应出现：

```text
Model cache directory: /Users/你的用户名/Documents/asr
```

旧缓存不会自动迁移，可以手动清理或重新下载。

### LLM 功能不可用

确认外部 Python 环境安装了 `openai`，并且设置里填写了 DashScope API Key。

## 开发说明

初始化或更新本项目后，建议运行：

```bash
python3 -m py_compile SubtitleAgent.py
python3 -m py_compile subtitle_agent/subtitle_agent_core.tool
```

不要把 `subtitle_agent/subtitle_agent_config.json`、模型、venv、音频、字幕输出文件提交到 git。
