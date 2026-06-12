#!/usr/bin/env python3

import argparse
import importlib.util
import json
import os
import queue
import select
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from importlib.machinery import SourceFileLoader
from tkinter import filedialog, messagebox, simpledialog

try:
    import customtkinter as ctk
except ImportError:
    ctk = None


APP_NAME = "Subtitle Agent"
APP_VERSION = "2026-06-13.1"
APP_SUPPORT_DIR = os.path.expanduser("~/Library/Application Support/SubtitleAgent")
DEFAULT_OUTPUT_DIR = os.path.expanduser("~/Documents/asr")


def resource_path(relative):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative)


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
AGENT_DIR = resource_path("subtitle_agent")
CORE_PATH = resource_path("subtitle_agent/subtitle_agent_core.tool")
LEGACY_CONFIG_PATH = os.path.join(SCRIPT_DIR, "subtitle_agent", "subtitle_agent_config.json")


def default_user_asr_dir():
    return os.path.expanduser("~/Documents/asr")


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


def _can_prepare_directory(path):
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, ".subtitle_agent_probe")
        with open(probe, "w", encoding="utf-8") as handle:
            handle.write("ok")
        os.unlink(probe)
        return True
    except Exception:
        return False


def runtime_config_path():
    if _can_prepare_directory(APP_SUPPORT_DIR):
        return os.path.join(APP_SUPPORT_DIR, "subtitle_agent_config.json")
    legacy_dir = os.path.dirname(LEGACY_CONFIG_PATH)
    if _can_prepare_directory(legacy_dir):
        return LEGACY_CONFIG_PATH
    fallback_dir = os.path.join(tempfile.gettempdir(), "SubtitleAgent")
    os.makedirs(fallback_dir, exist_ok=True)
    return os.path.join(fallback_dir, "subtitle_agent_config.json")


CONFIG_PATH = runtime_config_path()
os.environ.setdefault("SUBTITLE_AGENT_CONFIG_PATH", CONFIG_PATH)


def ensure_app_support_dir():
    config_dir = os.path.dirname(CONFIG_PATH)
    os.makedirs(config_dir, exist_ok=True)
    return config_dir


def load_core_module():
    module_stamp = str(int(os.path.getmtime(CORE_PATH))) if os.path.isfile(CORE_PATH) else str(int(time.time()))
    module_name = "subtitle_agent_core_app_%s" % module_stamp
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


DEFAULT_CONFIG = {
    "output_dir_mode": "custom",
    "custom_output_dir": compact_user_path(DEFAULT_OUTPUT_DIR),
    "dashscope_api_key": "",
    "region": "cn",
    "default_lang": "zh",
    "default_max_words": 24,
    "default_max_chars": 24,
    "default_chars_per_line": 24,
    "recognition_mode": "asr_remote",
    "target_lang": "zh-cn",
    "llm_model": "deepseek-v4-flash",
    "llm_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "llm_enable_thinking": False,
    "llm_proofread_prompt": core.DEFAULT_PROOFREAD_PROMPT,
    "llm_translate_prompt": core.DEFAULT_TRANSLATE_PROMPT,
    "llm_optimize_prompt": core.DEFAULT_OPTIMIZE_PROMPT,
}

MODE_SPECS = [
    ("asr_remote", "远程 ASR（云端识别）", "asr_remote"),
    ("resolve_builtin", "Resolve 原生识别（当前时间线）", "resolve_builtin"),
]
MODE_LABEL_TO_KEY = dict((label, key) for key, label, _ in MODE_SPECS)
MODE_KEY_TO_LABEL = dict((key, label) for key, label, _ in MODE_SPECS)
MODE_KEY_TO_SUFFIX = dict((key, suffix) for key, _, suffix in MODE_SPECS)


def ensure_config():
    ensure_app_support_dir()
    if not os.path.isfile(CONFIG_PATH) and os.path.isfile(LEGACY_CONFIG_PATH):
        try:
            with open(LEGACY_CONFIG_PATH, "r", encoding="utf-8") as handle:
                legacy = json.load(handle)
            merged = dict(DEFAULT_CONFIG)
            merged.update(legacy)
            with open(CONFIG_PATH, "w", encoding="utf-8") as handle:
                json.dump(merged, handle, ensure_ascii=False, indent=2)
            return
        except Exception:
            pass
    if not os.path.isfile(CONFIG_PATH):
        with open(CONFIG_PATH, "w", encoding="utf-8") as handle:
            json.dump(DEFAULT_CONFIG, handle, ensure_ascii=False, indent=2)


def load_config():
    ensure_config()
    with open(CONFIG_PATH, "r", encoding="utf-8") as handle:
        config = json.load(handle)
    merged = dict(DEFAULT_CONFIG)
    merged.update(config)
    for key in ("custom_output_dir",):
        if merged.get(key):
            merged[key] = expand_user_path(merged[key])
    for removed in ("python_path", "local_model_name", "local_device", "local_model_dir", "model_dir", "corrections_path", "corrections_json", "align_model", "align_device", "cache_dir"):
        merged.pop(removed, None)
    return merged


def save_config(config):
    ensure_app_support_dir()
    persisted = dict(DEFAULT_CONFIG)
    persisted.update(config)
    for removed in ("python_path", "local_model_name", "local_device", "local_model_dir", "model_dir", "corrections_path", "corrections_json", "align_model", "align_device", "cache_dir"):
        persisted.pop(removed, None)
    for key in ("custom_output_dir",):
        persisted[key] = compact_user_path(persisted.get(key))
    with open(CONFIG_PATH, "w", encoding="utf-8") as handle:
        json.dump(persisted, handle, ensure_ascii=False, indent=2)


def run_streaming_job_local(job, on_event=None):
    buffer = queue.Queue()

    def _stream_event(event_type, **payload):
        payload["type"] = event_type
        buffer.put(payload)

    original = core._stream_event
    core._stream_event = _stream_event
    try:
        if job.get("action") == "llm_srt_edit":
            core.run_llm_srt_edit_stream(job)
        elif job.get("action") == "llm_optimize_text":
            core.run_llm_optimize_text_stream(job)
        else:
            raise RuntimeError("Unsupported streaming action: %s" % job.get("action"))
    finally:
        core._stream_event = original
    result = None
    while not buffer.empty():
        event = buffer.get()
        if on_event:
            on_event(event)
        if event.get("type") == "error":
            raise RuntimeError(event.get("message", "Streaming worker failed"))
        if event.get("type") == "result":
            result = event.get("payload") or {}
    if result is None:
        raise RuntimeError("Streaming worker returned no result")
    return result


BaseToplevel = ctk.CTkToplevel if ctk is not None else object


class ResultDialog(BaseToplevel):
    def __init__(self, parent, title, stream_to_result=False):
        super().__init__(parent)
        self.title(title)
        self.geometry("1080x620")
        self.minsize(900, 520)
        self.stream_to_result = bool(stream_to_result)
        self.apply_callback = None
        self.save_callback = None
        self.protocol("WM_DELETE_WINDOW", self.close_dialog)

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        self.stage_label = ctk.CTkLabel(self, text="初始化任务", anchor="w", font=ctk.CTkFont(size=16, weight="bold"))
        self.stage_label.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 4))

        self.reasoning_label = ctk.CTkLabel(self, text="思维链文本长度：0 字符", anchor="w")
        self.reasoning_label.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 8))

        panes = ctk.CTkFrame(self)
        panes.grid(row=2, column=0, sticky="nsew", padx=12, pady=0)
        panes.grid_columnconfigure(0, weight=1)
        panes.grid_columnconfigure(1, weight=1)
        panes.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(panes, text="当前状态 / JSON 输出", anchor="w").grid(row=0, column=0, sticky="ew", padx=(8, 4), pady=(8, 4))
        ctk.CTkLabel(panes, text="最终输出结果", anchor="w").grid(row=0, column=1, sticky="ew", padx=(4, 8), pady=(8, 4))

        self.log_box = ctk.CTkTextbox(panes, wrap="word")
        self.log_box.grid(row=1, column=0, sticky="nsew", padx=(8, 4), pady=(0, 8))

        self.result_box = ctk.CTkTextbox(panes, wrap="word")
        self.result_box.grid(row=1, column=1, sticky="nsew", padx=(4, 8), pady=(0, 8))

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.grid(row=3, column=0, sticky="e", padx=12, pady=12)

        self.apply_button = ctk.CTkButton(actions, text="应用结果（等待生成）", command=self.apply_dialog)
        self.apply_button.pack(side="left", padx=(0, 8))

        self.close_button = ctk.CTkButton(actions, text="关闭", fg_color="#4b5563", hover_color="#374151", command=self.close_dialog)
        self.close_button.pack(side="left")

        self.transient(parent)
        self.lift()
        self.focus_force()

    def _append_text(self, widget, text):
        widget.insert("end", text)
        widget.see("end")

    def append_status(self, message):
        self.after(0, lambda: self._append_status_ui(message))

    def _append_status_ui(self, message):
        self.stage_label.configure(text=message)
        self._append_text(self.log_box, message + "\n")

    def append_output(self, text):
        self.after(0, lambda: self._append_output_ui(text))

    def _append_output_ui(self, text):
        target = self.result_box if self.stream_to_result else self.log_box
        self._append_text(target, text)

    def update_reasoning(self, message):
        self.after(0, lambda: self.reasoning_label.configure(text=message))

    def finish(self, success, message):
        prefix = "完成" if success else "失败"
        self.append_status("%s：%s" % (prefix, message))

    def set_result(self, text, apply_callback=None, save_callback=None):
        def _update():
            self.result_box.delete("1.0", "end")
            self.result_box.insert("1.0", text or "")
            self.apply_callback = apply_callback
            self.save_callback = save_callback
            self.apply_button.configure(text="应用结果" if apply_callback else "应用结果（无可应用内容）")

        self.after(0, _update)

    def get_result_text(self):
        return self.result_box.get("1.0", "end").strip()

    def save_result(self):
        if self.save_callback:
            self.save_callback(self.get_result_text())

    def close_dialog(self):
        try:
            self.save_result()
        finally:
            self.destroy()

    def apply_dialog(self):
        if not self.apply_callback:
            self.append_status("结果还未生成，暂不能应用")
            return
        self.save_result()
        self.apply_callback(self.get_result_text())
        self.destroy()


class SettingsDialog(BaseToplevel):
    def __init__(self, parent, config, on_save):
        super().__init__(parent)
        self.title("%s 设置" % APP_NAME)
        self.geometry("980x760")
        self.minsize(860, 640)
        self.config_data = config
        self.on_save = on_save
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        scroll = ctk.CTkScrollableFrame(self)
        scroll.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)
        scroll.grid_columnconfigure(1, weight=1)

        self.vars = {}
        row = 0

        def add_entry(label, key, show=None):
            nonlocal row
            ctk.CTkLabel(scroll, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=6)
            value = ctk.StringVar(value=str(self.config_data.get(key, "")))
            entry = ctk.CTkEntry(scroll, textvariable=value, show=show)
            entry.grid(row=row, column=1, sticky="ew", pady=6)
            self.vars[key] = value
            row += 1

        def add_combo(label, key, values):
            nonlocal row
            ctk.CTkLabel(scroll, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=6)
            combo = ctk.CTkComboBox(scroll, values=list(values))
            combo.set(str(self.config_data.get(key, values[0])))
            combo.grid(row=row, column=1, sticky="ew", pady=6)
            self.vars[key] = combo
            row += 1

        def add_switch(label, key):
            nonlocal row
            ctk.CTkLabel(scroll, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=6)
            switch = ctk.CTkSwitch(scroll, text="enable")
            if bool(self.config_data.get(key, False)):
                switch.select()
            else:
                switch.deselect()
            switch.grid(row=row, column=1, sticky="w", pady=6)
            self.vars[key] = switch
            row += 1

        def add_text(label, key, height=120):
            nonlocal row
            ctk.CTkLabel(scroll, text=label).grid(row=row, column=0, sticky="nw", padx=(0, 8), pady=6)
            text = ctk.CTkTextbox(scroll, height=height, wrap="word")
            text.insert("1.0", str(self.config_data.get(key, "")))
            text.grid(row=row, column=1, sticky="ew", pady=6)
            self.vars[key] = text
            row += 1

        add_entry("输出目录", "custom_output_dir")
        add_combo("默认语言", "default_lang", ["zh", "en", "yue", "ja", "ko"])
        add_combo("目标语言", "target_lang", ["zh-cn", "zh-tw", "zh-hk", "en", "ja", "ko"])
        add_entry("DashScope API Key", "dashscope_api_key", show="*")
        add_combo("region", "region", ["cn", "intl"])
        add_entry("llm_model", "llm_model")
        add_entry("llm_base_url", "llm_base_url")
        add_switch("thinking", "llm_enable_thinking")
        add_entry("max_words", "default_max_words")
        add_entry("max_chars", "default_max_chars")
        add_entry("chars_per_line", "default_chars_per_line")
        add_text("校对提示词", "llm_proofread_prompt")
        add_text("翻译提示词（可使用 {target_lang}）", "llm_translate_prompt")
        add_text("文案优化提示词", "llm_optimize_prompt")

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.grid(row=1, column=0, sticky="e", padx=12, pady=(0, 12))
        ctk.CTkButton(actions, text="保存设置", command=self.save_dialog).pack(side="left", padx=(0, 8))
        ctk.CTkButton(actions, text="关闭", fg_color="#4b5563", hover_color="#374151", command=self.destroy).pack(side="left")

    def save_dialog(self):
        cfg = dict(self.config_data)
        cfg["output_dir_mode"] = "custom"
        for key, widget in self.vars.items():
            if isinstance(widget, ctk.CTkComboBox):
                cfg[key] = widget.get().strip()
            elif isinstance(widget, ctk.CTkSwitch):
                cfg[key] = bool(widget.get())
            elif isinstance(widget, ctk.CTkTextbox):
                cfg[key] = widget.get("1.0", "end").strip()
            else:
                cfg[key] = widget.get().strip()
        for key in ("default_max_words", "default_max_chars", "default_chars_per_line"):
            cfg[key] = int(cfg.get(key) or DEFAULT_CONFIG[key])
        self.on_save(cfg)
        self.destroy()


class SubtitleAgentApp:
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
            "resolve_connected": False,
        }

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        self.root = ctk.CTk()
        self.root.title(APP_NAME)
        self.root.geometry("1460x980")
        self.root.minsize(1180, 820)
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(3, weight=1)

        self.ui = {}
        self._build_ui()
        self._populate_defaults()
        self.refresh_status()
        self.log("Subtitle Agent app loaded. Version: %s" % APP_VERSION)
        self.log("Config path: %s" % CONFIG_PATH)
        self.log("Core path: %s" % CORE_PATH)

    def _build_ui(self):
        self._build_status_group()
        self._build_material_group()
        self._build_action_group()
        self._build_log_group()

    def _section_frame(self, row, title, weight=0):
        frame = ctk.CTkFrame(self.root, corner_radius=10)
        frame.grid(row=row, column=0, sticky="nsew", padx=12, pady=(12 if row == 0 else 0, 8))
        if weight:
            self.root.grid_rowconfigure(row, weight=weight)
        ctk.CTkLabel(frame, text=title, anchor="w", font=ctk.CTkFont(size=16, weight="bold")).pack(fill="x", padx=12, pady=(10, 6))
        body = ctk.CTkFrame(frame, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        return frame, body

    def _build_status_group(self):
        _, body = self._section_frame(0, "Step 1 · 初始化")
        body.grid_columnconfigure((1, 3, 5, 7), weight=1)

        self.status_title_var = ctk.StringVar(value="Step 1 · 初始化")
        self.ui["status_header"] = self.root.winfo_children()[0].winfo_children()[0]

        self.resolve_var = ctk.StringVar()
        self.project_var = ctk.StringVar()
        self.timeline_var = ctk.StringVar()
        self.start_tc_var = ctk.StringVar()
        self.timeline_combo = ctk.CTkComboBox(body, values=[], state="readonly")

        self._grid_label_entry(body, 0, "Resolve", self.resolve_var)
        self._grid_label_entry(body, 2, "Project", self.project_var)
        self._grid_label_entry(body, 4, "Timeline", self.timeline_var)
        self._grid_label_entry(body, 6, "Start TC", self.start_tc_var)

        self.timeline_combo.grid(row=1, column=0, columnspan=4, sticky="ew", padx=(0, 8), pady=(8, 0))
        ctk.CTkButton(body, text="刷新状态", width=120, command=lambda: self.safe(self.refresh_status)).grid(row=1, column=4, padx=(0, 8), pady=(8, 0))
        ctk.CTkButton(body, text="切换时间线", width=120, command=self.on_switch_timeline).grid(row=1, column=5, padx=(0, 8), pady=(8, 0))
        ctk.CTkButton(body, text="修正起始时码", width=120, command=self.on_fix_timecode).grid(row=1, column=6, padx=(0, 8), pady=(8, 0))

    def _grid_label_entry(self, parent, column, text, variable):
        ctk.CTkLabel(parent, text=text).grid(row=0, column=column, sticky="w", padx=(0, 8), pady=(0, 0))
        entry = ctk.CTkEntry(parent, textvariable=variable)
        entry.configure(state="disabled")
        entry.grid(row=0, column=column + 1, sticky="ew", padx=(0, 12), pady=(0, 0))

    def _build_material_group(self):
        _, body = self._section_frame(1, "Step 2 · 准备素材", weight=1)
        for index in range(6):
            body.grid_columnconfigure(index, weight=1 if index in (1, 4) else 0)

        self.output_dir_var = ctk.StringVar()
        self.output_prefix_var = ctk.StringVar()
        self.wav_path_var = ctk.StringVar()
        self.text_path_var = ctk.StringVar()
        self.srt_path_var = ctk.StringVar()
        self.raw_srt_var = ctk.StringVar()
        self.processed_srt_var = ctk.StringVar()

        self._row_with_entry(body, 0, "输出目录", self.output_dir_var, [("选择目录", self.on_browse_output_dir)], extra_label="前缀", extra_var=self.output_prefix_var)
        self._row_with_entry(body, 1, "WAV 文件", self.wav_path_var, [("选择 WAV", self.on_browse_wav), ("清空 WAV", self.on_clear_wav)])
        self._row_with_entry(body, 2, "参考文稿", self.text_path_var, [("选择文稿", self.on_browse_text), ("清空文稿", self.on_clear_text)])

        top = ctk.CTkFrame(body, fg_color="transparent")
        top.grid(row=3, column=0, columnspan=6, sticky="ew", pady=(10, 4))
        top.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(top, text="参考文案输入 / 编辑", anchor="w").grid(row=0, column=0, sticky="w")
        ctk.CTkButton(top, text="优化文案", width=120, command=self.on_optimize_text).grid(row=0, column=1, sticky="e")

        self.text_editor = ctk.CTkTextbox(body, height=180, wrap="word")
        self.text_editor.grid(row=4, column=0, columnspan=6, sticky="nsew", pady=(0, 8))
        body.grid_rowconfigure(4, weight=1)

        self._row_with_entry(body, 5, "SRT 文件", self.srt_path_var, [("选择 SRT", self.on_browse_srt), ("设置", self.on_open_settings)])
        self._row_two_entries(body, 6, "原始 SRT", self.raw_srt_var, "处理后 SRT", self.processed_srt_var)

    def _row_with_entry(self, parent, row, label, var, buttons, extra_label=None, extra_var=None):
        ctk.CTkLabel(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=6)
        entry = ctk.CTkEntry(parent, textvariable=var)
        entry.grid(row=row, column=1, columnspan=3, sticky="ew", padx=(0, 8), pady=6)
        button_col = 4
        for text, command in buttons:
            ctk.CTkButton(parent, text=text, width=110, command=command).grid(row=row, column=button_col, padx=(0, 8), pady=6, sticky="ew")
            button_col += 1
        if extra_label and extra_var is not None:
            ctk.CTkLabel(parent, text=extra_label).grid(row=row, column=4, sticky="w", padx=(0, 8), pady=6)
            ctk.CTkEntry(parent, textvariable=extra_var).grid(row=row, column=5, sticky="ew", pady=6)

    def _row_two_entries(self, parent, row, left_label, left_var, right_label, right_var):
        ctk.CTkLabel(parent, text=left_label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=6)
        left = ctk.CTkEntry(parent, textvariable=left_var)
        left.configure(state="readonly")
        left.grid(row=row, column=1, columnspan=2, sticky="ew", padx=(0, 8), pady=6)
        ctk.CTkLabel(parent, text=right_label).grid(row=row, column=3, sticky="w", padx=(0, 8), pady=6)
        right = ctk.CTkEntry(parent, textvariable=right_var)
        right.configure(state="readonly")
        right.grid(row=row, column=4, columnspan=2, sticky="ew", pady=6)

    def _build_action_group(self):
        _, body = self._section_frame(2, "Step 3 · 执行")
        body.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(body, text="当前模式").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.mode_combo = ctk.CTkComboBox(body, values=[label for _, label, _ in MODE_SPECS], state="readonly", command=lambda _: self.on_mode_changed())
        self.mode_combo.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        ctk.CTkButton(body, text="开始识别", width=110, command=self.on_generate).grid(row=0, column=2, padx=(0, 8))
        ctk.CTkButton(body, text="导出时间线字幕", width=140, command=self.on_export_srt).grid(row=0, column=3, padx=(0, 8))
        ctk.CTkButton(body, text="校对", width=90, command=self.on_convert_srt).grid(row=0, column=4, padx=(0, 8))
        ctk.CTkButton(body, text="翻译", width=90, command=self.on_translate).grid(row=0, column=5, padx=(0, 8))
        ctk.CTkButton(body, text="导入 SRT 到时间线", width=150, command=self.on_import_srt).grid(row=0, column=6)

    def _build_log_group(self):
        _, body = self._section_frame(3, "", weight=3)
        body.grid_columnconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(body, text="日志", anchor="w").grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ctk.CTkLabel(body, text="字幕预览", anchor="w").grid(row=0, column=1, sticky="ew", padx=(6, 0))
        self.log_box = ctk.CTkTextbox(body, wrap="word")
        self.log_box.grid(row=1, column=0, sticky="nsew", padx=(0, 6))
        self.preview_box = ctk.CTkTextbox(body, wrap="word")
        self.preview_box.grid(row=1, column=1, sticky="nsew", padx=(6, 0))

    def _populate_defaults(self):
        self.output_dir_var.set(self._default_output_dir())
        self.mode_combo.set(MODE_KEY_TO_LABEL.get(self.config.get("recognition_mode", "asr_remote"), MODE_SPECS[0][1]))

    def _default_output_dir(self):
        base = self.config.get("custom_output_dir") or default_user_asr_dir()
        return expand_user_path(base)

    def _output_base_dir(self):
        return expand_user_path(self.config.get("custom_output_dir") or default_user_asr_dir())

    def _project_output_dir(self, context=None):
        context = context or self.state.get("context") or {}
        project_name = context.get("project_name_safe") or context.get("project_name") or ""
        if project_name:
            return os.path.join(self._output_base_dir(), core.sanitize_name(project_name))
        return self._output_base_dir()

    def _set_auto_output_dir(self, context=None):
        output_dir = self._project_output_dir(context)
        self.state["auto_output_dir"] = output_dir
        if not self.state.get("output_dir_overridden"):
            self.output_dir_var.set(output_dir)

    def _current_mode_key(self):
        return MODE_LABEL_TO_KEY.get(self.mode_combo.get(), self.config.get("recognition_mode", "asr_remote"))

    def _mode_suffix(self):
        return MODE_KEY_TO_SUFFIX.get(self._current_mode_key(), "asr_remote")

    def _safe_suffix(self, text):
        return core.sanitize_name(text or "output").lower()

    def path_for(self, suffix):
        output_dir = self.output_dir_var.get().strip() or APP_SUPPORT_DIR
        output_dir = os.path.abspath(os.path.expanduser(output_dir))
        os.makedirs(output_dir, exist_ok=True)
        prefix = self.output_prefix_var.get().strip() or "subtitle_agent"
        return os.path.join(output_dir, "%s_%s" % (prefix, suffix))

    def _select_file(self, filetypes):
        return filedialog.askopenfilename(filetypes=filetypes)

    def _select_dir(self):
        return filedialog.askdirectory(initialdir=self.output_dir_var.get().strip() or self._default_output_dir())

    def _set_readonly_var(self, var, value):
        var.set(value or "")

    def call_ui(self, func):
        self.root.after(0, func)

    def log(self, message):
        self.call_ui(lambda: self._append_log(message))

    def _append_log(self, message):
        self.log_box.insert("end", str(message) + "\n")
        self.log_box.see("end")

    def set_preview_text(self, text):
        def _set():
            self.preview_box.delete("1.0", "end")
            self.preview_box.insert("1.0", text or "")
        self.call_ui(_set)

    def set_preview(self, payload):
        if isinstance(payload, dict):
            content = payload.get("content")
            if content is not None:
                self.set_preview_text(content)
                return
            items = payload.get("items", [])
        else:
            items = payload or []
        lines = []
        for index, entry in enumerate(items, 1):
            lines.append(str(entry.get("index") or index))
            lines.append("%s --> %s" % (entry.get("start", ""), entry.get("end", "")))
            lines.append(entry.get("text", ""))
            lines.append("")
        self.set_preview_text("\n".join(lines))

    def load_srt_preview_from_path(self, path):
        try:
            with open(os.path.abspath(os.path.expanduser(path)), "r", encoding="utf-8-sig", errors="replace") as handle:
                self.set_preview_text(handle.read())
        except Exception as exc:
            self.log("Failed to load SRT preview: %s" % exc)

    def _set_status_header(self, text, warning=False):
        header = self.root.winfo_children()[0].winfo_children()[0]
        header.configure(text=text, text_color="#d9b44a" if warning else None)

    def _worker_python(self):
        return sys.executable or "python3"

    def _worker_env(self):
        env = os.environ.copy()
        resolve_api = "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting"
        resolve_lib = "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so"
        env.setdefault("RESOLVE_SCRIPT_API", resolve_api)
        env.setdefault("RESOLVE_SCRIPT_LIB", resolve_lib)
        module_path = os.path.join(resolve_api, "Modules")
        env["PYTHONPATH"] = module_path + os.pathsep + env.get("PYTHONPATH", "")
        env["SUBTITLE_AGENT_CONFIG_PATH"] = CONFIG_PATH
        tool_paths = ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin"]
        env["PATH"] = os.pathsep.join(tool_paths + [env.get("PATH", "")])
        if self.config.get("dashscope_api_key"):
            env["DASHSCOPE_API_KEY"] = self.config["dashscope_api_key"]
        return env

    def _worker_cmd(self, job_path):
        if getattr(sys, "frozen", False):
            return [sys.executable, "--core-worker", job_path]
        return [self._worker_python(), CORE_PATH, "worker", job_path]

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
        fd, job_path = tempfile.mkstemp(prefix="subtitle_agent_job_", suffix=".json")
        os.close(fd)
        try:
            with open(job_path, "w", encoding="utf-8") as handle:
                json.dump(job, handle, ensure_ascii=False, indent=2)
            process = subprocess.Popen(
                self._worker_cmd(job_path),
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
            remaining = process.stderr.read() if process.stderr else b""
            if remaining:
                stderr_buffer += remaining.decode("utf-8", "replace")
            self._flush_worker_log_buffer(stderr_buffer, force=True)
            stdout_bytes = process.stdout.read() if process.stdout else b""
            stdout = (stdout_bytes or b"").decode("utf-8", "replace").strip()
            if not stdout:
                raise RuntimeError("Worker returned no output")
            payload = json.loads(stdout)
            if process.wait() != 0 and payload.get("success"):
                raise RuntimeError("Worker failed with exit code %s" % process.returncode)
            if not payload.get("success"):
                raise RuntimeError(payload.get("error", "Worker failed"))
            if not payload.get("logs_streamed"):
                for line in payload.get("logs", []):
                    self.log(line)
            return payload
        finally:
            try:
                os.unlink(job_path)
            except Exception:
                pass

    def run_streaming_worker(self, job, dialog):
        fd, job_path = tempfile.mkstemp(prefix="subtitle_agent_stream_job_", suffix=".json")
        os.close(fd)
        try:
            with open(job_path, "w", encoding="utf-8") as handle:
                json.dump(job, handle, ensure_ascii=False, indent=2)
            process = subprocess.Popen(
                self._worker_cmd(job_path),
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
            for raw_line in process.stdout:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except Exception:
                    dialog.append_status(line)
                    continue
                event_type = event.get("type")
                if event_type == "status":
                    dialog.append_status(event.get("message", ""))
                elif event_type == "reasoning_summary":
                    dialog.update_reasoning(event.get("message", ""))
                elif event_type == "content_delta":
                    dialog.append_output(event.get("text", ""))
                elif event_type == "result":
                    result_payload = event.get("payload") or {}
                elif event_type == "error":
                    raise RuntimeError(event.get("message", "Streaming worker failed"))
            stderr = process.stderr.read() if process.stderr else ""
            if stderr and stderr.strip():
                self.log(stderr.strip())
            return_code = process.wait()
            if return_code != 0:
                raise RuntimeError("Streaming worker failed with exit code %s" % return_code)
            if not result_payload:
                raise RuntimeError("Streaming worker returned no result")
            for line in result_payload.get("logs", []):
                self.log(line)
            return result_payload
        finally:
            try:
                os.unlink(job_path)
            except Exception:
                pass

    def update_srt_state(self, key, payload):
        self.state[key] = payload["path"]
        if key == "raw_srt":
            self.raw_srt_var.set(payload["path"])
            self.srt_path_var.set(payload["path"])
        elif key == "processed_srt":
            self.processed_srt_var.set(payload["path"])
            self.srt_path_var.set(payload["path"])
        self.set_preview(payload)

    def reference_text_content(self, required=True):
        text = self.text_editor.get("1.0", "end").strip()
        if text:
            return text
        path = self.text_path_var.get().strip()
        if path and os.path.isfile(path):
            with open(path, "r", encoding="utf-8-sig") as handle:
                return handle.read().strip()
        if required:
            raise RuntimeError("Reference text is required")
        return ""

    def llm_job_defaults(self):
        return {
            "api_key": self.config.get("dashscope_api_key", ""),
            "base_url": self.config.get("llm_base_url", DEFAULT_CONFIG["llm_base_url"]),
            "model": self.config.get("llm_model", DEFAULT_CONFIG["llm_model"]),
            "enable_thinking": bool(self.config.get("llm_enable_thinking", False)),
            "timeout_seconds": 180,
            "connection_retries": 3,
            "proofread_prompt": self.config.get("llm_proofread_prompt", core.DEFAULT_PROOFREAD_PROMPT),
            "translate_prompt": self.config.get("llm_translate_prompt", core.DEFAULT_TRANSLATE_PROMPT),
            "optimize_prompt": self.config.get("llm_optimize_prompt", core.DEFAULT_OPTIMIZE_PROMPT),
        }

    def refresh_status(self):
        try:
            context = core.get_resolve_context()
            self.state["context"] = context
            self.state["resolve_connected"] = True
            self._set_readonly_var(self.resolve_var, context["version"]["version_string"])
            self._set_readonly_var(self.project_var, context["project_name"])
            self._set_readonly_var(self.timeline_var, context["current_timeline"])
            self._set_readonly_var(self.start_tc_var, context["start_timecode"])
            if not self.output_prefix_var.get().strip():
                self.output_prefix_var.set(context["project_name_safe"])
            values = ["%s. %s (%s)" % (tl["index"], tl["name"], tl["start_timecode"]) for tl in context["timelines"]]
            self.timeline_combo.configure(values=values)
            for value in values:
                if context["current_timeline"] in value:
                    self.timeline_combo.set(value)
                    break
            self._set_auto_output_dir(context)
            warning = context.get("warning", "")
            self._set_status_header("Step 1 · 初始化" + (" | 警告：%s" % warning if warning else ""), warning=bool(warning))
            self.log("Resolve connected: %s / %s" % (context["project_name"], context["current_timeline"]))
        except Exception as exc:
            self.state["context"] = None
            self.state["resolve_connected"] = False
            self._set_readonly_var(self.resolve_var, "未连接")
            self._set_readonly_var(self.project_var, "")
            self._set_readonly_var(self.timeline_var, "")
            self._set_readonly_var(self.start_tc_var, "")
            self.timeline_combo.configure(values=[])
            self.timeline_combo.set("")
            self._set_auto_output_dir(None)
            self._set_status_header("Step 1 · 初始化 | Resolve 未连接：%s" % exc, warning=True)
            self.log("Resolve unavailable: %s" % exc)

    def selected_timeline_index(self):
        text = self.timeline_combo.get().strip()
        try:
            return int(text.split(".", 1)[0])
        except Exception:
            return 1

    def save_config_and_refresh(self, config):
        self.config = config
        save_config(self.config)
        self.state["output_dir_overridden"] = False
        self._set_auto_output_dir(self.state.get("context"))
        self.mode_combo.set(MODE_KEY_TO_LABEL.get(self.config.get("recognition_mode", "asr_remote"), MODE_SPECS[0][1]))
        self.log("Settings saved.")

    def on_mode_changed(self):
        self.config["recognition_mode"] = self._current_mode_key()
        save_config(self.config)
        self.log("Recognition mode set to %s" % self.config["recognition_mode"])

    def on_switch_timeline(self):
        def action():
            result = core.set_current_timeline(self.selected_timeline_index())
            self.log("Timeline switched to %s" % result["name"])
            self.refresh_status()
        self.safe(action)

    def on_fix_timecode(self):
        def action():
            result = core.fix_timecode()
            self.log("Timecode fixed: %s -> %s" % (result["old_timecode"], result["new_timecode"]))
            self.refresh_status()
        self.safe(action)

    def on_browse_output_dir(self):
        selected = self._select_dir()
        if selected:
            self.state["output_dir_overridden"] = True
            self.output_dir_var.set(selected)

    def on_browse_wav(self):
        selected = self._select_file([("WAV", "*.wav"), ("Audio", "*.wav *.mp3 *.m4a *.aac *.mp4")])
        if selected:
            self.wav_path_var.set(selected)

    def on_clear_wav(self):
        self.wav_path_var.set("")

    def on_browse_text(self):
        selected = self._select_file([("Text", "*.txt"), ("All files", "*.*")])
        if selected:
            self.text_path_var.set(selected)
            try:
                with open(selected, "r", encoding="utf-8-sig") as handle:
                    self.text_editor.delete("1.0", "end")
                    self.text_editor.insert("1.0", handle.read())
            except Exception as exc:
                self.log("Failed to load reference text: %s" % exc)

    def on_clear_text(self):
        self.text_path_var.set("")
        self.text_editor.delete("1.0", "end")

    def on_browse_srt(self):
        selected = self._select_file([("SRT", "*.srt"), ("All files", "*.*")])
        if selected:
            self.srt_path_var.set(selected)
            self.load_srt_preview_from_path(selected)

    def on_open_settings(self):
        SettingsDialog(self.root, self.config, self.save_config_and_refresh)

    def on_export_srt(self):
        def action():
            if not self.state.get("resolve_connected"):
                raise RuntimeError("Resolve is not connected")
            output_path = self.path_for("timeline_subtitles.srt")
            payload = core.export_subtitles_srt(output_path)
            self.update_srt_state("raw_srt", payload)
            self.state["final_srt"] = payload["path"]
            self.log("Current timeline subtitles exported to %s (%s items)" % (payload["path"], payload["count"]))
        self.safe(action)

    def on_import_srt(self):
        def action():
            if not self.state.get("resolve_connected"):
                raise RuntimeError("Resolve is not connected")
            srt_path = self.srt_path_var.get().strip()
            if not srt_path:
                raise RuntimeError("Please choose an SRT file first")
            srt_path = os.path.abspath(os.path.expanduser(srt_path))
            if not os.path.isfile(srt_path):
                raise RuntimeError("SRT file does not exist: %s" % srt_path)
            payload = core.import_srt(srt_path)
            self.state["final_srt"] = srt_path
            self.set_preview(payload)
            self.log("SRT imported to current timeline: %s (%s items)" % (srt_path, payload.get("count", 0)))
        self.safe(action)

    def run_in_thread(self, target):
        threading.Thread(target=self._wrap_thread(target), daemon=True).start()

    def _wrap_thread(self, target):
        def wrapper():
            try:
                target()
            except Exception as exc:
                self.log("ERROR: %s" % exc)
                self.log(traceback.format_exc())
                self.call_ui(lambda: messagebox.showerror(APP_NAME, str(exc)))
        return wrapper

    def on_generate(self):
        def action():
            mode = self._current_mode_key()
            mode_suffix = self._mode_suffix()
            raw_srt_path = self.path_for("subtitles_%s_raw.srt" % mode_suffix)
            self.log("Recognition mode set to %s" % mode)
            if mode == "resolve_builtin":
                if not self.state.get("resolve_connected"):
                    raise RuntimeError("Resolve is not connected")
                self.log("Running Resolve native subtitle generation")
                result = core.generate_subtitles(int(self.config.get("default_chars_per_line", 24)))
                self.log("Resolve generated %s subtitle items" % result["count"])
                payload = core.export_subtitles_srt(raw_srt_path)
                self.update_srt_state("raw_srt", payload)
                self.state["final_srt"] = payload["path"]
                self.log("Raw SRT exported to %s" % payload["path"])
                return

            selected_wav = self.wav_path_var.get().strip()
            if selected_wav:
                audio_path = os.path.abspath(os.path.expanduser(selected_wav))
                if not os.path.isfile(audio_path):
                    raise RuntimeError("WAV file does not exist: %s" % audio_path)
                self.log("Using selected WAV file: %s" % audio_path)
            else:
                if not self.state.get("resolve_connected"):
                    raise RuntimeError("Resolve is not connected and no WAV file was provided")
                self.log("Exporting timeline audio")
                exported_audio = self.run_worker({"action": "export_audio", "output": self.path_for("audio_%s.wav" % mode_suffix)})
                audio_path = exported_audio["path"]
                self.wav_path_var.set(audio_path)
                self.log("Audio ready at %s" % audio_path)
            self.state["audio_path"] = audio_path

            if not self.config.get("dashscope_api_key"):
                raise RuntimeError("Please configure DashScope API Key first")
            payload = self.run_worker(
                {
                    "action": "asr",
                    "audio": audio_path,
                    "output": raw_srt_path,
                    "lang": self.config.get("default_lang", "zh"),
                    "max_words": int(self.config.get("default_max_words", 24)),
                    "dashscope_api_key": self.config.get("dashscope_api_key", ""),
                    "region": self.config.get("region", "cn"),
                }
            )
            self.update_srt_state("raw_srt", payload)
            self.state["final_srt"] = payload["path"]
            self.log("Raw SRT generated: %s (%s items)" % (payload["path"], payload["count"]))

        self.run_in_thread(action)

    def on_optimize_text(self):
        def action():
            text = self.reference_text_content(required=True)
            dialog = ResultDialog(self.root, "%s 文案优化" % APP_NAME, stream_to_result=True)
            job = self.llm_job_defaults()
            job.update({"action": "llm_optimize_text", "text": text})
            payload = self.run_streaming_worker(job, dialog)
            optimized = payload.get("text", "").strip()
            if not optimized:
                raise RuntimeError("LLM returned empty optimized text")
            output_path = self.path_for("reference_optimized.txt")

            def save_result(result_text):
                with open(output_path, "w", encoding="utf-8") as handle:
                    handle.write(result_text)
                self.log("Optimized reference text saved: %s" % output_path)

            def apply_result(result_text):
                self.text_editor.delete("1.0", "end")
                self.text_editor.insert("1.0", result_text)
                self.log("Optimized reference text applied from %s" % output_path)

            dialog.set_result(optimized, apply_result, save_result)
            dialog.finish(True, "参考文案已生成并保存：%s" % output_path)

        self.run_in_thread(action)

    def on_convert_srt(self):
        def action():
            srt_path = self.srt_path_var.get().strip()
            if not srt_path:
                raise RuntimeError("Please choose an SRT file first")
            output_path = self.path_for("subtitles_proofread.srt")
            json_path = self.path_for("proofread.json")
            reference_text = self.reference_text_content(required=False)
            dialog = ResultDialog(self.root, "%s SRT 校对" % APP_NAME)
            if reference_text:
                dialog.append_status("已附加参考文案上下文：%s 字符" % len(reference_text))
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
            payload = self.run_streaming_worker(job, dialog)
            result_text = self._read_text_file(payload["path"])

            def save_result(result_text_inner):
                with open(payload["path"], "w", encoding="utf-8") as handle:
                    handle.write(result_text_inner)
                self.log("Proofread SRT saved: %s" % payload["path"])

            def apply_result(result_text_inner):
                with open(payload["path"], "w", encoding="utf-8") as handle:
                    handle.write(result_text_inner)
                updated_payload = core.run_read_srt({"path": payload["path"]})
                self.update_srt_state("processed_srt", updated_payload)
                self.state["final_srt"] = payload["path"]
                self.log("Proofread SRT applied: %s" % payload["path"])

            dialog.set_result(result_text, apply_result, save_result)
            dialog.finish(True, "校对 SRT 已生成并保存：%s" % payload["path"])

        self.run_in_thread(action)

    def on_translate(self):
        target_lang = simpledialog.askstring(APP_NAME, "目标语言（如 en / ja / zh-cn）", initialvalue=self.config.get("target_lang", "zh-cn"), parent=self.root)
        if not target_lang:
            return
        self.config["target_lang"] = target_lang.strip()
        save_config(self.config)

        def action():
            srt_path = self.srt_path_var.get().strip()
            if not srt_path:
                raise RuntimeError("Please choose an SRT file first")
            lang_suffix = self._safe_suffix(self.config["target_lang"])
            output_path = self.path_for("subtitles_%s.srt" % lang_suffix)
            json_path = self.path_for("translation_%s.json" % lang_suffix)
            dialog = ResultDialog(self.root, "%s SRT 翻译" % APP_NAME)
            job = self.llm_job_defaults()
            job.update(
                {
                    "action": "llm_srt_edit",
                    "mode": "translate",
                    "input": srt_path,
                    "output": output_path,
                    "json_output": json_path,
                    "target_lang": self.config["target_lang"],
                }
            )
            payload = self.run_streaming_worker(job, dialog)
            result_text = self._read_text_file(payload["path"])

            def save_result(result_text_inner):
                with open(payload["path"], "w", encoding="utf-8") as handle:
                    handle.write(result_text_inner)
                self.log("Translated SRT saved: %s" % payload["path"])

            def apply_result(result_text_inner):
                with open(payload["path"], "w", encoding="utf-8") as handle:
                    handle.write(result_text_inner)
                updated_payload = core.run_read_srt({"path": payload["path"]})
                self.update_srt_state("processed_srt", updated_payload)
                self.state["final_srt"] = payload["path"]
                self.log("Translated SRT applied: %s" % payload["path"])

            dialog.set_result(result_text, apply_result, save_result)
            dialog.finish(True, "翻译 SRT 已生成并保存：%s" % payload["path"])

        self.run_in_thread(action)

    def _read_text_file(self, path):
        with open(os.path.abspath(os.path.expanduser(path)), "r", encoding="utf-8-sig") as handle:
            return handle.read()

    def safe(self, fn):
        try:
            fn()
        except Exception as exc:
            self.log("ERROR: %s" % exc)
            self.log(traceback.format_exc())
            messagebox.showerror(APP_NAME, str(exc))

    def run(self):
        self.root.mainloop()


def _cli_asr(args, config):
    api_key = args.api_key or config.get("dashscope_api_key") or os.environ.get("DASHSCOPE_API_KEY", "")
    if not api_key:
        print("Error: DashScope API key required", file=sys.stderr)
        sys.exit(1)
    job = {
        "action": "asr",
        "audio": os.path.abspath(args.input),
        "output": os.path.abspath(args.output),
        "lang": args.lang,
        "region": config.get("region", "cn"),
        "dashscope_api_key": api_key,
        "max_words": int(config.get("default_max_words", 24)),
    }
    result = core.run_asr(job)
    print("OK: %s segments -> %s" % (result["count"], args.output))


def _cli_proofread(args, config):
    api_key = args.api_key or config.get("dashscope_api_key") or os.environ.get("DASHSCOPE_API_KEY", "")
    if not api_key:
        print("Error: API key required", file=sys.stderr)
        sys.exit(1)
    json_output = os.path.join(os.path.dirname(os.path.abspath(args.output)), "%s_proofread.json" % os.path.splitext(os.path.basename(args.output))[0])
    job = {
        "action": "llm_srt_edit",
        "mode": "proofread",
        "input": os.path.abspath(args.input),
        "output": os.path.abspath(args.output),
        "json_output": os.path.abspath(json_output),
        "api_key": api_key,
        "model": config.get("llm_model", DEFAULT_CONFIG["llm_model"]),
        "base_url": config.get("llm_base_url", DEFAULT_CONFIG["llm_base_url"]),
        "proofread_prompt": config.get("llm_proofread_prompt", core.DEFAULT_PROOFREAD_PROMPT),
        "enable_thinking": bool(config.get("llm_enable_thinking", False)),
    }
    run_streaming_job_local(job)
    print("Done -> %s" % args.output)


def _cli_translate(args, config):
    api_key = args.api_key or config.get("dashscope_api_key") or os.environ.get("DASHSCOPE_API_KEY", "")
    if not api_key:
        print("Error: API key required", file=sys.stderr)
        sys.exit(1)
    json_output = os.path.join(os.path.dirname(os.path.abspath(args.output)), "%s_%s.json" % (os.path.splitext(os.path.basename(args.output))[0], args.target))
    job = {
        "action": "llm_srt_edit",
        "mode": "translate",
        "input": os.path.abspath(args.input),
        "output": os.path.abspath(args.output),
        "json_output": os.path.abspath(json_output),
        "target_lang": args.target,
        "api_key": api_key,
        "model": config.get("llm_model", DEFAULT_CONFIG["llm_model"]),
        "base_url": config.get("llm_base_url", DEFAULT_CONFIG["llm_base_url"]),
        "translate_prompt": config.get("llm_translate_prompt", core.DEFAULT_TRANSLATE_PROMPT),
        "enable_thinking": bool(config.get("llm_enable_thinking", False)),
    }
    run_streaming_job_local(job)
    print("Done -> %s" % args.output)


def _cli_optimize(args, config):
    api_key = args.api_key or config.get("dashscope_api_key") or os.environ.get("DASHSCOPE_API_KEY", "")
    if not api_key:
        print("Error: API key required", file=sys.stderr)
        sys.exit(1)
    with open(args.input, "r", encoding="utf-8-sig") as handle:
        content = handle.read()
    job = {
        "action": "llm_optimize_text",
        "text": content,
        "api_key": api_key,
        "model": config.get("llm_model", DEFAULT_CONFIG["llm_model"]),
        "base_url": config.get("llm_base_url", DEFAULT_CONFIG["llm_base_url"]),
        "optimize_prompt": config.get("llm_optimize_prompt", core.DEFAULT_OPTIMIZE_PROMPT),
        "enable_thinking": bool(config.get("llm_enable_thinking", False)),
    }
    result = run_streaming_job_local(job)
    with open(args.output, "w", encoding="utf-8") as handle:
        handle.write(result["text"])
    print("Done -> %s" % args.output)


def _cli_convert(args):
    result = core.run_convert_srt({"action": "convert_srt", "input": os.path.abspath(args.input), "output": os.path.abspath(args.output), "lang": args.lang})
    print("OK: %s changes/%s segments -> %s" % (result.get("changed_count", 0), result.get("original_count", 0), args.output))


def _cli_read(args):
    data = core.run_read_srt({"path": os.path.abspath(args.input)})
    print("File: %s" % data["path"])
    print("Count: %s" % data["count"])
    for item in data["items"][:20]:
        print("  [%s] %s --> %s  %s" % (item["index"], item["start"], item["end"], item["text"][:60]))
    if data["count"] > 20:
        print("  ... (%s more)" % (data["count"] - 20))


def build_parser():
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--core-worker", dest="core_worker", help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("asr", help="Remote ASR on audio file")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--lang", default="zh")
    p.add_argument("--api-key")

    p = sub.add_parser("proofread", help="Proofread SRT with LLM")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--api-key")

    p = sub.add_parser("translate", help="Translate SRT with LLM")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--target", required=True)
    p.add_argument("--api-key")

    p = sub.add_parser("optimize", help="Optimize text with LLM")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--api-key")

    p = sub.add_parser("convert", help="Convert SRT (zh conversion)")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--lang", default="zh-cn")

    p = sub.add_parser("read", help="Read and display SRT")
    p.add_argument("input")
    return parser


def main():
    ensure_config()
    parser = build_parser()
    args = parser.parse_args()

    if args.core_worker:
        return core._cli_worker(args.core_worker)

    if args.command:
        config = load_config()
        if args.command == "asr":
            _cli_asr(args, config)
        elif args.command == "proofread":
            _cli_proofread(args, config)
        elif args.command == "translate":
            _cli_translate(args, config)
        elif args.command == "optimize":
            _cli_optimize(args, config)
        elif args.command == "convert":
            _cli_convert(args)
        elif args.command == "read":
            _cli_read(args)
        return 0

    if ctk is None:
        raise RuntimeError("customtkinter is not installed. Install dependencies with: pip install -r requirements.txt")
    app = SubtitleAgentApp()
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
