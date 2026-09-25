# Windows 适配计划与实施记录

日期：2026-09-24  
状态：Windows x64 代码适配、打包、CLI/worker、Resolve 集成、强制对齐和正式目录包 GUI 启动烟测已完成；GUI 设置/文件流程、远程 API、实际录音质量及 macOS 回归仍待验收。

## 目标与范围

适配 Windows 10/11 x64，保留 GUI、CLI、远程 ASR、SRT/LLM 操作、DaVinci Resolve 集成和强制对齐能力。源码运行和 PyInstaller 目录包均提供 Windows 入口，并保留现有 macOS 构建入口。

本次构建环境为 Windows 11 x64（build 26100）和 Python 3.12.10。Windows Resolve Scripts 菜单启动入口已纳入实现。

## 实施结果

### 阶段 0：适配范围和外部依赖 — 已完成

- 目标定为 Windows 10/11 x64、Python 3.12 x64；当前本机实际构建使用 Python 3.12.10。
- Resolve 脚本 API 默认路径和 `fusionscript.dll` 自动定位已加入平台配置，并保留 `RESOLVE_SCRIPT_API`、`RESOLVE_SCRIPT_LIB` 手动覆盖。
- 已采用上游 `cpp-ctc-aligner` v0.2.2 Windows x64 构建；本机下载包 SHA-256 与 release 列出的值一致：`1d11b83b5086073524a3ebcb081ab6dca52753f6d751c950ddac2b4eee25a946`。
- 压缩包中的 `cpp-ort-aligner.exe`、`onnxruntime.dll` 和 `Chinese_to_Pinyin.txt` 已加入项目。原生程序报告版本 `0.2.2`；命令行参数及项目默认 Omnilingual 模型的 `model.int8.onnx` + `tokens.txt` 格式相符。

### 阶段 1：移除运行时 macOS 路径假设 — 已完成

- 新增 `subtitle_agent_app/platform_paths.py`，统一 Windows `%LOCALAPPDATA%\SubtitleAgent`、macOS Application Support 和 Resolve 默认路径。
- GUI、CLI 和 worker 通过同一配置路径；用户配置的输出目录仍然生效。
- 用独立线程读取 stdout/stderr 管道，去掉 Windows 不支持的 `select.select()` 管道监听方式。
- Windows worker 子进程输出显式使用 UTF-8，避免中文路径、日志和 JSON 字段按系统代码页解码。
- worker 继承当前系统 PATH，不再注入 Homebrew 或 Unix 路径。

### 阶段 2：Resolve 和 ffmpeg — 路径、API 连接和本地转换已验证

- Resolve API 模块目录、库路径和 DLL 搜索目录会同时传给主进程和 worker；缺少脚本模块时错误信息会显示当前使用的环境变量值。
- Windows 初始化面板显示 ffmpeg 安装说明，不调用 Homebrew。ffmpeg 与 ffprobe 均从当前 Windows PATH 检出。
- 当前 Resolve 安装在 `D:\Program Files\Blackmagic Design\DaVinci Resolve`，与 `%ProgramFiles%` 默认值不同。程序现优先从运行中的 Resolve 进程定位 DLL，并检查固定磁盘上的常见安装目录；清除两个 Resolve 环境变量或提供指向不存在文件的旧 DLL 路径后，仍自动发现 D 盘 DLL，Python 3.12.10 成功连接 Resolve 21.1.0.14。
- 本机 API 烟测确认工程和时间线可访问；在用户切换的测试工程中完成两条中文 SRT 字幕导入，并再次导出 SRT，文本与数量均匹配。
- 同一测试时间线成功导出音频：Resolve 生成的音频经 PATH 中的 ffmpeg 转为 WAV；ffprobe 确认输出为 48 kHz、双声道 PCM，时长约 168 秒。另以中文和空格路径的临时 WAV 验证了 `convert_to_wav`。
- 这两项操作只针对用户提供的测试副本；测试替换了副本的字幕轨道，并清空了副本的 Resolve 渲染队列。临时导出文件已清理。

### 阶段 3：Windows 强制对齐运行时 — 已完成端到端本机烟测

- 按操作系统选择 Windows x64 或 macOS 对齐器；Windows 包含 v0.2.2 EXE、ONNX Runtime DLL 和拼音表。
- Windows 路径不检查 Unix 可执行位；缺少平台对应二进制时报告明确错误。
- 打包目录中的对齐器资源已核对，`--version` 返回 `0.2.2`。
- 推荐 Omnilingual 模型已下载至 `%LOCALAPPDATA%\SubtitleAgent\models`（`model.int8.onnx` 约 365 MB，另含 `tokens.txt`）。
- Windows 中文语音合成生成的约 5.9 秒 WAV，分别通过源码和打包版 worker 完成强制对齐；打包版使用与 GUI 相同的 `romanize=False` 配置并生成 3 段 SRT。
- 对齐模型路径已保存到应用配置；打包版 CLI 不传 `--model-dir` 也能从配置加载模型并完成对齐。

### 阶段 4：Windows 构建和使用说明 — 已完成

- 新增独立的 `SubtitleAgentWindows.spec`，输出 PyInstaller onedir 包，不使用 macOS `BUNDLE`。
- 新增 `build_windows.ps1` 和 `run_ui_debug.ps1`。
- Windows 包同时提供 `Subtitle Agent.exe` GUI 和 `Subtitle Agent CLI.exe` 控制台入口。冻结版 worker 由 CLI 子进程运行；PyInstaller spec 同时收集 `zhconv` 运行词典。
- 构建脚本验证目录包中包含 `python312.dll` 与 VC Runtime DLL，并输出正式 GUI 启动路径；构建成功后会删除 workpath 中容易误点的中间 EXE。README 明确说明 `build/windows/SubtitleAgentWindows/` 不是运行目录。
- 新增 Resolve Scripts 菜单入口 `SubtitleAgent.py`；已验证入口能将含空格的 exe 路径作为一个参数交给 Windows。更新 README 与环境配置文档中的 Windows 安装、运行、构建及 Resolve 配置步骤。
- 本机执行 `build_windows.ps1` 成功，产物为 `dist/windows/Subtitle Agent/` 和 `dist/windows/SubtitleAgent_Windows_x64_2.1.1.zip`。
- GitHub Release 工作流仅手动触发，构建 ARM64 macOS 和 x64 Windows。Windows ARM64 构建已取消，不再包含其 runner、OpenSSL 构建依赖和对齐器二进制。

### 阶段 5：Windows 本机验收 — 部分完成

已验证：

- Python 3.12 源码 CLI 能读取位于中文和空格路径下的 SRT。
- 打包版控制台 CLI 能进行简繁转换；worker JSON 管道中的中文路径和字幕文本保持 UTF-8。
- 打包目录内 Windows 对齐器资源齐全，原生程序能报告 v0.2.2。
- 打包版 worker 使用完整 Omnilingual 模型完成中文语音强制对齐，成功生成保留中文文本的 SRT（3 段）。
- 打包版 worker 对本机 OpenAI-compatible mock 完成流式校对，中文事件和 SRT 替换均正确。
- 应用配置保存了已下载模型路径和 Windows 默认输出目录；未写入 API key。
- PyInstaller GUI/CLI 双入口目录包与版本化 ZIP 构建成功。
- `dist/windows/Subtitle Agent/Subtitle Agent.exe` 启动后窗口标题为 `Subtitle Agent`，并正常创建主窗口；同目录 CLI 的 `--help` 正常运行。正式 ZIP 已核实包含 `_internal/python312.dll`。用户截图中的路径指向 `build/windows/SubtitleAgentWindows/` 中间 EXE，该目录没有运行时 DLL；构建脚本现会在 ZIP 成功生成后删除这些中间 EXE。
- 将目录包复制到同时含中文和空格的路径后，CLI、简繁转换和对齐器仍可启动。
- 当前 Windows PATH 可解析 `ffmpeg.exe` 和 `ffprobe.exe`。
- Python 3.12.10 使用 Resolve 实际 DLL 路径成功连接 Resolve 21.1.0.14，并读取到活动工程和时间线。
- 清除 `RESOLVE_SCRIPT_API` 和 `RESOLVE_SCRIPT_LIB` 后，自动定位到 D 盘实际运行目录并连接 Resolve 21.1.0.14。
- `RESOLVE_SCRIPT_LIB` 指向不存在的默认 C 盘 DLL 时，会继续自动探测并选中 D 盘 DLL。
- 在用户切换的 Resolve 测试工程中成功导入 2 条中文 SRT 字幕，并通过脚本 API 导出后核对了两条原文。
- 测试时间线音频成功导出至中文和空格路径；ffmpeg 转码完成，ffprobe 检查为 `pcm_s16le`、48 kHz、双声道，时长约 168 秒。
- ffmpeg 成功转换中文路径下的临时 WAV 文件。

仍需完成：

- GUI 内保存设置及文件选择流程；将 `SubtitleAgent.py` 安装到 Resolve Scripts 菜单并验证启动。正式目录包 GUI 主窗口已通过启动烟测。
- 使用项目实际录音/时间线音频验收对齐质量；本次使用 Windows 中文 TTS 样本验证引擎和 SRT 输出。
- 带真实凭据的 DashScope ASR / LLM 请求；当前应用配置和环境中没有 DashScope API key，本次仅用本机 mock 验证 LLM 流程。
- 在 macOS 主机确认源码运行和原有 macOS 打包无回归。

## 交付文件

- `subtitle_agent_app/platform_paths.py`：平台数据目录和 Resolve 环境路径。
- `subtitle_agent_app/cpp-ort-aligner-windows-x64/`：上游 Windows x64 对齐器运行资源。
- `SubtitleAgentWindows.spec`：Windows GUI/CLI 目录包规格。
- `build_windows.ps1`、`run_ui_debug.ps1`：Windows 构建和源码启动脚本。
- `SubtitleAgent.py`：Resolve Scripts 菜单启动入口。
- `README.md`、`AGENT_ENV_SETUP.md`：用户和开发者环境说明。

## 验收结论与边界

Windows 代码适配、x64 打包、正式目录包 GUI 启动、CLI/worker UTF-8 通信、简繁 SRT 转换、中文模型强制对齐、中文空格路径迁移、非默认 D 盘 Resolve 自动发现与连接、测试工程字幕导入/导出和时间线音频导出及 ffmpeg 转换已通过当前主机烟测。完整产品验收仍需覆盖 GUI 设置/文件操作、Resolve 菜单启动、带凭据的远程 API、实际项目录音的对齐质量，以及 macOS 主机回归；这些部分目前不标记为已验证。

## 参考

- [cpp-ctc-aligner v0.2.2 Release](https://github.com/corvo007/cpp-ctc-aligner/releases/tag/v0.2.2)：`cpp-ort-aligner-windows-x64.zip`（SHA-256：`1d11b83b5086073524a3ebcb081ab6dca52753f6d751c950ddac2b4eee25a946`）；另有 arm64 构建（SHA-256：`0d38851fb4d3905ab4ef7edf6d0455cca5ee9270a749d6a86b20d2e9079f1544`）。
- [Resolve Windows 脚本 API 路径示例（Blackmagic Design 论坛）](https://forum.blackmagicdesign.com/viewtopic.php?p=655735&t=78611)
- [Resolve Windows 环境变量示例（Blackmagic Design 论坛）](https://forum.blackmagicdesign.com/viewtopic.php?f=21&t=91850)
