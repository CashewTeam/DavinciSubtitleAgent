#!/usr/bin/env python3

import html
import json
import os
import re
import sys
import tempfile


RESOLVE_SCRIPT_API = os.environ.get("RESOLVE_SCRIPT_API")
if RESOLVE_SCRIPT_API:
    sys.path.insert(0, os.path.join(RESOLVE_SCRIPT_API, "Modules"))
else:
    sys.path.insert(
        0,
        "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules",
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
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APP_SUPPORT_DIR = os.path.expanduser("~/Library/Application Support/SubtitleAgent")
CONFIG_PATH = os.environ.get("SUBTITLE_AGENT_CONFIG_PATH") or os.path.join(APP_SUPPORT_DIR, "subtitle_agent_config.json")
LEGACY_CONFIG_PATH = os.path.join(PROJECT_ROOT, "subtitle_agent", "subtitle_agent_config.json")

REGION_URLS = {
    "cn": "https://dashscope.aliyuncs.com/api/v1",
    "intl": "https://dashscope-intl.aliyuncs.com/api/v1",
}

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
SHORT_SUBTITLE_GAP_MS = 800

SRT_TIME_RE = re.compile(r"^(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})")
HTML_TAG_RE = re.compile(r"<[^>]+>")
ASS_OVERRIDE_RE = re.compile(r"\{\\[^}]*\}")


def load_json(path, default=None):
    if not os.path.isfile(path):
        return {} if default is None else default
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path, data):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)


def load_agent_config():
    return load_json(CONFIG_PATH, {})


def sanitize_name(name):
    return re.sub(r"[^\w\-]+", "_", name or "").strip("_") or "subtitle_agent"


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)
    return path


def worker_log(logs, message):
    logs.append(message)
    print(message, file=sys.stderr, flush=True)


def plain_subtitle_text(text):
    text = str(text or "")
    text = text.replace("\\N", "\n")
    text = ASS_OVERRIDE_RE.sub("", text)
    text = HTML_TAG_RE.sub("", text)
    return html.unescape(text).strip()


def temp_json(prefix, payload):
    fd, path = tempfile.mkstemp(prefix=prefix, suffix=".json")
    os.close(fd)
    write_json(path, payload)
    return path

