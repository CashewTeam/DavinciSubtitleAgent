# Subtitle Agent for DaVinci Resolve

![Subtitle Agent UI](subagent.png)

Subtitle Agent 现已调整为 **macOS 主应用优先** 的字幕工具：主界面使用 CustomTkinter，支持双击 `.app` 打开；DaVinci Resolve 侧只保留一个极薄的 `Workspace -> Scripts -> SubtitleAgent` 桥接脚本，用于拉起主 app。

目前仅面向 macOS。Windows 暂未适配。

## 主要功能

- 连接当前 DaVinci Resolve 项目与时间线。
- 导出时间线音频、导出当前时间线字幕、导入最终 SRT 到时间线。
- 两种字幕识别模式：
  - 远程 ASR
  - Resolve 原生识别
- 使用 OpenAI 兼容接口接入 DashScope / DeepSeek 做 SRT 校对、翻译、参考文案优化。
- 在结果窗口中手动编辑 LLM 输出，再决定是否应用到主页。

## 快速开始

### 1. 安装 ffmpeg

```bash
brew install ffmpeg
```

确认可用：

```bash
ffmpeg -version
ffprobe -version
```

### 2. 一键启动 app

如果你已经有打包好的 app，直接双击启动即可：


### 3. 配置阿里云

远程 ASR 与 LLM 功能需要 DashScope API Key。

首次启动后在设置页填写：

- `DashScope API Key`
- `llm_model`
- `llm_base_url`

## 当前识别模式

主 app 只保留两种识别模式：

- `远程 ASR（云端识别）`
- `Resolve 原生识别（当前时间线）`

本地 ASR 与强制对齐已从 UI 和主流程中移除。


## 项目结构

```text
SubtitleAgent.py              # Resolve 菜单桥接启动器
subtitle_agent_app.py         # macOS app 兼容入口（GUI + CLI + bundled worker）
subtitle_agent_app/           # 主 app package
  main.py                     # 启动、CLI 分发、主 App 组装
  state.py                    # 运行状态初始化
  services.py                 # 文件读取与预览文本转换
  dialogs/result.py           # LLM 结果弹窗
  panels/workbench.py         # 工作台页面
  panels/editor.py            # 文案与 SRT 双栏编辑页
  panels/settings.py          # 设置页
  core/                       # 核心业务与 worker
    api.py                    # 对外统一接口
    worker.py                 # 外部 worker 入口
    resolve_ops.py            # Resolve 相关操作
    srt_ops.py                # SRT 解析/转换
    asr_ops.py                # 远程 ASR
    llm_ops.py                # LLM 校对/翻译/文案优化
subagent.png                  # UI 截图
subtitle_agent/
README.md
AGENT_ENV_SETUP.md
requirements.txt
SubtitleAgent.spec
build_macos_app.sh
run_ui_debug.sh
```

## 配置文件位置

app 与 worker 统一使用这个配置文件：

```text
~/Library/Application Support/SubtitleAgent/subtitle_agent_config.json
```

如果存在旧版配置：

```text
/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility/subtitle_agent/subtitle_agent_config.json
```

首次启动 app 时会自动迁移。



## 开发者

### 调试启动 UI

```bash
./run_ui_debug.sh
```

### 源码运行

```bash
python3 subtitle_agent_app.py
```

### 打包

先安装依赖：

```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
```

如果项目里已经有 `venv`，直接激活即可：

```bash
source venv/bin/activate
```

然后执行：

```bash
./build_macos_app.sh
```

产物默认位于：

```text
dist/Subtitle Agent.app
```

### CLI

主入口同时支持命令行：

```bash
APP_BIN="/Applications/Subtitle Agent.app/Contents/MacOS/Subtitle Agent"

# 远程 ASR
"$APP_BIN" asr audio.wav subtitles.srt

# 校对 SRT
"$APP_BIN" proofread input.srt output.srt

# 翻译 SRT
"$APP_BIN" translate input.srt output.srt --target en

# 优化参考文案
"$APP_BIN" optimize input.txt output.txt

# 简繁转换
"$APP_BIN" convert input.srt output.srt --lang zh-tw

# 查看 SRT
"$APP_BIN" read subtitles.srt
```

如果是源码模式调试，也可以继续使用：

```bash
python3 subtitle_agent_app.py read subtitles.srt
```

## 输出命名

输出文件会带模式后缀，例如：

```text
Project_subtitles_asr_remote_raw.srt
Project_subtitles_resolve_builtin_raw.srt
Project_subtitles_zh_cn.srt
Project_reference_optimized.txt
```

### 开发验证

```bash
python3 -m py_compile SubtitleAgent.py
python3 -m py_compile subtitle_agent_app.py
python3 -m py_compile subtitle_agent_app/core/*.py
```

更多环境手动配置说明见 [AGENT_ENV_SETUP.md](/Users/con11/Documents/GitHub/DavinciSubtitleAgent/AGENT_ENV_SETUP.md)。

## 常见问题

### Resolve 菜单点击后没反应

确认以下至少其一存在：

```text
dist/Subtitle Agent.app
subtitle_agent_app.py
```

### 找不到 ffmpeg

确认已经安装：

```bash
brew install ffmpeg
which ffmpeg
which ffprobe
```

### 打包后的 app 无法读到配置

确认配置文件位于：

```text
~/Library/Application Support/SubtitleAgent/subtitle_agent_config.json
```

不要再把运行配置写回源码目录下的 `subtitle_agent/` 子目录。
