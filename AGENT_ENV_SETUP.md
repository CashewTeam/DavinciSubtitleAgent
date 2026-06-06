# Agent Environment Setup for Subtitle Agent

这份文档面向 AI agent 或高级用户，目标是在 **不使用预打包 `~/Documents/asr` 环境** 的前提下，手动搭建 Subtitle Agent 所需的 macOS 运行环境。

适用范围：

- macOS
- DaVinci Resolve 脚本目录已正确放置
- 用户希望自己创建 `venv`、安装依赖、下载模型

当前不包含 Windows 适配说明。

## 目标目录结构

建议统一使用：

```text
~/Documents/asr/
  venv/
  models/
```

其中：

- `~/Documents/asr/venv`：外部 Python 虚拟环境
- `~/Documents/asr`：作为 `cache_dir`
- `~/Documents/asr/models`：FunASR / ModelScope 会在缓存目录下自动管理的模型子目录

## 1. 安装全局 Python

不要使用 Homebrew Python 作为 DaVinci Resolve 的外部脚本环境。

请从 Python 官网下载 macOS installer：

[https://www.python.org/downloads/](https://www.python.org/downloads/)

推荐版本：

- `Python 3.11`
- `Python 3.12`

原因：

- `torch`、`torchaudio`、`funasr`、`openai` 这些依赖在 3.11/3.12 上通常更稳
- DaVinci / Fusion 在 macOS 下对 python.org 安装版兼容性更好

安装后确认：

```bash
python3 --version
which python3
```

## 2. 安装 ffmpeg

```bash
brew install ffmpeg
```

确认：

```bash
ffmpeg -version
ffprobe -version
```

Subtitle Agent 会在 worker 环境里自动补充：

```text
/opt/homebrew/bin
/usr/local/bin
```

所以 DaVinci 从 GUI 启动时也能找到 `ffmpeg`。

## 3. 创建 asr 目录和 venv

```bash
mkdir -p ~/Documents/asr
mkdir -p ~/Documents/asr/models
python3 -m venv ~/Documents/asr/venv
source ~/Documents/asr/venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
```

## 4. 安装 Python 依赖

先安装 PyTorch CPU 版常用依赖：

```bash
pip install torch torchaudio
```

再安装 Subtitle Agent 需要的依赖：

```bash
pip install funasr openai dashscope requests zhconv toml tomli
```

如果某些环境里 `funasr` 对额外依赖有要求，可以补装：

```bash
pip install modelscope
```

安装完成后可以做一个基础检查：

```bash
python - <<'PY'
import torch
import torchaudio
import funasr
import openai
import dashscope
print("torch:", torch.__version__)
print("torchaudio:", torchaudio.__version__)
print("funasr:", getattr(funasr, "__version__", "unknown"))
print("openai ok")
print("dashscope ok")
PY
```

## 5. 配置 Subtitle Agent

脚本首次运行后会在下面位置生成或读取配置：

```text
/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility/subtitle_agent/subtitle_agent_config.json
```

建议确保这些关键字段如下：

```json
{
  "python_path": "~/Documents/asr/venv/bin/python",
  "cache_dir": "~/Documents/asr",
  "local_model_name": "paraformer-zh",
  "local_device": "cpu",
  "align_model": "fa-zh",
  "align_device": "cpu"
}
```

说明：

- `python_path`：DaVinci 启动外部 worker 时使用的 Python
- `cache_dir`：会被脚本设置成 `MODELSCOPE_CACHE`
- FunASR / ModelScope 会在这个缓存目录下自动查找和管理 `models` 子目录

如果需要云端 ASR / LLM：

```json
{
  "dashscope_api_key": "你的 DashScope Key",
  "llm_model": "deepseek-v4-flash",
  "llm_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1"
}
```

## 6. 预下载本地 ASR 模型

最简单的方法是直接打开 DaVinci Resolve，运行 Subtitle Agent，然后选择：

```text
当前模式 -> FunASR 本地 ASR
```

首次跑一段短音频即可触发模型下载。

运行时日志里应看到：

```text
Model cache directory: /Users/你的用户名/Documents/asr
Loading local ASR model
```

下载完成后，缓存目录下会逐步出现 ModelScope / FunASR 管理的模型文件。

## 7. 预下载强制对齐模型

同样建议直接通过 Subtitle Agent 触发：

```text
当前模式 -> 文稿匹配（强制对齐）
```

给一段短音频和一份参考文稿，首次执行会下载对齐模型。

运行时日志里应看到：

```text
Model cache directory: /Users/你的用户名/Documents/asr
Loading align model: fa-zh
```

## 8. 验证环境

建议按下面顺序验证：

1. `Workspace -> Scripts -> SubtitleAgent` 能正常打开 UI
2. 设置页中的 `python_path` 指向 `~/Documents/asr/venv/bin/python`
3. 设置页中的 `cache_dir` 指向 `~/Documents/asr`
4. 选择一条短时间线，测试：
   `Resolve 内置字幕生成`
5. 再测试：
   `FunASR 本地 ASR`
6. 最后测试：
   `文稿匹配（强制对齐）`

## 9. 推荐给 agent 的执行顺序

如果让 AI agent 帮用户自动搭环境，建议按下面顺序执行：

1. 确认系统是 macOS。
2. 确认用户已安装 python.org 版本的 Python。
3. 检查 `ffmpeg` / `ffprobe` 是否存在。
4. 创建 `~/Documents/asr`、`~/Documents/asr/models`、`~/Documents/asr/venv`。
5. 安装 Python 依赖。
6. 写入或更新 `subtitle_agent_config.json` 中的：
   `python_path`
   `cache_dir`
   `local_model_name`
   `align_model`
7. 通过 Subtitle Agent 执行一次本地 ASR，触发模型下载。
8. 通过 Subtitle Agent 执行一次强制对齐，触发对齐模型下载。

## 10. 常见问题

### DaVinci 能打开脚本，但识别时报找不到 Python

检查：

```text
python_path = ~/Documents/asr/venv/bin/python
```

并确认该文件存在：

```bash
ls ~/Documents/asr/venv/bin/python
```

### 仍然下载到 ~/.cache/modelscope

检查设置页里的：

```text
cache_dir = ~/Documents/asr
```

运行时日志应出现：

```text
Model cache directory: /Users/你的用户名/Documents/asr
```

如果旧缓存已经存在，ModelScope 不会主动迁移它。后续新下载内容会走新的缓存目录。

### funasr 安装成功，但本地 ASR 仍失败

先在 venv 中手动测试：

```bash
source ~/Documents/asr/venv/bin/activate
python - <<'PY'
from funasr import AutoModel
print("funasr import ok")
PY
```

如果 `torch` 或 `torchaudio` 缺失，重新安装：

```bash
pip install torch torchaudio
```

### 强制对齐模型 fa-zh 无法加载

先确认当前使用的是脚本里配置的外部 Python，而不是系统其他 Python。再检查：

```text
cache_dir
align_model
align_device
```

默认建议：

```text
align_model = fa-zh
align_device = cpu
```

## 11. 适合补充给用户的说明

如果用户不想手动配环境，直接提供打包好的：

```text
~/Documents/asr
```

仍然是最省心的方案。

如果用户希望完全由 AI 帮他重建环境，这份文档就是最适合的执行基线。
