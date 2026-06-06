#!/usr/bin/env python3

import json
import os
import select
import subprocess
import sys
import tempfile
import traceback
import importlib
import importlib.util
import time
from importlib.machinery import SourceFileLoader


SCRIPT_ID = "com.codex.resolve.SubtitleAgent.v3"
LEGACY_SCRIPT_IDS = [
    "com.codex.resolve.SubtitleAgent",
    "com.codex.resolve.SubtitleAgent.v2",
]
APP_VERSION = "2026-06-06.35"

MODE_LABELS = [
    ("align", "文稿匹配（强制对齐）"),
    ("asr_remote", "FunASR 云端 ASR"),
    ("asr_local", "FunASR 本地 ASR"),
    ("resolve_builtin", "Resolve 内置字幕生成"),
]
MODE_LABEL_TO_KEY = dict((label, key) for key, label in MODE_LABELS)
MODE_KEY_TO_LABEL = dict(MODE_LABELS)


DEFAULT_PROOFREAD_PROMPT = (
    "请作为专业影视字幕校对编辑，对每条字幕进行精修：修正错别字、ASR 误识别、断句、"
    "标点、中英空格、口语不顺和明显术语错误；保持原意、语气、人物称呼和专有名词一致；"
    "避免过度改写，字幕应简洁自然，适合屏幕阅读。不要改变序号和时码。"
)
DEFAULT_TRANSLATE_PROMPT = (
    "请将每条字幕翻译为目标语言 {target_lang}。要求：自然口语、影视字幕风格、简洁易读；"
    "保留人物称呼、专有名词和上下文语气；不要解释，不要改变序号和时码。"
)
DEFAULT_OPTIMIZE_PROMPT = (
    "请优化参考文案，使其更适合字幕强制对齐：修正错别字、明显标点问题、多余空白和不利于对齐的断行，"
    "如果单行文本过长，使用逗号拆分为两句，专有英语名词首字母大写，以及修正其他英文大小写错误；"
    "保留原始语义、顺序、人物称呼和专有名词。只输出优化后的纯文本，不要解释。"
)


def _resolve_script_dir():
    candidates = []
    if "__file__" in globals() and __file__:
        candidates.append(__file__)
    if getattr(sys, "argv", None) and sys.argv and sys.argv[0]:
        candidates.append(sys.argv[0])
    main_mod = sys.modules.get("__main__")
    if main_mod is not None:
        main_file = getattr(main_mod, "__file__", None)
        if main_file:
            candidates.append(main_file)
    for candidate in candidates:
        try:
            abs_path = os.path.abspath(candidate)
            if os.path.exists(abs_path):
                return os.path.dirname(abs_path)
        except Exception:
            pass
    return "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility"


SCRIPT_DIR = _resolve_script_dir()
AGENT_DIR = os.path.join(SCRIPT_DIR, "subtitle_agent")
CORE_PATH = os.path.join(AGENT_DIR, "subtitle_agent_core.tool")
CONFIG_PATH = os.path.join(AGENT_DIR, "subtitle_agent_config.json")


def default_user_asr_dir():
    return os.path.expanduser("~/Documents/asr")


def default_user_asr_dir_token():
    return "~/Documents/asr"


def expand_user_path(path):
    return os.path.expanduser(path) if path else path


def compact_user_path(path):
    if not path:
        return path
    home = os.path.expanduser("~")
    abs_path = os.path.abspath(os.path.expanduser(path))
    if abs_path == home:
        return "~"
    if abs_path.startswith(home + os.sep):
        return "~" + abs_path[len(home) :]
    return path


def load_core_module():
    module_name = "subtitle_agent_core_embedded"
    loader = SourceFileLoader(module_name, CORE_PATH)
    spec = importlib.util.spec_from_loader(module_name, loader)
    if spec is None:
        raise RuntimeError("Failed to create import spec for %s" % CORE_PATH)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


core = load_core_module()


def ensure_config():
    os.makedirs(AGENT_DIR, exist_ok=True)
    if os.path.isfile(CONFIG_PATH):
        return
    base_dir_token = default_user_asr_dir_token()
    default_python_path = base_dir_token + "/venv/bin/python"
    default_cache_dir = base_dir_token
    with open(CONFIG_PATH, "w", encoding="utf-8") as handle:
        json.dump(
            {
                "python_path": default_python_path,
                "output_dir_mode": "custom",
                "custom_output_dir": base_dir_token,
                "dashscope_api_key": "",
                "region": "cn",
                "default_lang": "zh",
                "default_max_words": 0,
                "default_max_chars": 24,
                "default_chars_per_line": 24,
                "local_model_name": "paraformer-zh",
                "local_device": "cpu",
                "cache_dir": default_cache_dir,
                "align_model": "fa-zh",
                "align_device": "cpu",
                "llm_model": "deepseek-v4-flash",
                "llm_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "llm_enable_thinking": True,
                "llm_proofread_prompt": DEFAULT_PROOFREAD_PROMPT,
                "llm_translate_prompt": DEFAULT_TRANSLATE_PROMPT,
                "llm_optimize_prompt": DEFAULT_OPTIMIZE_PROMPT,
            },
            handle,
            ensure_ascii=False,
            indent=2,
        )


def load_config():
    ensure_config()
    with open(CONFIG_PATH, "r", encoding="utf-8") as handle:
        config = json.load(handle)
    base_dir = default_user_asr_dir()
    if not config.get("python_path"):
        config["python_path"] = os.path.join(base_dir, "bin", "python")
    if not config.get("cache_dir"):
        config["cache_dir"] = base_dir
    if not config.get("custom_output_dir"):
        config["custom_output_dir"] = base_dir
    if not config.get("output_dir_mode"):
        config["output_dir_mode"] = "custom"
    if not config.get("llm_model"):
        config["llm_model"] = "deepseek-v4-flash"
    if not config.get("llm_base_url"):
        config["llm_base_url"] = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    if "llm_enable_thinking" not in config:
        config["llm_enable_thinking"] = True
    if not config.get("llm_proofread_prompt"):
        config["llm_proofread_prompt"] = DEFAULT_PROOFREAD_PROMPT
    if not config.get("llm_translate_prompt"):
        config["llm_translate_prompt"] = DEFAULT_TRANSLATE_PROMPT
    if not config.get("llm_optimize_prompt"):
        config["llm_optimize_prompt"] = DEFAULT_OPTIMIZE_PROMPT
    config.pop("corrections_path", None)
    config.pop("corrections_json", None)
    for key in ("python_path", "custom_output_dir", "cache_dir"):
        config[key] = expand_user_path(config.get(key))
    return config


def get_fusion():
    if "fusion" in globals():
        return globals()["fusion"]
    resolve = core._get_resolve()
    if resolve and hasattr(resolve, "Fusion"):
        return resolve.Fusion()
    raise RuntimeError("Fusion UIManager is not available in this Resolve scripting context")


def get_bmd_module():
    if "bmd" in globals():
        return globals()["bmd"]
    try:
        return importlib.import_module("fusionscript")
    except Exception:
        raise RuntimeError("bmd / fusionscript module is not available in this Resolve scripting context")


def get_ui_manager(fusion_obj):
    manager = getattr(fusion_obj, "UIManager", None)
    if manager is None:
        raise RuntimeError("Fusion UIManager is not available in this Resolve scripting context")
    if callable(manager):
        instance = manager()
        if instance is not None:
            return instance
    return manager


FUSION = get_fusion()
BMD = get_bmd_module()
UI = get_ui_manager(FUSION)
DISPATCHER = BMD.UIDispatcher(UI)


def _normalize_dialog_result(value):
    if value is None:
        return ""
    text = str(value)
    return "" if text == "None" else text


def request_file_load():
    try:
        return _normalize_dialog_result(FUSION.RequestFile())
    except Exception:
        return ""


def request_file_save():
    try:
        return _normalize_dialog_result(FUSION.RequestFile("", "", {"FReqS_Save": True}))
    except Exception:
        return ""


def request_dir():
    try:
        return _normalize_dialog_result(FUSION.RequestDir())
    except Exception:
        return ""


class SubtitleAgentApp(object):
    def __init__(self):
        self.config = load_config()
        self.state = {
            "context": None,
            "raw_srt": "",
            "processed_srt": "",
            "final_srt": "",
            "audio_path": "",
            "auto_output_dir": "",
            "output_dir_overridden": False,
        }
        self.items = None
        self.window = None
        self.progress_window = None
        self.progress_items = None
        self.progress_apply_callback = None
        self.progress_save_callback = None
        self.progress_stream_output_to_result = False
        self.progress_dialog_counter = 0

    def create_window(self):
        for legacy_id in LEGACY_SCRIPT_IDS:
            legacy = UI.FindWindow(legacy_id)
            if legacy:
                try:
                    legacy.Close()
                except Exception:
                    pass
        existing = UI.FindWindow(SCRIPT_ID)
        if existing:
            try:
                existing.Close()
            except Exception:
                pass

        win = DISPATCHER.AddWindow(
            {
                "ID": SCRIPT_ID,
                "WindowTitle": "Subtitle Agent",
                "Geometry": [100, 80, 1380, 980],
            },
            UI.VGroup(
                {"Spacing": 8},
                [
                    self._status_group(),
                    self._wizard_group(),
                    self._action_group(),
                    self._log_group(),
                ],
            ),
        )
        self.window = win
        self.items = win.GetItems()
        self._connect_handlers()
        self._populate_defaults()
        self.refresh_status()
        self.log("Subtitle Agent loaded. Version: %s" % APP_VERSION)
        self.log("Script path: %s" % os.path.join(SCRIPT_DIR, "SubtitleAgent.py"))
        self.log("Core path: %s" % CORE_PATH)
        self.log("Audio export mode: external worker")
        if not self.config.get("python_path"):
            self.log("Config missing python_path. Edit %s before using ASR/align features." % CONFIG_PATH)
        return win

    def _status_group(self):
        return UI.VGroup(
            {"Weight": 0, "Spacing": 4},
            [
                UI.Label({"ID": "statusTitleLabel", "Text": "Step 1 · 初始化", "StyleSheet": "font-weight: bold; font-size: 14px;"}),
                UI.HGroup(
                    {"Weight": 0, "Spacing": 6},
                    [
                        UI.Label({"Text": "Resolve", "Weight": 0}),
                        UI.LineEdit({"ID": "resolveVersion", "ReadOnly": True, "Weight": 1}),
                        UI.Label({"Text": "Project", "Weight": 0}),
                        UI.LineEdit({"ID": "projectName", "ReadOnly": True, "Weight": 1}),
                        UI.Label({"Text": "Timeline", "Weight": 0}),
                        UI.LineEdit({"ID": "currentTimeline", "ReadOnly": True, "Weight": 1}),
                        UI.Label({"Text": "Start TC", "Weight": 0}),
                        UI.LineEdit({"ID": "startTc", "ReadOnly": True, "Weight": 1}),
                    ],
                ),
                UI.HGroup(
                    {"Weight": 0, "Spacing": 6},
                    [
                        UI.ComboBox({"ID": "timelineCombo", "Weight": 2}),
                        UI.Button({"ID": "refreshStatusBtn", "Text": "刷新状态", "Weight": 0}),
                        UI.Button({"ID": "switchTimelineBtn", "Text": "切换时间线", "Weight": 0}),
                        UI.Button({"ID": "fixTimecodeBtn", "Text": "修正起始时码", "Weight": 0}),
                    ],
                ),
            ],
        )

    def _wizard_group(self):
        return UI.VGroup(
            {"Weight": 2, "Spacing": 4},
            [
                UI.Label({"Text": "Step 2 · 准备素材", "StyleSheet": "font-weight: bold; font-size: 14px;"}),
                UI.HGroup(
                    {"Weight": 0, "Spacing": 6},
                    [
                        UI.Label({"Text": "输出目录", "Weight": 0}),
                        UI.LineEdit({"ID": "outputDirEdit", "Weight": 3}),
                        UI.Button({"ID": "browseOutputDirBtn", "Text": "选择目录", "Weight": 0}),
                        UI.Label({"Text": "前缀", "Weight": 0}),
                        UI.LineEdit({"ID": "outputPrefixEdit", "Weight": 1}),
                    ],
                ),
                UI.HGroup(
                    {"Weight": 0, "Spacing": 6},
                    [
                        UI.Label({"Text": "WAV 文件", "Weight": 0}),
                        UI.LineEdit({"ID": "wavPathEdit", "Weight": 3}),
                        UI.Button({"ID": "browseWavBtn", "Text": "选择 WAV", "Weight": 0}),
                        UI.Button({"ID": "clearWavBtn", "Text": "清空 WAV", "Weight": 0}),
                    ],
                ),
                UI.HGroup(
                    {"Weight": 0, "Spacing": 6},
                    [
                        UI.Label({"Text": "参考文稿", "Weight": 0}),
                        UI.LineEdit({"ID": "textPathEdit", "Weight": 3}),
                        UI.Button({"ID": "browseTextBtn", "Text": "选择文稿", "Weight": 0}),
                        UI.Button({"ID": "clearTextBtn", "Text": "清空文稿", "Weight": 0}),
                    ],
                ),
                UI.HGroup(
                    {"Weight": 0, "Spacing": 6},
                    [
                        UI.Label({"Text": "参考文案输入 / 编辑", "Weight": 1}),
                        UI.Button({"ID": "optimizeTextBtn", "Text": "优化文案", "Weight": 0}),
                    ],
                ),
                UI.VGroup(
                    {"Weight": 1, "Spacing": 0},
                    [
                        UI.TextEdit(
                            {
                                "ID": "textEditor",
                                "Weight": 1,
                                "PlaceholderText": "有参考文稿时可直接粘贴或编辑。留空则按设置中的识别模式执行 ASR。",
                            }
                        ),
                    ],
                ),
                UI.HGroup(
                    {"Weight": 0, "Spacing": 6},
                    [
                        UI.Label({"Text": "SRT 文件", "Weight": 0}),
                        UI.LineEdit({"ID": "srtPathEdit", "Weight": 3}),
                        UI.Button({"ID": "browseSrtBtn", "Text": "选择 SRT", "Weight": 0}),
                        UI.Button({"ID": "inlineSettingsBtn", "Text": "设置", "Weight": 0}),
                    ],
                ),
                UI.HGroup(
                    {"Weight": 0, "Spacing": 6},
                    [
                        UI.Label({"Text": "原始 SRT", "Weight": 0}),
                        UI.LineEdit({"ID": "rawSrtEdit", "ReadOnly": True, "Weight": 2}),
                        UI.Label({"Text": "处理后 SRT", "Weight": 0}),
                        UI.LineEdit({"ID": "processedSrtEdit", "ReadOnly": True, "Weight": 2}),
                    ],
                ),
            ],
        )

    def _action_group(self):
        return UI.VGroup(
            {"Weight": 0, "Spacing": 4},
            [
                UI.Label({"Text": "Step 3 · 执行", "StyleSheet": "font-weight: bold; font-size: 14px;"}),
                UI.HGroup(
                    {"Weight": 0, "Spacing": 6},
                    [
                        UI.Label({"Text": "当前模式", "Weight": 0}),
                        UI.ComboBox({"ID": "modeCombo", "Weight": 1}),
                        UI.Button({"ID": "generateBtn", "Text": "开始识别", "Weight": 0}),
                        UI.Button({"ID": "exportSrtBtn", "Text": "导出时间线字幕", "Weight": 0}),
                        UI.Button({"ID": "convertSrtBtn", "Text": "校对", "Weight": 0}),
                        UI.Button({"ID": "applyCorrectionsBtn", "Text": "翻译", "Weight": 0}),
                        UI.Button({"ID": "importSrtBtn", "Text": "导入 SRT 到时间线", "Weight": 0}),
                    ],
                ),
            ],
        )

    def _log_group(self):
        return UI.HGroup(
            {"Weight": 3, "Spacing": 6},
            [
                UI.VGroup(
                    {"Weight": 1, "Spacing": 1},
                    [
                        UI.Label({"Text": "日志", "Weight": 0, "MaximumSize": [16777215, 16], "StyleSheet": "font-size: 11px;"}),
                        UI.TextEdit({"ID": "logEdit", "ReadOnly": True, "Weight": 3, "MinimumSize": [0, 320]}),
                    ],
                ),
                UI.VGroup(
                    {"Weight": 1, "Spacing": 1},
                    [
                        UI.Label({"Text": "字幕预览", "Weight": 0, "MaximumSize": [16777215, 16], "StyleSheet": "font-size: 11px;"}),
                        UI.TextEdit({"ID": "previewEdit", "ReadOnly": True, "Weight": 3, "MinimumSize": [0, 320]}),
                    ],
                ),
            ],
        )

    def _populate_defaults(self):
        items = self.items
        items["outputDirEdit"].Text = self._default_output_dir()
        items["modeCombo"].AddItems([label for _, label in MODE_LABELS])
        self._select_mode_combo(self.config.get("recognition_mode", "align"))

    def _connect_handlers(self):
        win = self.window
        win.On[SCRIPT_ID].Close = self.on_close
        win.On["refreshStatusBtn"].Clicked = self.on_refresh
        win.On["switchTimelineBtn"].Clicked = self.on_switch_timeline
        win.On["fixTimecodeBtn"].Clicked = self.on_fix_timecode
        win.On["modeCombo"].CurrentIndexChanged = self.on_mode_changed
        win.On["browseOutputDirBtn"].Clicked = self.on_browse_output_dir
        win.On["browseWavBtn"].Clicked = self.on_browse_wav
        win.On["clearWavBtn"].Clicked = self.on_clear_wav
        win.On["browseTextBtn"].Clicked = self.on_browse_text
        win.On["clearTextBtn"].Clicked = self.on_clear_text
        win.On["optimizeTextBtn"].Clicked = self.on_optimize_text
        win.On["browseSrtBtn"].Clicked = self.on_browse_srt
        win.On["generateBtn"].Clicked = self.on_generate
        win.On["exportSrtBtn"].Clicked = self.on_export_srt
        win.On["inlineSettingsBtn"].Clicked = self.on_open_settings
        win.On["convertSrtBtn"].Clicked = self.on_convert_srt
        win.On["applyCorrectionsBtn"].Clicked = self.on_apply_corrections
        win.On["importSrtBtn"].Clicked = self.on_import_srt

    def _default_output_dir(self):
        return self._output_base_dir()

    def _output_base_dir(self):
        if self.config.get("output_dir_mode") == "custom" and self.config.get("custom_output_dir"):
            return self.config["custom_output_dir"]
        return default_user_asr_dir()

    def _project_output_dir(self, context=None):
        context = context or self.state.get("context") or {}
        project_name = context.get("project_name_safe") or context.get("project_name") or ""
        if project_name:
            project_name = core.sanitize_name(project_name)
            return os.path.join(self._output_base_dir(), project_name)
        return self._output_base_dir()

    def _set_auto_output_dir(self, context=None):
        output_dir = self._project_output_dir(context)
        self.state["auto_output_dir"] = output_dir
        if not self.state.get("output_dir_overridden"):
            self.items["outputDirEdit"].Text = output_dir

    def _current_mode_key(self):
        current = self.items["modeCombo"].CurrentText if self.items and "modeCombo" in self.items else ""
        if current in MODE_LABEL_TO_KEY:
            return MODE_LABEL_TO_KEY[current]
        if current in MODE_KEY_TO_LABEL:
            return current
        return self.config.get("recognition_mode", "align")

    def _mode_summary(self):
        mode_map = {
            "align": "当前模式：文稿匹配（强制对齐）",
            "asr_remote": "当前模式：FunASR 云端 ASR",
            "asr_local": "当前模式：FunASR 本地 ASR",
            "resolve_builtin": "当前模式：Resolve 内置字幕生成",
        }
        return mode_map.get(self._current_mode_key(), "当前模式：文稿匹配（强制对齐）")

    def _select_mode_combo(self, mode_key):
        self._select_combo_value(self.items["modeCombo"], MODE_KEY_TO_LABEL.get(mode_key, MODE_KEY_TO_LABEL["align"]))

    def log(self, message):
        self.items["logEdit"].Append(message)

    def set_preview(self, payload):
        if isinstance(payload, dict):
            content = payload.get("content")
            if content is not None:
                self.items["previewEdit"].PlainText = content
                return
            items = payload.get("items", [])
        else:
            items = payload or []
        lines = []
        for index, entry in enumerate(items, 1):
            start = entry.get("start") or entry.get("start_tc") or ""
            end = entry.get("end") or entry.get("end_tc") or ""
            text = entry.get("text", "")
            lines.append(str(entry.get("index") or index))
            lines.append("%s --> %s" % (start, end))
            lines.append(text)
            lines.append("")
        self.items["previewEdit"].PlainText = "\n".join(lines)

    def load_srt_preview_from_path(self, path):
        if not path:
            return
        try:
            with open(os.path.abspath(os.path.expanduser(path)), "r", encoding="utf-8-sig", errors="replace") as handle:
                content = handle.read()
            self.items["previewEdit"].PlainText = content
        except Exception as exc:
            self.log("Failed to load SRT preview: %s" % exc)

    def set_warning(self, text):
        if text:
            self.items["statusTitleLabel"].Text = "Step 1 · 初始化 | 警告：%s" % text
            self.items["statusTitleLabel"].StyleSheet = "font-weight: bold; font-size: 14px; color: #d9b44a;"
        else:
            self.items["statusTitleLabel"].Text = "Step 1 · 初始化"
            self.items["statusTitleLabel"].StyleSheet = "font-weight: bold; font-size: 14px;"

    def open_progress_dialog(self, title, with_result=False, stream_output_to_result=False):
        if self.progress_window:
            try:
                self.progress_window.Hide()
            except Exception:
                pass
        self.progress_dialog_counter += 1
        dialog_id = SCRIPT_ID + ".progress.%s.%s" % (self.progress_dialog_counter, int(time.time() * 1000))
        win = DISPATCHER.AddWindow(
            {"ID": dialog_id, "WindowTitle": title, "Geometry": [220, 180, 1040, 560]},
            UI.VGroup(
                {"Spacing": 6},
                [
                    UI.Label({"ID": "progressStageLabel", "Text": "准备中", "Weight": 0, "StyleSheet": "font-weight: bold; font-size: 14px;"}),
                    UI.Label({"ID": "reasoningLengthLabel", "Text": "思维链文本长度：0 字符", "Weight": 0, "StyleSheet": "font-size: 11px;"}),
                    UI.HGroup({"Weight": 1, "Spacing": 8}, [
                        UI.VGroup({"Weight": 1, "Spacing": 2}, [
                            UI.Label({"Text": "当前状态 / JSON 输出", "Weight": 0, "StyleSheet": "font-size: 11px;"}),
                            UI.TextEdit({"ID": "progressLogEdit", "ReadOnly": True, "Weight": 1}),
                        ]),
                        UI.VGroup({"ID": "progressResultGroup", "Weight": 1 if with_result else 0, "Spacing": 2}, [
                            UI.Label({"Text": "最终输出结果", "Weight": 0, "StyleSheet": "font-size: 11px;"}),
                            UI.TextEdit({"ID": "progressResultEdit", "ReadOnly": False, "Weight": 1}),
                        ]),
                    ]),
                    UI.HGroup({"Weight": 0, "Spacing": 6}, [
                        UI.Button({"ID": "progressApplyBtn", "Text": "应用结果（等待生成）", "Weight": 0}),
                        UI.Button({"ID": "progressCloseBtn", "Text": "关闭", "Weight": 0}),
                    ]),
                ],
            ),
        )
        self.progress_window = win
        self.progress_items = win.GetItems()
        self.progress_apply_callback = None
        self.progress_save_callback = None
        self.progress_stream_output_to_result = bool(stream_output_to_result)

        def close_dialog(ev):
            self.save_progress_result()
            win.Hide()
            if self.progress_window == win:
                self.progress_window = None

        def apply_dialog(ev):
            if not self.progress_apply_callback:
                self.progress_step("结果还未生成，暂不能应用")
                return
            try:
                self.save_progress_result()
                self.progress_apply_callback()
                win.Hide()
                if self.progress_window == win:
                    self.progress_window = None
            except Exception as exc:
                self.progress_step("应用结果失败：%s" % exc)

        win.On[dialog_id].Close = close_dialog
        win.On["progressCloseBtn"].Clicked = close_dialog
        win.On["progressApplyBtn"].Clicked = apply_dialog
        win.Show()
        try:
            win.Update()
            win.Repaint()
        except Exception:
            pass
        self.progress_step("初始化任务")
        return win

    def progress_step(self, message):
        self.log(message)
        if not self.progress_items:
            return
        self.progress_items["progressStageLabel"].Text = message
        self.progress_items["progressLogEdit"].Append(message)
        if self.progress_window:
            try:
                self.progress_window.Update()
                self.progress_window.Repaint()
            except Exception:
                pass

    def progress_output(self, text):
        if not self.progress_items:
            return
        if self.progress_stream_output_to_result and "progressResultEdit" in self.progress_items:
            current = self.progress_items["progressResultEdit"].PlainText or ""
            self.progress_items["progressResultEdit"].PlainText = current + (text or "")
        else:
            self.progress_items["progressLogEdit"].Append(text)
        if self.progress_window:
            try:
                self.progress_window.Update()
                self.progress_window.Repaint()
            except Exception:
                pass

    def update_reasoning_length(self, message):
        if not self.progress_items:
            return
        self.progress_items["reasoningLengthLabel"].Text = message
        if self.progress_window:
            try:
                self.progress_window.Update()
                self.progress_window.Repaint()
            except Exception:
                pass

    def finish_progress(self, success, message):
        prefix = "完成" if success else "失败"
        self.progress_step("%s：%s" % (prefix, message))

    def progress_result_text(self):
        if self.progress_items and "progressResultEdit" in self.progress_items:
            return self.progress_items["progressResultEdit"].PlainText or ""
        return ""

    def save_progress_result(self):
        if self.progress_save_callback:
            self.progress_save_callback(self.progress_result_text())

    def set_progress_result(self, text, apply_callback=None, save_callback=None):
        if not self.progress_items:
            return
        if "progressResultEdit" in self.progress_items:
            self.progress_items["progressResultEdit"].PlainText = text or ""
        self.progress_apply_callback = apply_callback
        self.progress_save_callback = save_callback
        if "progressApplyBtn" in self.progress_items:
            self.progress_items["progressApplyBtn"].Text = "应用结果" if apply_callback else "应用结果（无可应用内容）"
        if self.progress_window:
            try:
                self.progress_window.Update()
                self.progress_window.Repaint()
            except Exception:
                pass

    def path_for(self, suffix):
        output_dir = self.items["outputDirEdit"].Text.strip() or SCRIPT_DIR
        output_dir = os.path.abspath(os.path.expanduser(output_dir))
        os.makedirs(output_dir, exist_ok=True)
        prefix = self.items["outputPrefixEdit"].Text.strip() or "subtitle_agent"
        return os.path.join(output_dir, "%s_%s" % (prefix, suffix))

    def _safe_suffix(self, text):
        return core.sanitize_name(text or "output").lower()

    def _mode_output_suffix(self, mode=None):
        mode = mode or self._current_mode_key()
        mode_map = {
            "align": "align",
            "asr_remote": "asr_remote",
            "asr_local": "asr_local",
            "resolve_builtin": "resolve_builtin",
        }
        return mode_map.get(mode, self._safe_suffix(mode))

    def _read_text_file(self, path):
        with open(os.path.abspath(os.path.expanduser(path)), "r", encoding="utf-8-sig") as handle:
            return handle.read()

    def refresh_status(self):
        context = core.get_resolve_context()
        self.state["context"] = context
        self.items["resolveVersion"].Text = context["version"]["version_string"]
        self.items["projectName"].Text = context["project_name"]
        self.items["currentTimeline"].Text = context["current_timeline"]
        self.items["startTc"].Text = context["start_timecode"]
        if not self.items["outputPrefixEdit"].Text.strip():
            self.items["outputPrefixEdit"].Text = context["project_name_safe"]
        self._set_auto_output_dir(context)
        combo = self.items["timelineCombo"]
        combo.Clear()
        for timeline in context["timelines"]:
            combo.AddItem("%s. %s (%s)" % (timeline["index"], timeline["name"], timeline["start_timecode"]))
            if timeline["name"] == context["current_timeline"]:
                combo.CurrentIndex = combo.Count() - 1
        self.set_warning(context.get("warning", ""))

    def selected_timeline_index(self):
        text = self.items["timelineCombo"].CurrentText or ""
        try:
            return int(text.split(".", 1)[0])
        except Exception:
            return 1

    def ensure_python_path(self):
        python_path = (self.config.get("python_path") or "").strip()
        if not python_path:
            raise RuntimeError("subtitle_agent_config.json missing python_path")
        if not os.path.exists(python_path):
            raise RuntimeError("Configured python_path does not exist: %s" % python_path)
        return python_path

    def write_temp_file(self, suffix, content):
        fd, path = tempfile.mkstemp(prefix="subtitle_agent_", suffix=suffix)
        os.close(fd)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)
        return path

    def prepare_reference_text(self):
        editor_text = self.items["textEditor"].PlainText.strip()
        file_path = self.items["textPathEdit"].Text.strip()
        if editor_text:
            temp_path = self.write_temp_file(".txt", editor_text)
            self.log("Reference text staged to %s" % temp_path)
            return temp_path
        if file_path:
            return file_path
        raise RuntimeError("Reference text is required for align mode")

    def reference_text_content(self):
        editor_text = self.items["textEditor"].PlainText.strip()
        if editor_text:
            return editor_text
        file_path = self.items["textPathEdit"].Text.strip()
        if file_path:
            with open(os.path.abspath(os.path.expanduser(file_path)), "r", encoding="utf-8") as handle:
                return handle.read().strip()
        raise RuntimeError("Reference text is required")

    def optional_reference_text_content(self):
        try:
            return self.reference_text_content()
        except Exception:
            return ""

    def llm_job_defaults(self):
        return {
            "api_key": self.config.get("dashscope_api_key", ""),
            "base_url": self.config.get("llm_base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            "model": self.config.get("llm_model", "deepseek-v4-flash"),
            "enable_thinking": bool(self.config.get("llm_enable_thinking", True)),
            "proofread_prompt": self.config.get("llm_proofread_prompt", DEFAULT_PROOFREAD_PROMPT),
            "translate_prompt": self.config.get("llm_translate_prompt", DEFAULT_TRANSLATE_PROMPT),
            "optimize_prompt": self.config.get("llm_optimize_prompt", DEFAULT_OPTIMIZE_PROMPT),
        }

    def prepare_corrections_file(self):
        path = self.path_for("corrections.json")
        if not os.path.isfile(path):
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({}, handle, ensure_ascii=False, indent=2)
            self.log("Created runtime corrections JSON: %s" % path)
        return path

    def prepare_translation_file(self):
        path = self.path_for("translation.json")
        if not os.path.isfile(path):
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({}, handle, ensure_ascii=False, indent=2)
            raise RuntimeError("已生成翻译 JSON 模板，请先编辑这个文件后再点翻译: %s" % path)
        return path

    def _flush_worker_log_buffer(self, buffer, force=False):
        while True:
            newline = buffer.find("\n")
            carriage = buffer.find("\r")
            positions = [pos for pos in (newline, carriage) if pos >= 0]
            if not positions:
                break
            pos = min(positions)
            line = buffer[:pos].strip()
            buffer = buffer[pos + 1 :]
            if line:
                self.log(line)
        if force and buffer.strip():
            self.log(buffer.strip())
            return ""
        return buffer

    def run_worker(self, job):
        python_path = self.ensure_python_path()
        fd, job_path = tempfile.mkstemp(prefix="subtitle_agent_job_", suffix=".json")
        os.close(fd)
        with open(job_path, "w", encoding="utf-8") as handle:
            json.dump(job, handle, ensure_ascii=False, indent=2)
        cmd = [python_path, CORE_PATH, "worker", job_path]
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=SCRIPT_DIR,
            env=self._worker_env(),
        )
        stderr_buffer = ""
        stderr_fd = process.stderr.fileno()
        while process.poll() is None:
            ready, _, _ = select.select([stderr_fd], [], [], 0.2)
            if ready:
                chunk = os.read(stderr_fd, 4096)
                if chunk:
                    stderr_buffer += chunk.decode("utf-8", "replace")
                    stderr_buffer = self._flush_worker_log_buffer(stderr_buffer)
        remaining_stderr = process.stderr.read() if process.stderr else b""
        if remaining_stderr:
            stderr_buffer += remaining_stderr.decode("utf-8", "replace")
        stderr_buffer = self._flush_worker_log_buffer(stderr_buffer, force=True)
        stdout_bytes = process.stdout.read() if process.stdout else b""
        return_code = process.wait()
        stdout = (stdout_bytes or b"").decode("utf-8", "replace").strip()
        if not stdout:
            raise RuntimeError("Worker returned no output")
        try:
            payload = json.loads(stdout)
        except Exception:
            payload = None
            for candidate in reversed(stdout.splitlines()):
                try:
                    payload = json.loads(candidate)
                    self.log("Worker stdout contained extra text; recovered JSON result from final line.")
                    break
                except Exception:
                    pass
            if payload is None:
                raise RuntimeError("Worker output was not valid JSON: %s" % stdout[:400])
        if return_code != 0 and payload.get("success"):
            raise RuntimeError("Worker failed with exit code %s" % return_code)
        if not payload.get("success"):
            raise RuntimeError(payload.get("error", "Worker failed"))
        if not payload.get("logs_streamed"):
            for line in payload.get("logs", []):
                self.log(line)
        return payload

    def _worker_env(self):
        env = os.environ.copy()
        resolve_api = "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting"
        resolve_lib = "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so"
        env.setdefault("RESOLVE_SCRIPT_API", resolve_api)
        env.setdefault("RESOLVE_SCRIPT_LIB", resolve_lib)
        module_path = os.path.join(env["RESOLVE_SCRIPT_API"], "Modules")
        env["PYTHONPATH"] = module_path + os.pathsep + env.get("PYTHONPATH", "")
        tool_paths = ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin"]
        env["PATH"] = os.pathsep.join(tool_paths + [env.get("PATH", "")])
        cache_dir = (self.config.get("cache_dir") or "").strip()
        if cache_dir:
            cache_dir = os.path.abspath(os.path.expanduser(cache_dir))
            os.makedirs(cache_dir, exist_ok=True)
            env["MODELSCOPE_CACHE"] = cache_dir
            env["MODELSCOPE_HUB_CACHE"] = cache_dir
            env["FUNASR_CACHE"] = cache_dir
        if self.config.get("dashscope_api_key"):
            env["DASHSCOPE_API_KEY"] = self.config.get("dashscope_api_key")
        return env

    def run_streaming_worker(self, job):
        python_path = self.ensure_python_path()
        fd, job_path = tempfile.mkstemp(prefix="subtitle_agent_stream_job_", suffix=".json")
        os.close(fd)
        with open(job_path, "w", encoding="utf-8") as handle:
            json.dump(job, handle, ensure_ascii=False, indent=2)
        cmd = [python_path, CORE_PATH, "worker", job_path]
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=SCRIPT_DIR,
            env=self._worker_env(),
            bufsize=1,
        )
        result_payload = None
        stderr_lines = []
        for raw_line in process.stdout:
            line = raw_line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except Exception:
                self.progress_step(line)
                continue
            event_type = event.get("type")
            if event_type == "status":
                self.progress_step(event.get("message", ""))
            elif event_type == "reasoning_summary":
                self.update_reasoning_length(event.get("message", ""))
            elif event_type == "content_delta":
                self.progress_output(event.get("text", ""))
            elif event_type == "result":
                result_payload = event.get("payload")
            elif event_type == "error":
                process.wait()
                raise RuntimeError(event.get("message", "Streaming worker failed"))
        if process.stderr:
            stderr = process.stderr.read()
            if stderr:
                stderr_lines.append(stderr.strip())
        return_code = process.wait()
        for line in stderr_lines:
            if line:
                self.log(line)
        if return_code != 0:
            raise RuntimeError("Streaming worker failed with exit code %s" % return_code)
        if not result_payload:
            raise RuntimeError("Streaming worker returned no result")
        for line in result_payload.get("logs", []):
            self.log(line)
        return result_payload

    def update_srt_state(self, key, payload):
        self.state[key] = payload["path"]
        if key == "raw_srt":
            self.items["rawSrtEdit"].Text = payload["path"]
            self.items["srtPathEdit"].Text = payload["path"]
        elif key == "processed_srt":
            self.items["processedSrtEdit"].Text = payload["path"]
            self.items["srtPathEdit"].Text = payload["path"]
        self.set_preview(payload)

    def on_close(self, ev):
        DISPATCHER.ExitLoop()

    def on_refresh(self, ev):
        self.safe(self.refresh_status)

    def on_switch_timeline(self, ev):
        def action():
            result = core.set_current_timeline(self.selected_timeline_index())
            self.log("Timeline switched to %s" % result["name"])
            self.refresh_status()

        self.safe(action)

    def on_fix_timecode(self, ev):
        def action():
            result = core.fix_timecode()
            self.log("Timecode fixed: %s -> %s" % (result["old_timecode"], result["new_timecode"]))
            self.refresh_status()

        self.safe(action)

    def on_mode_changed(self, ev):
        self.config["recognition_mode"] = self._current_mode_key()
        self.log("Recognition mode set to %s" % self.config["recognition_mode"])

    def on_browse_output_dir(self, ev):
        selected = request_dir()
        if selected:
            self.state["output_dir_overridden"] = True
            self.items["outputDirEdit"].Text = selected

    def on_browse_wav(self, ev):
        selected = request_file_load()
        if selected:
            self.items["wavPathEdit"].Text = selected

    def on_clear_wav(self, ev):
        self.items["wavPathEdit"].Text = ""

    def on_browse_text(self, ev):
        selected = request_file_load()
        if selected:
            self.items["textPathEdit"].Text = selected
            try:
                with open(selected, "r", encoding="utf-8") as handle:
                    self.items["textEditor"].PlainText = handle.read()
            except Exception as exc:
                self.log("Failed to load reference text: %s" % exc)

    def on_browse_srt(self, ev):
        selected = request_file_load()
        if selected:
            self.items["srtPathEdit"].Text = selected
            self.load_srt_preview_from_path(selected)

    def on_clear_text(self, ev):
        self.items["textPathEdit"].Text = ""
        self.items["textEditor"].PlainText = ""

    def on_optimize_text(self, ev):
        def action():
            self.open_progress_dialog("Subtitle Agent 文案优化", with_result=True, stream_output_to_result=True)
            try:
                self.progress_step("读取参考文案")
                text = self.reference_text_content()
                job = self.llm_job_defaults()
                job.update(
                    {
                        "action": "llm_optimize_text",
                        "text": text,
                    }
                )
                self.progress_step("调用 LLM 优化参考文案")
                payload = self.run_streaming_worker(job)
                optimized = payload.get("text", "").strip()
                if not optimized:
                    raise RuntimeError("LLM returned empty optimized text")
                output_path = self.path_for("reference_optimized.txt")
                with open(output_path, "w", encoding="utf-8") as handle:
                    handle.write(optimized)

                def save_result(text):
                    with open(output_path, "w", encoding="utf-8") as handle:
                        handle.write(text)
                    self.log("Optimized reference text saved: %s" % output_path)

                def apply_result():
                    self.items["textEditor"].PlainText = self.progress_result_text()
                    self.log("Optimized reference text applied from %s" % output_path)

                self.set_progress_result(optimized, apply_result, save_result)
                self.finish_progress(True, "参考文案已生成并保存：%s" % output_path)
            except Exception as exc:
                self.finish_progress(False, str(exc))
                raise

        self.safe(action)

    def on_generate(self, ev):
        def action():
            try:
                mode = self._current_mode_key()
                mode_suffix = self._mode_output_suffix(mode)
                raw_srt_path = self.path_for("subtitles_%s_raw.srt" % mode_suffix)
                self.progress_step("识别模式：%s" % mode)
                if mode == "resolve_builtin":
                    self.progress_step("执行 Resolve 内置字幕生成")
                    result = core.generate_subtitles(int(self.config.get("default_chars_per_line", 24)))
                    self.log("Resolve generated %s subtitle items" % result["count"])
                    self.progress_step("写入原始 SRT")
                    exported = core.export_subtitles_srt(raw_srt_path)
                    self.progress_step("刷新 SRT 路径与预览")
                    self.update_srt_state("raw_srt", exported)
                    self.state["final_srt"] = exported["path"]
                    self.log("Raw SRT exported to %s" % exported["path"])
                    self.finish_progress(True, "原始 SRT 已生成：%s" % exported["path"])
                    return

                selected_wav = self.items["wavPathEdit"].Text.strip()
                if selected_wav:
                    self.progress_step("使用用户选择 WAV")
                    audio_path = os.path.abspath(os.path.expanduser(selected_wav))
                    if not os.path.isfile(audio_path):
                        raise RuntimeError("WAV file does not exist: %s" % audio_path)
                    if os.path.splitext(audio_path)[1].lower() != ".wav":
                        raise RuntimeError("Please choose a .wav file: %s" % audio_path)
                    self.log("Using selected WAV file: %s" % audio_path)
                else:
                    self.progress_step("导出时间线音频")
                    exported_audio = self.run_worker(
                        {
                            "action": "export_audio",
                            "output": self.path_for("audio_%s.wav" % mode_suffix),
                        }
                    )
                    audio_path = exported_audio["path"]
                    self.items["wavPathEdit"].Text = audio_path
                    self.log("Audio ready at %s" % audio_path)
                self.state["audio_path"] = audio_path

                if mode == "align":
                    self.progress_step("准备参考文稿")
                    text_path = self.prepare_reference_text()
                    self.progress_step("执行强制对齐")
                    payload = self.run_worker(
                        {
                            "action": "align",
                            "audio": audio_path,
                            "text": text_path,
                            "output": raw_srt_path,
                            "model": self.config.get("align_model", "fa-zh"),
                            "device": self.config.get("align_device", "cpu"),
                            "max_chars": int(self.config.get("default_max_chars", 24)),
                            "cache_dir": self.config.get("cache_dir", ""),
                        }
                    )
                elif mode == "asr_remote":
                    self.progress_step("执行云端 ASR")
                    payload = self.run_worker(
                        {
                            "action": "asr",
                            "audio": audio_path,
                            "output": raw_srt_path,
                            "lang": self.config.get("default_lang", "zh"),
                            "max_words": int(self.config.get("default_max_words", 0)),
                            "dashscope_api_key": self.config.get("dashscope_api_key", ""),
                            "region": self.config.get("region", "cn"),
                            "local": False,
                        }
                    )
                else:
                    self.progress_step("执行本地 ASR")
                    payload = self.run_worker(
                        {
                            "action": "asr",
                            "audio": audio_path,
                            "output": raw_srt_path,
                            "lang": self.config.get("default_lang", "zh"),
                            "max_words": int(self.config.get("default_max_words", 0)),
                            "local": True,
                            "model_name": self.config.get("local_model_name", "paraformer-zh"),
                            "device": self.config.get("local_device", "cpu"),
                            "cache_dir": self.config.get("cache_dir", ""),
                        }
                    )
                self.progress_step("写入原始 SRT")
                self.progress_step("刷新 SRT 路径与预览")
                self.update_srt_state("raw_srt", payload)
                self.state["final_srt"] = payload["path"]
                self.log("Raw SRT generated: %s (%s items)" % (payload["path"], payload["count"]))
                self.finish_progress(True, "原始 SRT 已生成：%s" % payload["path"])
            except Exception as exc:
                self.finish_progress(False, str(exc))
                raise

        self.safe(action)

    def on_export_srt(self, ev):
        def action():
            output_path = self.path_for("timeline_subtitles.srt")
            payload = core.export_subtitles_srt(output_path)
            self.update_srt_state("raw_srt", payload)
            self.state["final_srt"] = payload["path"]
            self.log("Current timeline subtitles exported to %s (%s items)" % (payload["path"], payload["count"]))

        self.safe(action)

    def on_import_srt(self, ev):
        def action():
            raw_path = self.items["srtPathEdit"].Text.strip()
            if not raw_path:
                raise RuntimeError("Please choose an SRT file first")
            srt_path = os.path.abspath(os.path.expanduser(raw_path))
            if not os.path.isfile(srt_path):
                raise RuntimeError("SRT file does not exist: %s" % srt_path)
            if os.path.splitext(srt_path)[1].lower() != ".srt":
                raise RuntimeError("Please choose a .srt file: %s" % srt_path)
            payload = core.import_srt(srt_path)
            self.state["final_srt"] = srt_path
            self.set_preview(payload)
            self.log("SRT imported to current timeline: %s (%s items)" % (srt_path, payload.get("count", 0)))

        self.safe(action)

    def on_convert_srt(self, ev):
        def action():
            self.open_progress_dialog("Subtitle Agent SRT 校对", with_result=True)
            try:
                srt_path = self.items["srtPathEdit"].Text.strip()
                if not srt_path:
                    raise RuntimeError("Please choose an SRT file first")
                self.items["srtPathEdit"].Text = srt_path
                output_path = self.path_for("subtitles_proofread.srt")
                json_path = self.path_for("proofread.json")
                reference_text = self.optional_reference_text_content()
                if reference_text:
                    self.progress_step("已附加参考文案上下文：%s 字符" % len(reference_text))
                job = self.llm_job_defaults()
                job.update(
                    {
                        "action": "llm_srt_edit",
                        "mode": "proofread",
                        "input": srt_path,
                        "output": output_path,
                        "json_output": json_path,
                        "target_lang": self.config.get("target_lang", "zh-cn"),
                        "reference_text": reference_text,
                    }
                )
                self.progress_step("调用 LLM 生成校对 JSON")
                payload = self.run_streaming_worker(job)
                result_text = self._read_text_file(payload["path"])

                def save_result(text):
                    with open(payload["path"], "w", encoding="utf-8") as handle:
                        handle.write(text)
                    self.log("Proofread SRT saved: %s" % payload["path"])

                def apply_result():
                    self.update_srt_state("processed_srt", payload)
                    self.state["final_srt"] = payload["path"]
                    self.log("Proofread SRT applied: %s" % payload["path"])

                self.set_progress_result(result_text, apply_result, save_result)
                self.finish_progress(True, "校对 SRT 已生成并保存：%s" % payload["path"])
            except Exception as exc:
                self.finish_progress(False, str(exc))
                raise

        self.safe(action)

    def on_apply_corrections(self, ev):
        self.open_translate_language_dialog()

    def open_translate_language_dialog(self):
        dialog_id = SCRIPT_ID + ".translate_language"
        existing = UI.FindWindow(dialog_id)
        if existing:
            existing.Show()
            existing.Raise()
            return
        win = DISPATCHER.AddWindow(
            {"ID": dialog_id, "WindowTitle": "选择翻译目标语言", "Geometry": [260, 220, 520, 180]},
            UI.VGroup(
                {"Spacing": 8},
                [
                    UI.Label({"Text": "目标语言", "Weight": 0}),
                    UI.HGroup({"Weight": 0, "Spacing": 6}, [
                        UI.ComboBox({"ID": "translateLangCombo", "Weight": 1}),
                        UI.LineEdit({"ID": "translateLangCustom", "PlaceholderText": "自定义，如 en / ja / zh-cn", "Weight": 1}),
                    ]),
                    UI.HGroup({"Weight": 0, "Spacing": 6}, [
                        UI.Button({"ID": "translateRunBtn", "Text": "开始翻译", "Weight": 0}),
                        UI.Button({"ID": "translateCancelBtn", "Text": "取消", "Weight": 0}),
                    ]),
                ],
            ),
        )
        items = win.GetItems()
        items["translateLangCombo"].AddItems(["zh-cn", "zh-tw", "zh-hk", "en", "ja", "ko"])
        self._select_combo_value(items["translateLangCombo"], self.config.get("target_lang", "zh-cn"))

        def close_dialog(ev):
            win.Hide()

        def run_dialog(ev):
            target_lang = items["translateLangCustom"].Text.strip() or items["translateLangCombo"].CurrentText or "zh-cn"
            self.config["target_lang"] = target_lang
            win.Hide()
            self.run_translation_with_lang(target_lang)

        win.On[dialog_id].Close = close_dialog
        win.On["translateCancelBtn"].Clicked = close_dialog
        win.On["translateRunBtn"].Clicked = run_dialog
        win.Show()

    def run_translation_with_lang(self, target_lang):
        def action():
            self.open_progress_dialog("Subtitle Agent SRT 翻译", with_result=True)
            try:
                srt_path = self.items["srtPathEdit"].Text.strip()
                if not srt_path:
                    raise RuntimeError("Please choose an SRT file first")
                lang_suffix = self._safe_suffix(target_lang)
                output_path = self.path_for("subtitles_%s.srt" % lang_suffix)
                json_path = self.path_for("translation_%s.json" % lang_suffix)
                job = self.llm_job_defaults()
                job.update(
                    {
                        "action": "llm_srt_edit",
                        "mode": "translate",
                        "input": srt_path,
                        "output": output_path,
                        "json_output": json_path,
                        "target_lang": target_lang,
                    }
                )
                self.progress_step("调用 LLM 生成翻译 JSON")
                payload = self.run_streaming_worker(job)
                result_text = self._read_text_file(payload["path"])

                def save_result(text):
                    with open(payload["path"], "w", encoding="utf-8") as handle:
                        handle.write(text)
                    self.log("Translated SRT saved: %s" % payload["path"])

                def apply_result():
                    self.update_srt_state("processed_srt", payload)
                    self.state["final_srt"] = payload["path"]
                    self.log("Translated SRT applied: %s" % payload["path"])

                self.set_progress_result(result_text, apply_result, save_result)
                self.finish_progress(True, "翻译 SRT 已生成并保存：%s" % payload["path"])
            except Exception as exc:
                self.finish_progress(False, str(exc))
                raise

        self.safe(action)

    def on_open_settings(self, ev):
        self.safe(self.open_settings_dialog)

    def open_settings_dialog(self):
        dialog_id = SCRIPT_ID + ".settings"
        existing = UI.FindWindow(dialog_id)
        if existing:
            existing.Show()
            existing.Raise()
            return

        win = DISPATCHER.AddWindow(
            {"ID": dialog_id, "WindowTitle": "Subtitle Agent Settings", "Geometry": [180, 100, 960, 760]},
            UI.VGroup(
                {"Spacing": 8},
                [
                    UI.HGroup({"Weight": 0, "Spacing": 6}, [
                        UI.Label({"Text": "output_base_dir", "Weight": 0}),
                        UI.LineEdit({"ID": "settingsOutputDir", "Text": self.config.get("custom_output_dir", self._default_output_dir()), "Weight": 3}),
                    ]),
                    UI.HGroup({"Weight": 0, "Spacing": 6}, [
                        UI.Label({"Text": "python_path", "Weight": 0}),
                        UI.LineEdit({"ID": "settingsPythonPath", "Text": self.config.get("python_path", ""), "Weight": 3}),
                    ]),
                    UI.HGroup({"Weight": 0, "Spacing": 6}, [
                        UI.Label({"Text": "语言", "Weight": 0}),
                        UI.ComboBox({"ID": "settingsLang", "Weight": 2}),
                        UI.Label({"Text": "目标语言", "Weight": 0}),
                        UI.ComboBox({"ID": "settingsTargetLang", "Weight": 1}),
                    ]),
                    UI.HGroup({"Weight": 0, "Spacing": 6}, [
                        UI.Label({"Text": "max_words", "Weight": 0}),
                        UI.SpinBox({"ID": "settingsMaxWords", "Minimum": 0, "Maximum": 200, "Value": int(self.config.get("default_max_words", 0)), "Weight": 0}),
                        UI.Label({"Text": "max_chars", "Weight": 0}),
                        UI.SpinBox({"ID": "settingsMaxChars", "Minimum": 0, "Maximum": 200, "Value": int(self.config.get("default_max_chars", 24)), "Weight": 0}),
                        UI.Label({"Text": "chars_per_line", "Weight": 0}),
                        UI.SpinBox({"ID": "settingsCharsPerLine", "Minimum": 1, "Maximum": 200, "Value": int(self.config.get("default_chars_per_line", 24)), "Weight": 0}),
                    ]),
                    UI.HGroup({"Weight": 0, "Spacing": 6}, [
                        UI.Label({"Text": "align_model", "Weight": 0}),
                        UI.LineEdit({"ID": "settingsAlignModel", "Text": self.config.get("align_model", "fa-zh"), "Weight": 1}),
                        UI.Label({"Text": "align_device", "Weight": 0}),
                        UI.LineEdit({"ID": "settingsAlignDevice", "Text": self.config.get("align_device", "cpu"), "Weight": 1}),
                    ]),
                    UI.HGroup({"Weight": 0, "Spacing": 6}, [
                        UI.Label({"Text": "local_model", "Weight": 0}),
                        UI.LineEdit({"ID": "settingsLocalModel", "Text": self.config.get("local_model_name", "paraformer-zh"), "Weight": 1}),
                        UI.Label({"Text": "local_device", "Weight": 0}),
                        UI.LineEdit({"ID": "settingsLocalDevice", "Text": self.config.get("local_device", "cpu"), "Weight": 1}),
                        UI.Label({"Text": "cache_dir", "Weight": 0}),
                        UI.LineEdit({"ID": "settingsCacheDir", "Text": self.config.get("cache_dir", ""), "Weight": 1}),
                    ]),
                    UI.HGroup({"Weight": 0, "Spacing": 6}, [
                        UI.Label({"Text": "DashScope Key", "Weight": 0}),
                        UI.LineEdit({"ID": "settingsApiKey", "Text": self.config.get("dashscope_api_key", ""), "EchoMode": "Password", "Weight": 2}),
                        UI.Label({"Text": "region", "Weight": 0}),
                        UI.ComboBox({"ID": "settingsRegion", "Weight": 1}),
                    ]),
                    UI.HGroup({"Weight": 0, "Spacing": 6}, [
                        UI.Label({"Text": "llm_model", "Weight": 0}),
                        UI.LineEdit({"ID": "settingsLlmModel", "Text": self.config.get("llm_model", "deepseek-v4-flash"), "Weight": 1}),
                        UI.Label({"Text": "thinking", "Weight": 0}),
                        UI.CheckBox({"ID": "settingsLlmThinking", "Text": "enable", "Checked": bool(self.config.get("llm_enable_thinking", True)), "Weight": 0}),
                    ]),
                    UI.HGroup({"Weight": 0, "Spacing": 6}, [
                        UI.Label({"Text": "llm_base_url", "Weight": 0}),
                        UI.LineEdit({"ID": "settingsLlmBaseUrl", "Text": self.config.get("llm_base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1"), "Weight": 3}),
                    ]),
                    UI.Label({"Text": "校对提示词", "Weight": 0}),
                    UI.TextEdit({"ID": "settingsProofreadPrompt", "PlainText": self.config.get("llm_proofread_prompt", DEFAULT_PROOFREAD_PROMPT), "Weight": 1}),
                    UI.Label({"Text": "翻译提示词（可使用 {target_lang}）", "Weight": 0}),
                    UI.TextEdit({"ID": "settingsTranslatePrompt", "PlainText": self.config.get("llm_translate_prompt", DEFAULT_TRANSLATE_PROMPT), "Weight": 1}),
                    UI.Label({"Text": "文案优化提示词", "Weight": 0}),
                    UI.TextEdit({"ID": "settingsOptimizePrompt", "PlainText": self.config.get("llm_optimize_prompt", DEFAULT_OPTIMIZE_PROMPT), "Weight": 1}),
                    UI.HGroup({"Weight": 0, "Spacing": 6}, [
                        UI.Button({"ID": "settingsSaveBtn", "Text": "保存设置", "Weight": 0}),
                        UI.Button({"ID": "settingsCloseBtn", "Text": "关闭", "Weight": 0}),
                    ]),
                ],
            ),
        )

        items = win.GetItems()
        items["settingsLang"].AddItems(["zh", "en", "yue", "ja", "ko"])
        items["settingsTargetLang"].AddItems(["zh-cn", "zh-tw", "zh-hk"])
        items["settingsRegion"].AddItems(["cn", "intl"])

        self._select_combo_value(items["settingsLang"], self.config.get("default_lang", "zh"))
        self._select_combo_value(items["settingsTargetLang"], self.config.get("target_lang", "zh-cn"))
        self._select_combo_value(items["settingsRegion"], self.config.get("region", "cn"))

        def close_dialog(ev):
            win.Hide()

        def save_dialog(ev):
            self.config["output_dir_mode"] = "custom"
            self.config["custom_output_dir"] = expand_user_path(items["settingsOutputDir"].Text.strip() or default_user_asr_dir())
            self.config["python_path"] = expand_user_path(items["settingsPythonPath"].Text.strip())
            self.config["default_lang"] = items["settingsLang"].CurrentText or "zh"
            self.config["target_lang"] = items["settingsTargetLang"].CurrentText or "zh-cn"
            self.config["default_max_words"] = int(items["settingsMaxWords"].Value)
            self.config["default_max_chars"] = int(items["settingsMaxChars"].Value)
            self.config["default_chars_per_line"] = int(items["settingsCharsPerLine"].Value)
            self.config["align_model"] = items["settingsAlignModel"].Text.strip() or "fa-zh"
            self.config["align_device"] = items["settingsAlignDevice"].Text.strip() or "cpu"
            self.config["local_model_name"] = items["settingsLocalModel"].Text.strip() or "paraformer-zh"
            self.config["local_device"] = items["settingsLocalDevice"].Text.strip() or "cpu"
            self.config["cache_dir"] = expand_user_path(items["settingsCacheDir"].Text.strip())
            self.config["dashscope_api_key"] = items["settingsApiKey"].Text.strip()
            self.config["region"] = items["settingsRegion"].CurrentText or "cn"
            self.config["llm_model"] = items["settingsLlmModel"].Text.strip() or "deepseek-v4-flash"
            self.config["llm_base_url"] = items["settingsLlmBaseUrl"].Text.strip() or "https://dashscope.aliyuncs.com/compatible-mode/v1"
            self.config["llm_enable_thinking"] = bool(items["settingsLlmThinking"].Checked)
            self.config["llm_proofread_prompt"] = items["settingsProofreadPrompt"].PlainText.strip() or DEFAULT_PROOFREAD_PROMPT
            self.config["llm_translate_prompt"] = items["settingsTranslatePrompt"].PlainText.strip() or DEFAULT_TRANSLATE_PROMPT
            self.config["llm_optimize_prompt"] = items["settingsOptimizePrompt"].PlainText.strip() or DEFAULT_OPTIMIZE_PROMPT
            persisted = dict(self.config)
            for key in ("python_path", "custom_output_dir", "cache_dir"):
                persisted[key] = compact_user_path(persisted.get(key))
            with open(CONFIG_PATH, "w", encoding="utf-8") as handle:
                json.dump(persisted, handle, ensure_ascii=False, indent=2)
            self._select_mode_combo(self.config.get("recognition_mode", "align"))
            self.state["output_dir_overridden"] = False
            self._set_auto_output_dir()
            self.log("Settings saved.")
            win.Hide()

        win.On[dialog_id].Close = close_dialog
        win.On["settingsCloseBtn"].Clicked = close_dialog
        win.On["settingsSaveBtn"].Clicked = save_dialog
        win.Show()

    def _select_combo_value(self, combo, value):
        for idx in range(combo.Count()):
            if combo.ItemText[idx] == value:
                combo.CurrentIndex = idx
                return
        combo.AddItem(value)
        combo.CurrentIndex = combo.Count() - 1

    def safe(self, fn):
        try:
            fn()
        except Exception as exc:
            self.log("ERROR: %s" % exc)
            self.log(traceback.format_exc())


def main():
    app = SubtitleAgentApp()
    window = app.create_window()
    window.Show()
    DISPATCHER.RunLoop()


if __name__ == "__main__":
    main()
