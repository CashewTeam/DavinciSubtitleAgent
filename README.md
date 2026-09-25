# Subtitle Agent for DaVinci Resolve

![Subtitle Agent UI](subagent.png)

Subtitle Agent 使用 CustomTkinter，支持 macOS ARM64 和 Windows x64。Windows 使用 PyInstaller 目录包；macOS 使用 `.app`。

## 主要功能

- 连接当前 DaVinci Resolve 项目与时间线。
- 导出时间线音频、导出当前时间线字幕、导入最终 SRT 到时间线。
- 三种字幕识别模式：
  - 远程 ASR
  - 强制对齐
  - Resolve 原生识别
- 使用 OpenAI 兼容接口接入 DashScope / DeepSeek 做 SRT 校对、翻译、参考文案优化。
- 在结果窗口中手动编辑 LLM 输出，再决定是否应用到主页。
- 强制对齐使用 [corvo007/cpp-ctc-aligner](https://github.com/corvo007/cpp-ctc-aligner) 的平台原生 release 产物。仓库包含 macOS ARM64 和 Windows x64 运行文件。
- 推荐初始化模型为 [csukuangfj2/sherpa-onnx-omnilingual-asr-1600-languages-300M-ctc-int8-2025-11-12](https://huggingface.co/csukuangfj2/sherpa-onnx-omnilingual-asr-1600-languages-300M-ctc-int8-2025-11-12)。

## 快速开始

### 1. 启动 app

Windows：在 Windows x64 主机运行 `build_windows.ps1` 后，双击 `dist/windows/Subtitle Agent/Subtitle Agent.exe`；源码模式使用 `run_ui_debug.ps1`。macOS：双击 `Subtitle Agent.app`。

Windows 只运行 `dist\windows\Subtitle Agent\` 目录中的程序，或从 ZIP 解压后的同名目录启动。`build\windows\SubtitleAgentWindows\` 是 PyInstaller 中间工作目录，其中生成的 EXE 缺少运行时文件，不能直接启动。

Windows 目录包同时提供控制台 CLI：

```powershell
& ".\dist\windows\Subtitle Agent\Subtitle Agent CLI.exe" --help
& ".\dist\windows\Subtitle Agent\Subtitle Agent CLI.exe" read "D:\项目\字幕.srt"
```

macOS 首次打开若被系统拦截，请按 macOS 打包说明处理隔离标记。

### 2. 打开初始化面板

启动 app 后，在首页点击 `初始化`。

初始化面板可以：

- 检查 `ffmpeg` 和强制对齐模型状态；macOS 另外检查 `Homebrew`
- 在 macOS 上通过 Homebrew 安装 `ffmpeg`；Windows 上显示安装说明，需将 `ffmpeg.exe` 所在目录加入 PATH
- 下载推荐 Omnilingual ONNX 对齐模型
- 保存基础 LLM 配置

推荐模型下载源：

- 镜像优先：`https://hf-mirror.com/csukuangfj2/sherpa-onnx-omnilingual-asr-1600-languages-300M-ctc-int8-2025-11-12`
- 官方回退：`https://huggingface.co/csukuangfj2/sherpa-onnx-omnilingual-asr-1600-languages-300M-ctc-int8-2025-11-12`

## 当前识别模式

主 app 当前提供三种识别模式：

- `远程 ASR（云端识别）`
- `强制对齐（参考文案 + 音频）`
- `Resolve 原生识别（当前时间线）`

其中强制对齐默认可通过初始化面板自动下载 Omnilingual ONNX 模型；如果手动配置本地模型目录，目录内需至少满足以下之一：

- `model.int8.onnx` + `tokens.txt`
- `model.onnx` + `vocab.json`


## 项目结构

```text
subtitle_agent_app.py         # GUI、CLI 和 bundled worker 入口
SubtitleAgent.py               # DaVinci Resolve Scripts 菜单启动入口
subtitle_agent_app/           # 主 app package
  platform_paths.py            # 用户数据与 Resolve 路径
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
    align_ops.py              # 强制对齐
    llm_ops.py                # LLM 校对/翻译/文案优化
  cpp-ort-aligner-macos-arm64/
  cpp-ort-aligner-windows-x64/
subagent.png                  # UI 截图
README.md
AGENT_ENV_SETUP.md
requirements.txt
SubtitleAgent.spec
SubtitleAgentWindows.spec
build_macos_app.sh
run_ui_debug.sh
build_windows.ps1
run_ui_debug.ps1
```

## 配置文件位置

app、CLI 与 worker 使用同一个配置文件。Windows：

```text
%LOCALAPPDATA%\SubtitleAgent\subtitle_agent_config.json
```

macOS：

```text
~/Library/Application Support/SubtitleAgent/subtitle_agent_config.json
```

如果存在旧版配置：

```text
/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility/subtitle_agent/subtitle_agent_config.json
```

首次启动 app 时会自动迁移项目目录中的旧配置。
## 开发者
<details>
<summary><strong>折叠内容</strong></summary>

### 调试启动 UI

Windows PowerShell：

```powershell
py -3.12 -m venv venv
.\venv\Scripts\python.exe -m pip install --upgrade pip setuptools wheel
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\run_ui_debug.ps1
```

macOS：

```bash
./run_ui_debug.sh
```

### 源码运行

```bash
python3 subtitle_agent_app.py
```

### 打包

Windows x64 或 ARM64：在相应架构的 Windows 上安装项目依赖后运行：

```powershell
.\build_windows.ps1
```

正式产物位于 `dist/windows/Subtitle Agent/`，并生成 `dist/windows/SubtitleAgent_Windows_<x64|ARM64>_2.1.1.zip`。请从该目录（或解压后的完整目录）启动 `Subtitle Agent.exe`；不要启动 `build/windows/SubtitleAgentWindows/` 中的中间 EXE。
目录包内包含 GUI、控制台 CLI、Python 运行时 DLL、Windows 对齐器 EXE、ONNX Runtime DLL 和拼音表。

macOS：

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

默认还会额外生成一个适合 adhoc 分发的压缩包：

```text
dist/SubtitleAgent_macOS_ARM64_<APP_VERSION>.zip
```

压缩包内包含：

- `Subtitle Agent.app`
- `fix_quarantine.command`

对方机器如果首次打开被系统拦截，可以先双击 `fix_quarantine.command`，它会自动执行：

```bash
xattr -dr com.apple.quarantine "Subtitle Agent.app"
```

如果要给其他 macOS 机器稳定分发，建议用 `Developer ID Application` 证书签名并做 notarization。

最少需要：

```bash
export MACOS_CODESIGN_IDENTITY="Developer ID Application: Your Name (TEAMID)"
```

如果你已经配置了 `notarytool` keychain profile：

```bash
export MACOS_NOTARYTOOL_PROFILE="AC_PASSWORD_PROFILE"
./build_macos_app.sh
```

或者直接使用 Apple 凭据：

```bash
export MACOS_CODESIGN_IDENTITY="Developer ID Application: Your Name (TEAMID)"
export MACOS_NOTARY_APPLE_ID="you@example.com"
export MACOS_NOTARY_TEAM_ID="TEAMID"
export MACOS_NOTARY_PASSWORD="app-specific-password"
./build_macos_app.sh
```

单独对已打包好的 app 做签名/公证也可以：

```bash
./sign_macos_app.sh "dist/Subtitle Agent.app"
```

成功后会额外生成：

```text
dist/Subtitle Agent.zip
```

这个 zip 用于 notarization 提交；完成后脚本会自动 `staple` 回 `.app`。

### 手动发布 GitHub Release

仓库的 `.github/workflows/release.yml` 仅配置 `workflow_dispatch`。在 GitHub Actions 页面手动运行 **Manual Release**，工作流会读取 `subtitle_agent_app/main.py` 中的 `APP_VERSION`，分别在 ARM64 macOS 和 Windows x64 runner 上构建，并创建 `v<APP_VERSION>` Release，附上两个安装包和 `SHA256SUMS.txt`。发布新版本前先更新 `APP_VERSION`；如果同名 Release 已存在，发布步骤会失败，不会覆盖旧 Release。

GitHub Actions 默认生成未签名的 macOS 应用；压缩包包含 `fix_quarantine.command`。如需 Developer ID 签名和 notarization，需另行配置 Apple 证书与凭据。

### Resolve 脚本菜单（Windows）

将 `SubtitleAgent.py` 复制到 Resolve 的 Utility Scripts 目录：

```text
%PROGRAMDATA%\Blackmagic Design\DaVinci Resolve\Fusion\Scripts\Utility
```

设置 `SUBTITLE_AGENT_EXE` 用户环境变量指向目录包中的 `Subtitle Agent.exe`，然后重启 Resolve：

```powershell
[Environment]::SetEnvironmentVariable('SUBTITLE_AGENT_EXE', 'E:\Apps\Subtitle Agent\Subtitle Agent.exe', 'User')
```

Windows 启动后会优先从运行中的 Resolve 定位 `fusionscript.dll`，也会检查固定磁盘上的标准安装目录。仅当 Resolve 使用了非标准目录结构且未运行时，才需要手动设置 `RESOLVE_SCRIPT_LIB`。

源码模式可改为设置 `SUBTITLE_AGENT_SCRIPT` 指向项目的 `subtitle_agent_app.py`，并设置 `SUBTITLE_AGENT_PYTHON` 指向已安装依赖的 Python 3.12。

### CLI

Windows 目录包的控制台入口为 `Subtitle Agent CLI.exe`；macOS 打包入口和源码入口也支持 CLI。Windows 示例：

```powershell
& ".\dist\windows\Subtitle Agent\Subtitle Agent CLI.exe" --help
& ".\dist\windows\Subtitle Agent\Subtitle Agent CLI.exe" read "D:\项目\字幕.srt"
```

macOS 示例：

```bash
APP_BIN="/Applications/Subtitle Agent.app/Contents/MacOS/Subtitle Agent"

# 远程 ASR
"$APP_BIN" asr audio.wav subtitles.srt

# 强制对齐
"$APP_BIN" align audio.wav reference.txt aligned.srt --model-dir /path/to/model_dir

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
Project_subtitles_forced_alignment_raw.srt
Project_subtitles_resolve_builtin_raw.srt
Project_subtitles_zh_cn.srt
Project_reference_optimized.txt
```

### 开发验证

Windows PowerShell：

```powershell
& .\venv\Scripts\python.exe -m py_compile subtitle_agent_app.py SubtitleAgent.py
```

macOS：

```bash
python3 -m py_compile subtitle_agent_app.py
python3 -m py_compile subtitle_agent_app/core/*.py
```

更多环境手动配置说明见 [AGENT_ENV_SETUP.md](AGENT_ENV_SETUP.md)。

</details>

## 常见问题


### 找不到 ffmpeg

Windows PowerShell 中确认 `ffmpeg.exe` 和 `ffprobe.exe` 均在 PATH：

```powershell
Get-Command ffmpeg, ffprobe
ffmpeg -version
ffprobe -version
```

macOS：

```bash
brew install ffmpeg
which ffmpeg
which ffprobe
```

### 打包后的 app 无法读到配置

确认配置文件位于：

Windows：

```text
%LOCALAPPDATA%\SubtitleAgent\subtitle_agent_config.json
```

macOS：

```text
~/Library/Application Support/SubtitleAgent/subtitle_agent_config.json
```

不要再把运行配置写回源码目录下的 `subtitle_agent/` 子目录。
