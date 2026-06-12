#!/usr/bin/env python3

import os
import re

from .bootstrap import SHORT_SUBTITLE_GAP_MS, SRT_TIME_RE, ensure_dir, load_json


def parse_srt_content(srt_content):
    blocks = re.split(r"\n\s*\n+", srt_content.strip()) if srt_content.strip() else []
    subtitles = []
    for block in blocks:
        lines = [line.rstrip("\r") for line in block.splitlines() if line.strip() != ""]
        if len(lines) < 3:
            continue
        try:
            index = int(lines[0])
        except ValueError:
            continue
        match = SRT_TIME_RE.match(lines[1])
        if not match:
            continue
        subtitles.append(
            {
                "index": index,
                "start": match.group(1),
                "end": match.group(2),
                "text": "\n".join(lines[2:]),
            }
        )
    return subtitles


def read_srt_file(path):
    with open(path, "r", encoding="utf-8-sig") as handle:
        content = handle.read()
    items = parse_srt_content(content)
    return {"success": True, "path": path, "count": len(items), "items": items, "content": content}


def ms_to_srt(ms):
    hours = int(ms // 3600000)
    minutes = int((ms % 3600000) // 60000)
    seconds = int((ms % 60000) // 1000)
    millis = int(ms % 1000)
    return "%02d:%02d:%02d,%03d" % (hours, minutes, seconds, millis)


def srt_to_ms(value):
    match = re.match(r"^(\d{2}):(\d{2}):(\d{2}),(\d{3})$", str(value or "").strip())
    if not match:
        raise RuntimeError("Invalid SRT timecode: %s" % value)
    hours, minutes, seconds, millis = [int(part) for part in match.groups()]
    return (((hours * 60) + minutes) * 60 + seconds) * 1000 + millis


def collapse_short_gaps(entries, min_gap_ms=SHORT_SUBTITLE_GAP_MS):
    if not entries:
        return []
    normalized = [
        {
            "index": entry["index"],
            "start": entry["start"],
            "end": entry["end"],
            "text": entry["text"],
        }
        for entry in entries
    ]
    for index in range(len(normalized) - 1):
        current = normalized[index]
        following = normalized[index + 1]
        current_end_ms = srt_to_ms(current["end"])
        next_start_ms = srt_to_ms(following["start"])
        gap_ms = next_start_ms - current_end_ms
        if 0 < gap_ms < int(min_gap_ms):
            midpoint_ms = current_end_ms + (gap_ms // 2)
            midpoint_tc = ms_to_srt(midpoint_ms)
            current["end"] = midpoint_tc
            following["start"] = midpoint_tc
    return normalized


def read_srt_entries(path):
    with open(path, "r", encoding="utf-8-sig") as handle:
        lines = handle.readlines()

    entries = []
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if not line:
            index += 1
            continue
        try:
            seq = int(line)
        except ValueError:
            index += 1
            continue
        if index + 1 >= len(lines):
            break
        match = SRT_TIME_RE.match(lines[index + 1].strip())
        if not match:
            index += 1
            continue
        start, end = match.groups()
        index += 2
        text_lines = []
        while index < len(lines) and lines[index].strip():
            text_lines.append(lines[index].rstrip("\r\n"))
            index += 1
        entries.append({"index": seq, "start": start, "end": end, "text": "\n".join(text_lines)})
        index += 1
    return entries


def write_srt_entries(path, entries):
    entries = collapse_short_gaps(entries)
    lines = []
    for entry in entries:
        lines.append(str(entry["index"]))
        lines.append("%s --> %s" % (entry["start"], entry["end"]))
        lines.append(entry["text"])
        lines.append("")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))


def load_corrections(path):
    if not path:
        return {}
    data = load_json(path, {})
    if not isinstance(data, dict):
        raise RuntimeError("Corrections file must be a JSON object")
    return data


def apply_corrections_to_text(text, corrections):
    for wrong, correct in corrections.items():
        text = text.replace(wrong, correct)
    return text


def zhconv_convert(text, lang):
    try:
        from zhconv import convert as zh_convert
    except ImportError:
        return text
    target = {
        "zh_cn": "zh-cn",
        "zh-cn": "zh-cn",
        "zh_tw": "zh-tw",
        "zh-tw": "zh-tw",
        "zh_hk": "zh-hk",
        "zh-hk": "zh-hk",
    }.get(lang.lower(), "zh-cn")
    return zh_convert(text, target)


def fix_cjk_spacing(text):
    text = re.sub(r"([\u4e00-\u9fff\u3400-\u4dbf\uff00-\uffef])\s+([a-zA-Z0-9])", r"\1\2", text)
    text = re.sub(r"([a-zA-Z0-9])\s+([\u4e00-\u9fff\u3400-\u4dbf\uff00-\uffef])", r"\1\2", text)
    return text


def fix_punctuation(text):
    text = re.sub(r"，,", "，", text)
    text = re.sub(r",，", "，", text)
    text = re.sub(r"[.][.]+", "…", text)
    text = re.sub(r"…\.", "…", text)
    text = re.sub(r"۔\.", "。", text)
    return text.replace('"', "「")


def run_read_srt(job):
    result = read_srt_file(os.path.abspath(job["path"]))
    result["logs"] = ["Loaded SRT: %s" % result["path"]]
    return result


def run_convert_srt(job):
    input_path = os.path.abspath(job["input"])
    output_path = os.path.abspath(job["output"])
    lang = job.get("lang", "zh-cn")
    corrections = load_corrections(job.get("corrections"))
    entries = read_srt_entries(input_path)
    logs = ["Converting SRT to %s" % lang]
    changed_count = 0
    original_count = len(entries)
    for entry in entries:
        before = entry["text"]
        text = before
        if corrections:
            text = apply_corrections_to_text(text, corrections)
        if lang:
            text = zhconv_convert(text, lang)
        text = fix_cjk_spacing(text)
        text = fix_punctuation(text)
        entry["text"] = text
        if text != before:
            changed_count += 1
    ensure_dir(os.path.dirname(output_path) or ".")
    write_srt_entries(output_path, entries)
    result = read_srt_file(output_path)
    result.update(
        {
            "original_count": original_count,
            "changed_count": changed_count,
            "logs": logs,
        }
    )
    return result


def run_apply_corrections(job):
    input_path = os.path.abspath(job["input"])
    output_path = os.path.abspath(job["output"])
    corrections = load_corrections(job.get("corrections"))
    entries = read_srt_entries(input_path)
    changed_count = 0
    for entry in entries:
        before = entry["text"]
        entry["text"] = apply_corrections_to_text(entry["text"], corrections)
        if entry["text"] != before:
            changed_count += 1
    ensure_dir(os.path.dirname(output_path) or ".")
    write_srt_entries(output_path, entries)
    result = read_srt_file(output_path)
    result.update({"changed_count": changed_count, "logs": ["Applied text replacements"]})
    return result

