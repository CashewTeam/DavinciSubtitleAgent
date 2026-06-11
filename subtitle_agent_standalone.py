#!/usr/bin/env python3
"""
Subtitle Agent - GUI and CLI

GUI:
  python3 subtitle_agent_standalone.py

CLI:
  python3 subtitle_agent_standalone.py asr input.wav output.srt
  python3 subtitle_agent_standalone.py proofread input.srt output.srt
  python3 subtitle_agent_standalone.py translate input.srt output.srt --target en
  python3 subtitle_agent_standalone.py optimize input.txt output.txt
  python3 subtitle_agent_standalone.py convert input.srt output.srt --lang zh-tw
  python3 subtitle_agent_standalone.py read input.srt
"""

import argparse
import contextlib
import io
import json
import os
import sys
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

# ── Paths ──────────────────────────────────────────────────────────
SCRIPT_DIR = "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility"
AGENT_DIR = os.path.join(SCRIPT_DIR, "subtitle_agent")
CORE_PATH = os.path.join(AGENT_DIR, "subtitle_agent_core.tool")
CONFIG_PATH = os.path.join(AGENT_DIR, "subtitle_agent_config.json")

sys.path.insert(0, AGENT_DIR)

from importlib.machinery import SourceFileLoader
core = SourceFileLoader("subtitle_agent_core", CORE_PATH).load_module()


def load_config():
    config = core.load_json(CONFIG_PATH, {})
    for key in ("python_path", "custom_output_dir"):
        if config.get(key):
            config[key] = os.path.expanduser(config[key])
    return config


def save_config(config):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def run_streaming_job(job, on_event=None):
    buffer = io.StringIO()
    runner = core.run_llm_srt_edit_stream if job.get("action") == "llm_srt_edit" else core.run_llm_optimize_text_stream
    with contextlib.redirect_stdout(buffer):
        runner(job)
    result = None
    for raw_line in buffer.getvalue().splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except Exception:
            continue
        if on_event:
            on_event(event)
        event_type = event.get("type")
        if event_type == "error":
            raise RuntimeError(event.get("message", "Streaming worker failed"))
        if event_type == "result":
            result = event.get("payload") or {}
    if result is None:
        raise RuntimeError("Streaming worker returned no result")
    return result


# ── Application ────────────────────────────────────────────────────
class SubtitleAgentGUI:
    def __init__(self):
        self.config = load_config()
        self.state = {
            "output_dir": self.config.get("custom_output_dir", os.path.expanduser("~/Documents/subtitle_agent")),
        }

        self.root = tk.Tk()
        self.root.title("Subtitle Agent")
        self.root.geometry("1380x980")
        self.root.minsize(1000, 700)

        style = ttk.Style()
        style.theme_use("clam")

        self._build_ui()

    # ── UI Build ───────────────────────────────────────────────────
    def _build_ui(self):
        main = ttk.Frame(self.root, padding=8)
        main.pack(fill=tk.BOTH, expand=True)
        self._build_status(main)
        self._build_reference(main)
        self._build_actions(main)
        self._build_log(main)

    # ── Top: Files & output ────────────────────────────────────────
    def _build_status(self, parent):
        box = ttk.LabelFrame(parent, text="文件", padding=4)
        box.pack(fill=tk.X, pady=(0, 4))

        row1 = ttk.Frame(box)
        row1.pack(fill=tk.X, pady=1)
        ttk.Label(row1, text="WAV 音频:").pack(side=tk.LEFT)
        self.wav_path_var = tk.StringVar()
        e_wav = ttk.Entry(row1, textvariable=self.wav_path_var)
        e_wav.pack(side=tk.LEFT, padx=4, fill=tk.X, expand=True)
        ttk.Button(row1, text="浏览", command=lambda: self._browse_file(self.wav_path_var, [("WAV", "*.wav"), ("Audio", "*.wav *.mp3 *.m4a")])).pack(side=tk.LEFT, padx=2)

        row2 = ttk.Frame(box)
        row2.pack(fill=tk.X, pady=1)
        ttk.Label(row2, text="输出目录:").pack(side=tk.LEFT)
        self.out_dir_var = tk.StringVar(value=self.state["output_dir"])
        e_out = ttk.Entry(row2, textvariable=self.out_dir_var)
        e_out.pack(side=tk.LEFT, padx=4, fill=tk.X, expand=True)
        ttk.Button(row2, text="浏览", command=self._browse_dir).pack(side=tk.LEFT, padx=2)

    # ── Reference Text ─────────────────────────────────────────────
    def _build_reference(self, parent):
        box = ttk.LabelFrame(parent, text="参考文案", padding=4)
        box.pack(fill=tk.BOTH, expand=True, pady=(0, 4))

        top = ttk.Frame(box)
        top.pack(fill=tk.X)
        ttk.Label(top, text="文稿文件:").pack(side=tk.LEFT)
        self.text_path_var = tk.StringVar()
        e_txt = ttk.Entry(top, textvariable=self.text_path_var)
        e_txt.pack(side=tk.LEFT, padx=4, fill=tk.X, expand=True)
        ttk.Button(top, text="浏览", command=lambda: self._browse_file(self.text_path_var, [("Text", "*.txt"), ("All", "*")])).pack(side=tk.LEFT, padx=2)
        ttk.Button(top, text="加载", command=self._load_text_file).pack(side=tk.LEFT, padx=2)
        ttk.Button(top, text="优化文案", command=self._run_optimize_ui).pack(side=tk.LEFT, padx=2)

        self.text_editor = scrolledtext.ScrolledText(box, font=("Menlo", 11), height=14, wrap=tk.WORD)
        self.text_editor.pack(fill=tk.BOTH, expand=True, pady=(4, 0))

    def _load_text_file(self):
        path = self.text_path_var.get().strip()
        if path and os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                self.text_editor.delete(1.0, tk.END)
                self.text_editor.insert(1.0, f.read())
            self.log("已加载: %s" % path)

    # ── Actions ────────────────────────────────────────────────────
    def _build_actions(self, parent):
        box = ttk.LabelFrame(parent, text="操作", padding=4)
        box.pack(fill=tk.X, pady=(0, 4))

        row = ttk.Frame(box)
        row.pack(fill=tk.X)

        ttk.Button(row, text="开始识别", command=self._run_asr).pack(side=tk.LEFT, padx=3)
        ttk.Button(row, text="校对", command=self._on_proofread).pack(side=tk.LEFT, padx=3)
        ttk.Button(row, text="翻译", command=self._on_translate).pack(side=tk.LEFT, padx=3)
        ttk.Button(row, text="设置", command=self.open_settings).pack(side=tk.LEFT, padx=3)

    # ── Log + Preview ──────────────────────────────────────────────
    def _build_log(self, parent):
        panes = ttk.Frame(parent)
        panes.pack(fill=tk.BOTH, expand=True)
        panes.grid_columnconfigure(0, weight=1)
        panes.grid_columnconfigure(1, weight=1)
        panes.grid_rowconfigure(0, weight=1)

        left = ttk.LabelFrame(panes, text="日志", padding=2)
        left.grid(row=0, column=0, sticky=tk.NSEW, padx=(0, 2))
        self.log_text = scrolledtext.ScrolledText(left, font=("Menlo", 9), wrap=tk.WORD, state="normal")
        self.log_text.pack(fill=tk.BOTH, expand=True)

        right = ttk.LabelFrame(panes, text="字幕预览", padding=2)
        right.grid(row=0, column=1, sticky=tk.NSEW, padx=(2, 0))
        self.preview_text = scrolledtext.ScrolledText(right, font=("Menlo", 9), wrap=tk.WORD, state="normal")
        self.preview_text.pack(fill=tk.BOTH, expand=True)

    # ── Dialogs ────────────────────────────────────────────────────
    def open_settings(self):
        win = tk.Toplevel(self.root)
        win.title("Subtitle Agent 设置")
        win.geometry("960x700")
        win.transient(self.root)

        # Scrollable canvas for the whole settings
        canvas = tk.Canvas(win, highlightthickness=0)
        scrollbar = ttk.Scrollbar(win, orient=tk.VERTICAL, command=canvas.yview)
        scroll_frame = ttk.Frame(canvas)
        scroll_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scroll_frame, anchor=tk.NW)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        # Mousewheel scrolling
        def _on_mousewheel(event):
            canvas.yview_scroll(-1 * (event.delta // 120), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        win.protocol("WM_DELETE_WINDOW", lambda: (canvas.unbind_all("<MouseWheel>"), win.destroy()))

        f = ttk.Frame(scroll_frame, padding=15)
        f.pack(fill=tk.BOTH, expand=True)
        f.grid_columnconfigure(1, weight=1)

        row = [0]

        def label(text, r=None):
            r = r or row[0]
            ttk.Label(f, text=text).grid(row=r, column=0, sticky=tk.NW, pady=3, padx=(0, 5))
            return r

        def entry(width, default, r=None):
            r = r or row[0]
            e = ttk.Entry(f, width=width)
            e.insert(0, self.config.get(default, ""))
            e.grid(row=r, column=1, padx=5, pady=3, sticky=tk.EW)
            return e

        def combo(values, default, r=None):
            r = r or row[0]
            c = ttk.Combobox(f, values=values, state="readonly", width=20)
            val = self.config.get(default, values[0])
            c.set(val if val in values else values[0])
            c.grid(row=r, column=1, sticky=tk.W, padx=5, pady=3)
            return c

        def check(default, text="enable", r=None):
            r = r or row[0]
            var = tk.BooleanVar(value=bool(self.config.get(default, False)))
            cb = ttk.Checkbutton(f, text=text, variable=var)
            cb.grid(row=r, column=1, sticky=tk.W, padx=5, pady=3)
            return var

        def spin(minv, maxv, default, r=None):
            r = r or row[0]
            var = tk.StringVar(value=str(int(self.config.get(default, 0))))
            s = ttk.Spinbox(f, from_=minv, to=maxv, textvariable=var, width=8)
            s.grid(row=r, column=1, sticky=tk.W, padx=5, pady=3)
            return var

        def textarea(height, default, r=None):
            r = r or row[0]
            txt = scrolledtext.ScrolledText(f, font=("Menlo", 10), height=height, wrap=tk.WORD)
            txt.insert(1.0, self.config.get(default, ""))
            txt.grid(row=r, column=1, padx=5, pady=3, sticky=tk.EW)
            f.grid_rowconfigure(r, weight=1)
            return txt

        def next_row():
            row[0] += 1
            return row[0]

        # ── Fields ─────────────────────────────────────────────────
        r = next_row()
        label("输出目录", r)
        e_outdir = entry(50, "custom_output_dir", r)

        r = next_row()
        label("语言", r)
        c_lang = combo(["zh", "en", "yue", "ja", "ko"], "default_lang", r)

        r = next_row()
        label("目标语言", r)
        c_tlang = combo(["zh-cn", "zh-tw", "zh-hk"], "target_lang", r)

        r = next_row()
        label("DashScope API Key", r)
        e_key = ttk.Entry(f, width=50, show="*")
        e_key.insert(0, self.config.get("dashscope_api_key", ""))
        e_key.grid(row=r, column=1, padx=5, pady=3, sticky=tk.EW)

        r = next_row()
        label("region", r)
        c_region = combo(["cn", "intl"], "region", r)

        r = next_row()
        label("llm_model", r)
        e_model = entry(30, "llm_model", r)

        r = next_row()
        label("llm_base_url", r)
        e_url = entry(50, "llm_base_url", r)

        r = next_row()
        label("thinking", r)
        v_thinking = check("llm_enable_thinking", "enable", r)

        r = next_row()
        label("max_words", r)
        v_mw = spin(0, 200, "default_max_words", r)

        r = next_row()
        label("max_chars", r)
        v_mc = spin(0, 200, "default_max_chars", r)

        r = next_row()
        label("chars_per_line", r)
        v_cpl = spin(1, 200, "default_chars_per_line", r)

        r = next_row()
        label("校对提示词", r)
        t_proof = textarea(4, "llm_proofread_prompt", r)

        r = next_row()
        label("翻译提示词\n(可使用 {target_lang})", r)
        t_trans = textarea(4, "llm_translate_prompt", r)

        r = next_row()
        label("文案优化提示词", r)
        t_optim = textarea(4, "llm_optimize_prompt", r)

        # ── Save ───────────────────────────────────────────────────
        r = next_row()
        btn_frame = ttk.Frame(f)
        btn_frame.grid(row=r, column=1, sticky=tk.W, pady=12)

        def save():
            self.config["custom_output_dir"] = e_outdir.get().strip() or "~/Documents/subtitle_agent"
            self.config["default_lang"] = c_lang.get() or "zh"
            self.config["target_lang"] = c_tlang.get() or "zh-cn"
            self.config["dashscope_api_key"] = e_key.get().strip()
            self.config["region"] = c_region.get() or "cn"
            self.config["llm_model"] = e_model.get().strip() or "deepseek-v4-flash"
            self.config["llm_base_url"] = e_url.get().strip() or "https://dashscope.aliyuncs.com/compatible-mode/v1"
            self.config["llm_enable_thinking"] = v_thinking.get()
            self.config["default_max_words"] = int(v_mw.get() or 0)
            self.config["default_max_chars"] = int(v_mc.get() or 24)
            self.config["default_chars_per_line"] = int(v_cpl.get() or 24)
            self.config["llm_proofread_prompt"] = t_proof.get(1.0, tk.END).strip()
            self.config["llm_translate_prompt"] = t_trans.get(1.0, tk.END).strip()
            self.config["llm_optimize_prompt"] = t_optim.get(1.0, tk.END).strip()
            save_config(self.config)
            self.state["output_dir"] = self.config.get("custom_output_dir", "")
            self.out_dir_var.set(self.state["output_dir"])
            canvas.unbind_all("<MouseWheel>")
            messagebox.showinfo("设置", "已保存")
            win.destroy()

        ttk.Button(btn_frame, text="保存设置", command=save).pack(side=tk.LEFT, padx=3)
        ttk.Button(btn_frame, text="关闭", command=lambda: (canvas.unbind_all("<MouseWheel>"), win.destroy())).pack(side=tk.LEFT, padx=3)

    # ── Helpers ────────────────────────────────────────────────────
    def log(self, msg):
        self.log_text.insert(tk.END, msg + "\n")
        self.log_text.see(tk.END)
        self.root.update_idletasks()

    def log_result(self, msg):
        self.preview_text.insert(tk.END, msg + "\n")
        self.preview_text.see(tk.END)
        self.root.update_idletasks()

    def _browse_file(self, var, types):
        path = filedialog.askopenfilename(filetypes=types)
        if path:
            var.set(path)

    def _browse_dir(self):
        path = filedialog.askdirectory(initialdir=self.out_dir_var.get())
        if path:
            self.out_dir_var.set(path)
            self.state["output_dir"] = path

    def _api_key(self):
        return self.config.get("dashscope_api_key") or os.environ.get("DASHSCOPE_API_KEY", "")

    def _run_thread(self, target):
        threading.Thread(target=self._wrap(target), daemon=True).start()

    def _wrap(self, target):
        def wrapper():
            try:
                target()
            except Exception as e:
                self.root.after(0, lambda: self.log("错误: %s" % e))
                self.root.after(0, lambda: messagebox.showerror("错误", str(e)))
        return wrapper

    def _output_path(self, base, suffix):
        d = self.out_dir_var.get().strip() or os.path.expanduser("~/Documents/subtitle_agent")
        os.makedirs(d, exist_ok=True)
        name = os.path.splitext(os.path.basename(base) if base else "output")[0]
        return os.path.join(d, "%s_%s.srt" % (name, suffix))

    def _json_output_path(self, output_path, suffix):
        directory = os.path.dirname(os.path.abspath(output_path))
        os.makedirs(directory, exist_ok=True)
        name = os.path.splitext(os.path.basename(output_path))[0]
        return os.path.join(directory, "%s_%s.json" % (name, suffix))

    def _reference_text(self):
        text = self.text_editor.get(1.0, tk.END).strip()
        if text:
            return text
        path = self.text_path_var.get().strip()
        if path and os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                return f.read().strip()
        return ""

    # ── Actions ────────────────────────────────────────────────────
    def _run_asr(self):
        wav = self.wav_path_var.get().strip()
        if not wav or not os.path.isfile(wav):
            messagebox.showerror("错误", "请先选择 WAV 音频文件")
            return
        api_key = self._api_key()
        if not api_key:
            messagebox.showerror("错误", "请在 设置 中配置 DashScope API Key")
            return

        output = self._output_path(wav, "asr_remote")

        job = {
            "action": "asr", "audio": os.path.abspath(wav),
            "output": os.path.abspath(output), "lang": "zh",
            "region": self.config.get("region", "cn"),
            "dashscope_api_key": api_key, "max_words": 0,
        }

        def run():
            self.log("ASR 识别开始: %s" % os.path.basename(wav))
            self.log("输出到: %s" % output)
            result = core.run_asr(job)
            if result.get("success"):
                self.log("ASR 完成: %s 条字幕 -> %s" % (result["count"], output))
                self.log_result("ASR 结果 (%s 条):" % result["count"])
                for item in result["items"]:
                    self.log_result("[%s] %s --> %s  %s" % (item["index"], item["start"], item["end"], item["text"]))
            else:
                self.log("ASR 失败: %s" % result.get("error", "未知错误"))

        self._run_thread(run)

    def _on_proofread(self):
        api_key = self._api_key()
        if not api_key:
            messagebox.showerror("错误", "请在 设置 中配置 API Key")
            return

        path = filedialog.askopenfilename(title="选择要校对的 SRT 文件", filetypes=[("SRT", "*.srt")])
        if not path:
            return

        output = self._output_path(path, "proofread")
        json_output = self._json_output_path(output, "proofread")
        prompt = self.config.get("llm_proofread_prompt", "")
        reference_text = self._reference_text()

        job = {
            "action": "llm_srt_edit", "mode": "proofread",
            "input": os.path.abspath(path),
            "output": os.path.abspath(output),
            "json_output": os.path.abspath(json_output),
            "api_key": api_key,
            "model": self.config.get("llm_model", "deepseek-v4-flash"),
            "base_url": self.config.get("llm_base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            "proofread_prompt": prompt,
            "reference_text": reference_text,
            "enable_thinking": self.config.get("llm_enable_thinking", False),
        }

        def run():
            self.log("校对开始: %s" % os.path.basename(path))
            run_streaming_job(job)
            self.log("校对完成 -> %s" % output)
            self.log("校对 JSON -> %s" % json_output)
            self._view_srt(output)

        self._run_thread(run)

    def _on_translate(self):
        api_key = self._api_key()
        if not api_key:
            messagebox.showerror("错误", "请在 设置 中配置 API Key")
            return

        path = filedialog.askopenfilename(title="选择要翻译的 SRT 文件", filetypes=[("SRT", "*.srt")])
        if not path:
            return

        target = "en"
        output = self._output_path(path, target)
        json_output = self._json_output_path(output, target)
        prompt = self.config.get("llm_translate_prompt", "")

        job = {
            "action": "llm_srt_edit", "mode": "translate",
            "input": os.path.abspath(path),
            "output": os.path.abspath(output),
            "json_output": os.path.abspath(json_output),
            "target_lang": target,
            "api_key": api_key,
            "model": self.config.get("llm_model", "deepseek-v4-flash"),
            "base_url": self.config.get("llm_base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            "translate_prompt": prompt,
            "enable_thinking": self.config.get("llm_enable_thinking", False),
        }

        def run():
            self.log("翻译开始: %s -> %s" % (os.path.basename(path), target))
            run_streaming_job(job)
            self.log("翻译完成 -> %s" % output)
            self.log("翻译 JSON -> %s" % json_output)
            self._view_srt(output)

        self._run_thread(run)

    def _run_optimize_ui(self):
        text = self.text_editor.get(1.0, tk.END).strip()
        if not text:
            messagebox.showerror("错误", "请先在参考文案编辑区输入或粘贴文本")
            return
        api_key = self._api_key()
        if not api_key:
            messagebox.showerror("错误", "请在 设置 中配置 API Key")
            return
        output = os.path.join(self.out_dir_var.get().strip() or os.path.expanduser("~/Documents/subtitle_agent"), "reference_optimized.txt")
        prompt = self.config.get("llm_optimize_prompt", "")
        job = {
            "action": "llm_optimize_text",
            "text": text,
            "api_key": api_key,
            "model": self.config.get("llm_model", "deepseek-v4-flash"),
            "base_url": self.config.get("llm_base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            "optimize_prompt": prompt,
            "enable_thinking": self.config.get("llm_enable_thinking", False),
        }
        def run():
            self.log("优化开始...")
            result = run_streaming_job(job)
            optimized = result["text"]
            with open(output, "w", encoding="utf-8") as f:
                f.write(optimized)
            self.log("优化完成 -> %s" % output)
            self.text_editor.delete(1.0, tk.END)
            self.text_editor.insert(1.0, optimized)
            self.log("已更新编辑区内容")
        self._run_thread(run)

    def _view_srt(self, path):
        try:
            data = core.run_read_srt({"path": os.path.abspath(path)})
            self.preview_text.delete(1.0, tk.END)
            for item in data["items"][:50]:
                self.preview_text.insert(tk.END, "[%s] %s --> %s\n    %s\n\n" % (item["index"], item["start"], item["end"], item["text"]))
            if data["count"] > 50:
                self.preview_text.insert(tk.END, "... (共 %s 条)" % data["count"])
        except Exception as e:
            self.log("预览加载失败: %s" % e)

    # ── Run ────────────────────────────────────────────────────────
    def run(self):
        self.root.mainloop()


def _cli_asr(args):
    config = load_config()
    api_key = args.api_key or config.get("dashscope_api_key") or os.environ.get("DASHSCOPE_API_KEY", "")
    if not api_key:
        print("Error: DashScope API key required", file=sys.stderr); sys.exit(1)
    job = {"action": "asr", "audio": os.path.abspath(args.input), "output": os.path.abspath(args.output),
           "lang": args.lang, "region": config.get("region", "cn"), "dashscope_api_key": api_key, "max_words": 0}
    result = core.run_asr(job)
    if result.get("success"):
        print("OK: %s segments -> %s" % (result["count"], args.output))
    else:
        print("FAILED: %s" % result.get("error", "unknown"), file=sys.stderr); sys.exit(1)

def _cli_proofread(args):
    config = load_config()
    api_key = args.api_key or config.get("dashscope_api_key") or os.environ.get("DASHSCOPE_API_KEY", "")
    if not api_key:
        print("Error: API key required", file=sys.stderr); sys.exit(1)
    prompt = config.get("llm_proofread_prompt", "")
    json_output = os.path.join(
        os.path.dirname(os.path.abspath(args.output)),
        "%s_proofread.json" % os.path.splitext(os.path.basename(args.output))[0],
    )
    job = {"action": "llm_srt_edit", "mode": "proofread", "input": os.path.abspath(args.input),
           "output": os.path.abspath(args.output), "json_output": os.path.abspath(json_output), "api_key": api_key,
           "model": config.get("llm_model", "deepseek-v4-flash"),
           "base_url": config.get("llm_base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
           "proofread_prompt": prompt, "enable_thinking": config.get("llm_enable_thinking", False)}
    run_streaming_job(job)
    print("Done -> %s" % args.output)

def _cli_translate(args):
    config = load_config()
    api_key = args.api_key or config.get("dashscope_api_key") or os.environ.get("DASHSCOPE_API_KEY", "")
    if not api_key:
        print("Error: API key required", file=sys.stderr); sys.exit(1)
    prompt = config.get("llm_translate_prompt", "")
    json_output = os.path.join(
        os.path.dirname(os.path.abspath(args.output)),
        "%s_%s.json" % (os.path.splitext(os.path.basename(args.output))[0], args.target),
    )
    job = {"action": "llm_srt_edit", "mode": "translate", "input": os.path.abspath(args.input), "target_lang": args.target,
           "output": os.path.abspath(args.output), "json_output": os.path.abspath(json_output), "api_key": api_key,
           "model": config.get("llm_model", "deepseek-v4-flash"),
           "base_url": config.get("llm_base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
           "translate_prompt": prompt, "enable_thinking": config.get("llm_enable_thinking", False)}
    run_streaming_job(job)
    print("Done -> %s" % args.output)

def _cli_optimize(args):
    config = load_config()
    api_key = args.api_key or config.get("dashscope_api_key") or os.environ.get("DASHSCOPE_API_KEY", "")
    if not api_key:
        print("Error: API key required", file=sys.stderr); sys.exit(1)
    prompt = config.get("llm_optimize_prompt", "")
    with open(args.input, "r", encoding="utf-8") as f:
        content = f.read()
    job = {"action": "llm_optimize_text", "text": content,
           "api_key": api_key,
           "model": config.get("llm_model", "deepseek-v4-flash"),
           "base_url": config.get("llm_base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
           "optimize_prompt": prompt, "enable_thinking": config.get("llm_enable_thinking", False)}
    result = run_streaming_job(job)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(result["text"])
    print("Done -> %s" % args.output)

def _cli_convert(args):
    config = load_config()
    job = {"action": "convert_srt", "input": os.path.abspath(args.input),
           "output": os.path.abspath(args.output), "lang": args.lang}
    result = core.run_convert_srt(job)
    print("OK: %s changes/%s segments -> %s" % (result.get("changed_count", 0), result.get("original_count", 0), args.output))

def _cli_read(args):
    data = core.run_read_srt({"path": os.path.abspath(args.input)})
    print("File: %s" % data["path"])
    print("Count: %s" % data["count"])
    for item in data["items"][:20]:
        print("  [%s] %s --> %s  %s" % (item["index"], item["start"], item["end"], item["text"][:60]))
    if data["count"] > 20:
        print("  ... (%s more)" % (data["count"] - 20))


def main():
    parser = argparse.ArgumentParser(description="Subtitle Agent")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("asr", help="Remote ASR on audio file")
    p.add_argument("input"); p.add_argument("output"); p.add_argument("--lang", default="zh"); p.add_argument("--api-key")

    p = sub.add_parser("proofread", help="Proofread SRT with LLM")
    p.add_argument("input"); p.add_argument("output"); p.add_argument("--api-key")

    p = sub.add_parser("translate", help="Translate SRT with LLM")
    p.add_argument("input"); p.add_argument("output"); p.add_argument("--target", required=True); p.add_argument("--api-key")

    p = sub.add_parser("optimize", help="Optimize text with LLM")
    p.add_argument("input"); p.add_argument("output"); p.add_argument("--api-key")

    p = sub.add_parser("convert", help="Convert SRT (zh conversion)")
    p.add_argument("input"); p.add_argument("output"); p.add_argument("--lang", default="zh-cn")

    p = sub.add_parser("read", help="Read and display SRT")
    p.add_argument("input")

    args = parser.parse_args()
    if args.command == "asr": _cli_asr(args)
    elif args.command == "proofread": _cli_proofread(args)
    elif args.command == "translate": _cli_translate(args)
    elif args.command == "optimize": _cli_optimize(args)
    elif args.command == "convert": _cli_convert(args)
    elif args.command == "read": _cli_read(args)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ("asr", "proofread", "translate", "optimize", "convert", "read"):
        main()
    else:
        SubtitleAgentGUI().run()
