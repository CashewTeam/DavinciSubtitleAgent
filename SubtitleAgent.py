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
APP_VERSION = "2026-06-11.44"

MODE_LABELS = [
    ("asr_remote", "远程 ASR"),
    ("resolve_builtin", "Resolve 内置字幕生成"),
]
MODE_LABEL_TO_KEY = dict((label, key) for key, label in MODE_LABELS)
MODE_KEY_TO_LABEL = dict(MODE_LABELS)


DEFAULT_PROOFREAD_PROMPT = (
    "请作为专业影视字幕校对编辑，阅读整份 SRT 并输出一个用于全局文本替换的 JSON 词典。"
    "你的任务是找出需要修正的错别字、ASR 误识别、术语错误、英文大小写/拼写错误、中英空格问题和明显不自然的短语，"
    "将错误文本映射到正确文本。只输出 JSON，不要解释，不要输出 markdown。"
    "输出格式固定为 {\"replacements\":{\"错误文本\":\"正确文本\"}}。"
    "不要输出行号、序号、时码，不要重写整条字幕。"
    "尽量输出最小但安全的替换单元，避免过短到误伤其他字幕。"
    "如果无需修改，输出 {\"replacements\":{}}。"
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
    try:
        module_stamp = str(int(os.path.getmtime(CORE_PATH)))
    except Exception:
        module_stamp = str(int(time.time()))
    module_name = "subtitle_agent_core_embedded_%s" % module_stamp
    loader = SourceFileLoader(module_name, CORE_PATH)
    spec = importlib.util.spec_from_loader(module_name, loader)
    if spec is None:
        raise RuntimeError("Failed to create import spec for %s" % CORE_PATH)
    module = importlib.util.module_from_spec(spec)
    old_dont_write_bytecode = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = old_dont_write_bytecode
    return module


core = load_core_module()


def ensure_config():
    os.makedirs(AGENT_DIR, exist_ok=True)
    if os.path.isfile(CONFIG_PATH):
        return
    with open(CONFIG_PATH, "w", encoding="utf-8") as handle:
        json.dump(
            {
                "dashscope_api_key": "",
                "region": "cn",
                "default_lang": "zh",
                "default_max_words": 0,
                "default_max_chars": 24,
                "default_chars_per_line": 24,
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
    for key in ("python_path", "custom_output_dir"):
        if config.get(key):
            config[key] = expand_user_path(config[key])
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
        return win

    def _status_group(self):
        return UI.VGroup(
            {"Weight": 0, "Spacing": 4},
            [
                UI.Label({"ID": "statusTitleLabel", "Text": "Step 1 \xb7 \u521d\u59cb\u5316", "StyleSheet": "font-weight: bold; font-size: 14px;"}),
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
                        UI.Button({"ID": "refreshStatusBtn", "Text": "\u5237\u65b0\u72b6\u6001", "Weight": 0}),
                        UI.Button({"ID": "switchTimelineBtn", "Text": "\u5207\u6362\u65f6\u95f4\u7ebf", "Weight": 0}),
                        UI.Button({"ID": "fixTimecodeBtn", "Text": "\u4fee\u6b63\u8d77\u59cb\u65f6\u7801", "Weight": 0}),
                    ],
                ),
            ],
        )

    def _wizard_group(self):
        return UI.VGroup(
            {"Weight": 2, "Spacing": 4},
            [
                UI.Label({"Text": "Step 2 \xb7 \u51c6\u5907\u7d20\u6750", "StyleSheet": "font-weight: bold; font-size: 14px;"}),
                UI.HGroup(
                    {"Weight": 0, "Spacing": 6},
                    [
                        UI.Label({"Text": "\u8f93\u51fa\u76ee\u5f55", "Weight": 0}),
                        UI.LineEdit({"ID": "outputDirEdit", "Weight": 3}),
                        UI.Button({"ID": "browseOutputDirBtn", "Text": "\u9009\u62e9\u76ee\u5f55", "Weight": 0}),
                        UI.Label({"Text": "\u524d\u7f00", "Weight": 0}),
                        UI.LineEdit({"ID": "outputPrefixEdit", "Weight": 1}),
                    ],
                ),
                UI.HGroup(
                    {"Weight": 0, "Spacing": 6},
                    [
                        UI.Label({"Text": "WAV \u6587\u4ef6", "Weight": 0}),
                        UI.LineEdit({"ID": "wavPathEdit", "Weight": 3}),
                        UI.Button({"ID": "browseWavBtn", "Text": "\u9009\u62e9 WAV", "Weight": 0}),
                        UI.Button({"ID": "clearWavBtn", "Text": "\u6e05\u7a7a WAV", "Weight": 0}),
                    ],
                ),
                UI.HGroup(
                    {"Weight": 0, "Spacing": 6},
                    [
                        UI.Label({"Text": "\u53c2\u8003\u6587\u7a3f", "Weight": 0}),
                        UI.LineEdit({"ID": "textPathEdit", "Weight": 3}),
                        UI.Button({"ID": "browseTextBtn", "Text": "\u9009\u62e9\u6587\u7a3f", "Weight": 0}),
                        UI.Button({"ID": "clearTextBtn", "Text": "\u6e05\u7a7a\u6587\u7a3f", "Weight": 0}),
                    ],
                ),
                UI.HGroup(
                    {"Weight": 0, "Spacing": 6},
                    [
                        UI.Label({"Text": "\u53c2\u8003\u6587\u6848\u8f93\u5165 / \u7f16\u8f91", "Weight": 1}),
                        UI.Button({"ID": "optimizeTextBtn", "Text": "\u4f18\u5316\u6587\u6848", "Weight": 0}),
                    ],
                ),
                UI.VGroup(
                    {"Weight": 1, "Spacing": 0},
                    [
                        UI.TextEdit(
                            {
                                "ID": "textEditor",
                                "Weight": 1,
                                "PlaceholderText": "\u6709\u53c2\u8003\u6587\u7a3f\u65f6\u53ef\u76f4\u63a5\u7c98\u8d34\u6216\u7f16\u8f91\u3002\u7559\u7a7a\u5219\u6309\u8bbe\u7f6e\u4e2d\u7684\u8bc6\u522b\u6a21\u5f0f\u6267\u884c ASR\u3002",
                            }
                        ),
                    ],
                ),
                UI.HGroup(
                    {"Weight": 0, "Spacing": 6},
                    [
                        UI.Label({"Text": "SRT \u6587\u4ef6", "Weight": 0}),
                        UI.LineEdit({"ID": "srtPathEdit", "Weight": 3}),
                        UI.Button({"ID": "browseSrtBtn", "Text": "\u9009\u62e9 SRT", "Weight": 0}),
                        UI.Button({"ID": "inlineSettingsBtn", "Text": "\u8bbe\u7f6e", "Weight": 0}),
                    ],
                ),
                UI.HGroup(
                    {"Weight": 0, "Spacing": 6},
                    [
                        UI.Label({"Text": "\u539f\u59cb SRT", "Weight": 0}),
                        UI.LineEdit({"ID": "rawSrtEdit", "ReadOnly": True, "Weight": 2}),
                        UI.Label({"Text": "\u5904\u7406\u540e SRT", "Weight": 0}),
                        UI.LineEdit({"ID": "processedSrtEdit", "ReadOnly": True, "Weight": 2}),
                    ],
                ),
            ],
        )

    def _action_group(self):
        return UI.VGroup(
            {"Weight": 0, "Spacing": 4},
            [
                UI.Label({"Text": "Step 3 \xb7 \u6267\u884c", "StyleSheet": "font-weight: bold; font-size: 14px;"}),
                UI.HGroup(
                    {"Weight": 0, "Spacing": 6},
                    [
                        UI.Label({"Text": "\u5f53\u524d\u6a21\u5f0f", "Weight": 0}),
                        UI.ComboBox({"ID": "modeCombo", "Weight": 1}),
                        UI.Button({"ID": "generateBtn", "Text": "\u5f00\u59cb\u8bc6\u522b", "Weight": 0}),
                        UI.Button({"ID": "exportSrtBtn", "Text": "\u5bfc\u51fa\u65f6\u95f4\u7ebf\u5b57\u5e55", "Weight": 0}),
                        UI.Button({"ID": "convertSrtBtn", "Text": "\u6821\u5bf9", "Weight": 0}),
                        UI.Button({"ID": "applyCorrectionsBtn", "Text": "\u7ffb\u8bd1", "Weight": 0}),
                        UI.Button({"ID": "importSrtBtn", "Text": "\u5bfc\u5165 SRT \u5230\u65f6\u95f4\u7ebf", "Weight": 0}),
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
                        UI.Label({"Text": "\u65e5\u5fd7", "Weight": 0, "MaximumSize": [16777215, 16], "StyleSheet": "font-size: 11px;"}),
                        UI.TextEdit({"ID": "logEdit", "ReadOnly": True, "Weight": 3, "MinimumSize": [0, 320]}),
                    ],
                ),
                UI.VGroup(
                    {"Weight": 1, "Spacing": 1},
                    [
                        UI.Label({"Text": "\u5b57\u5e55\u9884\u89c8", "Weight": 0, "MaximumSize": [16777215, 16], "StyleSheet": "font-size: 11px;"}),
                        UI.TextEdit({"ID": "previewEdit", "ReadOnly": True, "Weight": 3, "MinimumSize": [0, 320]}),
                    ],
                ),
            ],
        )

    def _populate_defaults(self):
        items = self.items
        items["outputDirEdit"].Text = self._default_output_dir()
        items["modeCombo"].AddItems([label for _, label in MODE_LABELS])
        self._select_mode_combo(self.config.get("recognition_mode", "asr_remote"))

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
        return self.config.get("recognition_mode", "asr_remote")

    def _mode_summary(self):
        mode_map = {
            "asr_remote": "\u5f53\u524d\u6a21\u5f0f\uff1a\u8fdc\u7a0b ASR",
            "resolve_builtin": "\u5f53\u524d\u6a21\u5f0f\uff1aResolve \u5185\u7f6e\u5b57\u5e55\u751f\u6210",
        }
        return mode_map.get(self._current_mode_key(), "\u5f53\u524d\u6a21\u5f0f\uff1a\u8fdc\u7a0b ASR")

    def _select_mode_combo(self, mode_key):
        self._select_combo_value(self.items["modeCombo"], MODE_KEY_TO_LABEL.get(mode_key, MODE_KEY_TO_LABEL["asr_remote"]))

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
            self.items["statusTitleLabel"].Text = "Step 1 \xb7 \u521d\u59cb\u5316 | \u8b66\u544a\uff1a%s" % text
            self.items["statusTitleLabel"].StyleSheet = "font-weight: bold; font-size: 14px; color: #d9b44a;"
        else:
            self.items["statusTitleLabel"].Text = "Step 1 \xb7 \u521d\u59cb\u5316"
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
                    UI.Label({"ID": "progressStageLabel", "Text": "\u51c6\u5907\u4e2d", "Weight": 0, "StyleSheet": "font-weight: bold; font-size: 14px;"}),
                    UI.Label({"ID": "reasoningLengthLabel", "Text": "\u601d\u7ef4\u94fe\u6587\u672c\u957f\u5ea6\uff1a0 \u5b57\u7b26", "Weight": 0, "StyleSheet": "font-size: 11px;"}),
                    UI.HGroup({"Weight": 1, "Spacing": 8}, [
                        UI.VGroup({"Weight": 1, "Spacing": 2}, [
                            UI.Label({"Text": "\u5f53\u524d\u72b6\u6001 / JSON \u8f93\u51fa", "Weight": 0, "StyleSheet": "font-size: 11px;"}),
                            UI.TextEdit({"ID": "progressLogEdit", "ReadOnly": True, "Weight": 1}),
                        ]),
                        UI.VGroup({"ID": "progressResultGroup", "Weight": 1 if with_result else 0, "Spacing": 2}, [
                            UI.Label({"Text": "\u6700\u7ec8\u8f93\u51fa\u7ed3\u679c", "Weight": 0, "StyleSheet": "font-size: 11px;"}),
                            UI.TextEdit({"ID": "progressResultEdit", "ReadOnly": False, "Weight": 1}),
                        ]),
                    ]),
                    UI.HGroup({"Weight": 0, "Spacing": 6}, [
                        UI.Button({"ID": "progressApplyBtn", "Text": "\u5e94\u7528\u7ed3\u679c\uff08\u7b49\u5f85\u751f\u6210\uff09", "Weight": 0}),
                        UI.Button({"ID": "progressCloseBtn", "Text": "\u5173\u95ed", "Weight": 0}),
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
                self.progress_step("\u7ed3\u679c\u8fd8\u672a\u751f\u6210\uff0c\u6682\u4e0d\u80fd\u5e94\u7528")
                return
            try:
                self.save_progress_result()
                self.progress_apply_callback()
                win.Hide()
                if self.progress_window == win:
                    self.progress_window = None
            except Exception as exc:
                self.progress_step("\u5e94\u7528\u7ed3\u679c\u5931\u8d25\uff1a%s" % exc)

        win.On[dialog_id].Close = close_dialog
        win.On["progressCloseBtn"].Clicked = close_dialog
        win.On["progressApplyBtn"].Clicked = apply_dialog
        win.Show()
        try:
            win.Update()
            win.Repaint()
        except Exception:
            pass
        self.progress_step("\u521d\u59cb\u5316\u4efb\u52a1")
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
        prefix = "\u5b8c\u6210" if success else "\u5931\u8d25"
        self.progress_step("%s\uff1a%s" % (prefix, message))

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
            self.progress_items["progressApplyBtn"].Text = "\u5e94\u7528\u7ed3\u679c" if apply_callback else "\u5e94\u7528\u7ed3\u679c\uff08\u65e0\u53ef\u5e94\u7528\u5185\u5bb9\uff09"
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
            "asr_remote": "asr_remote",
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

    def write_temp_file(self, suffix, content):
        fd, path = tempfile.mkstemp(prefix="subtitle_agent_", suffix=suffix)
        os.close(fd)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)
        return path

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
            "timeout_seconds": 180,
            "connection_retries": 3,
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
            raise RuntimeError("\u5df2\u751f\u6210\u7ffb\u8bd1 JSON \u6a21\u677f\uff0c\u8bf7\u5148\u7f16\u8f91\u8fd9\u4e2a\u6587\u4ef6\u540e\u518d\u70b9\u7ffb\u8bd1: %s" % path)
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

    def _worker_python(self):
        path = self.config.get("python_path", "")
        if path:
            return os.path.abspath(os.path.expanduser(path))
        return "python3"

    def run_worker(self, job):
        fd, job_path = tempfile.mkstemp(prefix="subtitle_agent_job_", suffix=".json")
        os.close(fd)
        with open(job_path, "w", encoding="utf-8") as handle:
            json.dump(job, handle, ensure_ascii=False, indent=2)
        cmd = [self._worker_python(), CORE_PATH, "worker", job_path]
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
        if self.config.get("dashscope_api_key"):
            env["DASHSCOPE_API_KEY"] = self.config.get("dashscope_api_key")
        return env

    def run_streaming_worker(self, job):
        fd, job_path = tempfile.mkstemp(prefix="subtitle_agent_stream_job_", suffix=".json")
        os.close(fd)
        with open(job_path, "w", encoding="utf-8") as handle:
            json.dump(job, handle, ensure_ascii=False, indent=2)
        cmd = [self._worker_python(), CORE_PATH, "worker", job_path]
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
                return_code = process.wait()
                if process.stderr:
                    stderr = process.stderr.read()
                    if stderr and stderr.strip():
                        self.log(stderr.strip())
                if return_code not in (0, None):
                    self.log("Streaming worker exited with code %s" % return_code)
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
            self.open_progress_dialog("Subtitle Agent \u6587\u6848\u4f18\u5316", with_result=True, stream_output_to_result=True)
            try:
                self.progress_step("\u8bfb\u53d6\u53c2\u8003\u6587\u6848")
                text = self.reference_text_content()
                job = self.llm_job_defaults()
                job.update(
                    {
                        "action": "llm_optimize_text",
                        "text": text,
                    }
                )
                self.progress_step("\u8c03\u7528 LLM \u4f18\u5316\u53c2\u8003\u6587\u6848")
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
                self.finish_progress(True, "\u53c2\u8003\u6587\u6848\u5df2\u751f\u6210\u5e76\u4fdd\u5b58\uff1a%s" % output_path)
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
                self.progress_step("\u8bc6\u522b\u6a21\u5f0f\uff1a%s" % mode)
                if mode == "resolve_builtin":
                    self.progress_step("\u6267\u884c Resolve \u5185\u7f6e\u5b57\u5e55\u751f\u6210")
                    result = core.generate_subtitles(int(self.config.get("default_chars_per_line", 24)))
                    self.log("Resolve generated %s subtitle items" % result["count"])
                    self.progress_step("\u5199\u5165\u539f\u59cb SRT")
                    exported = core.export_subtitles_srt(raw_srt_path)
                    self.progress_step("\u5237\u65b0 SRT \u8def\u5f84\u4e0e\u9884\u89c8")
                    self.update_srt_state("raw_srt", exported)
                    self.state["final_srt"] = exported["path"]
                    self.log("Raw SRT exported to %s" % exported["path"])
                    self.finish_progress(True, "\u539f\u59cb SRT \u5df2\u751f\u6210\uff1a%s" % exported["path"])
                    return

                selected_wav = self.items["wavPathEdit"].Text.strip()
                if selected_wav:
                    self.progress_step("\u4f7f\u7528\u7528\u6237\u9009\u62e9 WAV")
                    audio_path = os.path.abspath(os.path.expanduser(selected_wav))
                    if not os.path.isfile(audio_path):
                        raise RuntimeError("WAV file does not exist: %s" % audio_path)
                    if os.path.splitext(audio_path)[1].lower() != ".wav":
                        raise RuntimeError("Please choose a .wav file: %s" % audio_path)
                    self.log("Using selected WAV file: %s" % audio_path)
                else:
                    self.progress_step("\u5bfc\u51fa\u65f6\u95f4\u7ebf\u97f3\u9891")
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

                self.progress_step("\u6267\u884c\u8fdc\u7a0b ASR")
                payload = self.run_worker(
                    {
                        "action": "asr",
                        "audio": audio_path,
                        "output": raw_srt_path,
                        "lang": self.config.get("default_lang", "zh"),
                        "max_words": int(self.config.get("default_max_words", 0)),
                        "dashscope_api_key": self.config.get("dashscope_api_key", ""),
                        "region": self.config.get("region", "cn"),
                    }
                )
                self.progress_step("\u5199\u5165\u539f\u59cb SRT")
                self.progress_step("\u5237\u65b0 SRT \u8def\u5f84\u4e0e\u9884\u89c8")
                self.update_srt_state("raw_srt", payload)
                self.state["final_srt"] = payload["path"]
                self.log("Raw SRT generated: %s (%s items)" % (payload["path"], payload["count"]))
                self.finish_progress(True, "\u539f\u59cb SRT \u5df2\u751f\u6210\uff1a%s" % payload["path"])
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
            self.open_progress_dialog("Subtitle Agent SRT \u6821\u5bf9", with_result=True)
            try:
                srt_path = self.items["srtPathEdit"].Text.strip()
                if not srt_path:
                    raise RuntimeError("Please choose an SRT file first")
                self.items["srtPathEdit"].Text = srt_path
                output_path = self.path_for("subtitles_proofread.srt")
                json_path = self.path_for("proofread.json")
                reference_text = self.optional_reference_text_content()
                if reference_text:
                    self.progress_step("\u5df2\u9644\u52a0\u53c2\u8003\u6587\u6848\u4e0a\u4e0b\u6587\uff1a%s \u5b57\u7b26" % len(reference_text))
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
                self.progress_step("\u8c03\u7528 LLM \u751f\u6210\u6821\u5bf9 JSON")
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
                self.finish_progress(True, "\u6821\u5bf9 SRT \u5df2\u751f\u6210\u5e76\u4fdd\u5b58\uff1a%s" % payload["path"])
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
            {"ID": dialog_id, "WindowTitle": "\u9009\u62e9\u7ffb\u8bd1\u76ee\u6807\u8bed\u8a00", "Geometry": [260, 220, 520, 180]},
            UI.VGroup(
                {"Spacing": 8},
                [
                    UI.Label({"Text": "\u76ee\u6807\u8bed\u8a00", "Weight": 0}),
                    UI.HGroup({"Weight": 0, "Spacing": 6}, [
                        UI.ComboBox({"ID": "translateLangCombo", "Weight": 1}),
                        UI.LineEdit({"ID": "translateLangCustom", "PlaceholderText": "\u81ea\u5b9a\u4e49\uff0c\u5982 en / ja / zh-cn", "Weight": 1}),
                    ]),
                    UI.HGroup({"Weight": 0, "Spacing": 6}, [
                        UI.Button({"ID": "translateRunBtn", "Text": "\u5f00\u59cb\u7ffb\u8bd1", "Weight": 0}),
                        UI.Button({"ID": "translateCancelBtn", "Text": "\u53d6\u6d88", "Weight": 0}),
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
            self.open_progress_dialog("Subtitle Agent SRT \u7ffb\u8bd1", with_result=True)
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
                self.progress_step("\u8c03\u7528 LLM \u751f\u6210\u7ffb\u8bd1 JSON")
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
                self.finish_progress(True, "\u7ffb\u8bd1 SRT \u5df2\u751f\u6210\u5e76\u4fdd\u5b58\uff1a%s" % payload["path"])
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
            {"ID": dialog_id, "WindowTitle": "Subtitle Agent Settings", "Geometry": [180, 100, 960, 700]},
            UI.VGroup(
                {"Spacing": 8},
                [
                    UI.HGroup({"Weight": 0, "Spacing": 6}, [
                        UI.Label({"Text": "\u8f93\u51fa\u76ee\u5f55", "Weight": 0}),
                        UI.LineEdit({"ID": "settingsOutputDir", "Text": self.config.get("custom_output_dir", self._default_output_dir()), "Weight": 3}),
                    ]),
                    UI.HGroup({"Weight": 0, "Spacing": 6}, [
                        UI.Label({"Text": "\u8bed\u8a00", "Weight": 0}),
                        UI.ComboBox({"ID": "settingsLang", "Weight": 2}),
                        UI.Label({"Text": "\u76ee\u6807\u8bed\u8a00", "Weight": 0}),
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
                    UI.Label({"Text": "\u6821\u5bf9\u63d0\u793a\u8bcd", "Weight": 0}),
                    UI.TextEdit({"ID": "settingsProofreadPrompt", "PlainText": self.config.get("llm_proofread_prompt", DEFAULT_PROOFREAD_PROMPT), "Weight": 1}),
                    UI.Label({"Text": "\u7ffb\u8bd1\u63d0\u793a\u8bcd\uff08\u53ef\u4f7f\u7528 {target_lang}\uff09", "Weight": 0}),
                    UI.TextEdit({"ID": "settingsTranslatePrompt", "PlainText": self.config.get("llm_translate_prompt", DEFAULT_TRANSLATE_PROMPT), "Weight": 1}),
                    UI.Label({"Text": "\u6587\u6848\u4f18\u5316\u63d0\u793a\u8bcd", "Weight": 0}),
                    UI.TextEdit({"ID": "settingsOptimizePrompt", "PlainText": self.config.get("llm_optimize_prompt", DEFAULT_OPTIMIZE_PROMPT), "Weight": 1}),
                    UI.HGroup({"Weight": 0, "Spacing": 6}, [
                        UI.Button({"ID": "settingsSaveBtn", "Text": "\u4fdd\u5b58\u8bbe\u7f6e", "Weight": 0}),
                        UI.Button({"ID": "settingsCloseBtn", "Text": "\u5173\u95ed", "Weight": 0}),
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
            self.config["default_lang"] = items["settingsLang"].CurrentText or "zh"
            self.config["target_lang"] = items["settingsTargetLang"].CurrentText or "zh-cn"
            self.config["default_max_words"] = int(items["settingsMaxWords"].Value)
            self.config["default_max_chars"] = int(items["settingsMaxChars"].Value)
            self.config["default_chars_per_line"] = int(items["settingsCharsPerLine"].Value)
            self.config["dashscope_api_key"] = items["settingsApiKey"].Text.strip()
            self.config["region"] = items["settingsRegion"].CurrentText or "cn"
            self.config["llm_model"] = items["settingsLlmModel"].Text.strip() or "deepseek-v4-flash"
            self.config["llm_base_url"] = items["settingsLlmBaseUrl"].Text.strip() or "https://dashscope.aliyuncs.com/compatible-mode/v1"
            self.config["llm_enable_thinking"] = bool(items["settingsLlmThinking"].Checked)
            self.config["llm_proofread_prompt"] = items["settingsProofreadPrompt"].PlainText.strip() or DEFAULT_PROOFREAD_PROMPT
            self.config["llm_translate_prompt"] = items["settingsTranslatePrompt"].PlainText.strip() or DEFAULT_TRANSLATE_PROMPT
            self.config["llm_optimize_prompt"] = items["settingsOptimizePrompt"].PlainText.strip() or DEFAULT_OPTIMIZE_PROMPT
            persisted = dict(self.config)
            for key in ("custom_output_dir",):
                persisted[key] = compact_user_path(persisted.get(key))
            with open(CONFIG_PATH, "w", encoding="utf-8") as handle:
                json.dump(persisted, handle, ensure_ascii=False, indent=2)
            self._select_mode_combo(self.config.get("recognition_mode", "asr_remote"))
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
