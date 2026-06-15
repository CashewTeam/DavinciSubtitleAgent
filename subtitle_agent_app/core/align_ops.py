#!/usr/bin/env python3

import json
import os
import re
import subprocess
import sys
import tempfile

from .bootstrap import PROJECT_ROOT, ensure_dir, worker_log
from .srt_ops import ms_to_srt, read_srt_file, write_srt_entries


ALIGNER_DIR = "subtitle_agent_app/cpp-ort-aligner-macos-universal2"
ALIGNER_BIN = "cpp-ort-aligner"
PINYIN_TABLE = "Chinese_to_Pinyin.txt"

LANGUAGE_MAP = {
    "zh": "cmn",
    "zh-cn": "cmn",
    "zh-tw": "cmn",
    "zh-hk": "cmn",
    "zh_cn": "cmn",
    "zh_tw": "cmn",
    "zh_hk": "cmn",
    "en": "eng",
    "ja": "jpn",
    "jp": "jpn",
    "ko": "kor",
}

CJK_ALIGN_LANGS = {"cmn", "zho", "chi", "jpn", "kor"}


def _resource_root():
    return getattr(sys, "_MEIPASS", PROJECT_ROOT)


def _aligner_base_dir():
    return os.path.join(_resource_root(), ALIGNER_DIR)


def _aligner_bin_path():
    path = os.path.join(_aligner_base_dir(), ALIGNER_BIN)
    if not os.path.isfile(path):
        raise RuntimeError("Forced aligner binary not found: %s" % path)
    if not os.access(path, os.X_OK):
        raise RuntimeError("Forced aligner is not executable: %s" % path)
    return path


def _pinyin_table_path():
    path = os.path.join(_aligner_base_dir(), PINYIN_TABLE)
    if not os.path.isfile(path):
        raise RuntimeError("Chinese_to_Pinyin.txt not found: %s" % path)
    return path


def _detect_model_dir(model_dir):
    raw_model_dir = str(model_dir or "").strip()
    if not raw_model_dir:
        raise RuntimeError("Forced alignment model directory is required. Set align_model_dir in Settings first.")
    model_dir = os.path.abspath(os.path.expanduser(raw_model_dir))
    if not os.path.isdir(model_dir):
        raise RuntimeError("Forced alignment model directory does not exist: %s" % model_dir)

    mms = (
        os.path.isfile(os.path.join(model_dir, "model.onnx"))
        and os.path.isfile(os.path.join(model_dir, "vocab.json"))
    )
    omni = (
        os.path.isfile(os.path.join(model_dir, "model.int8.onnx"))
        and os.path.isfile(os.path.join(model_dir, "tokens.txt"))
    )
    if not (mms or omni):
        raise RuntimeError(
            "Invalid forced alignment model directory: %s. Expected model.onnx + vocab.json or model.int8.onnx + tokens.txt."
            % model_dir
        )
    return model_dir


def _language_code(language):
    raw = str(language or "").strip().lower()
    if not raw:
        return "cmn"
    return LANGUAGE_MAP.get(raw, raw)


def _default_romanize(language_code):
    return language_code in CJK_ALIGN_LANGS


def _normalize_text_block(text):
    text = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def _text_to_segments(text):
    text = _normalize_text_block(text)
    if not text:
        raise RuntimeError("Reference text is required for forced alignment")
    blocks = [block.strip() for block in re.split(r"\n\s*\n+", text) if block.strip()]
    segments = []
    if len(blocks) > 1:
        for block in blocks:
            segments.append({"text": block})
    else:
        for line in text.splitlines():
            line = line.strip()
            if line:
                segments.append({"text": line})
    if not segments:
        raise RuntimeError("Reference text did not produce any alignable segments")
    return segments


def _seconds_to_srt(value):
    millis = max(0, int(round(float(value or 0) * 1000)))
    return ms_to_srt(millis)


def _write_json(path, payload):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def _read_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_aligned_srt(json_output_path, output_path):
    payload = _read_json(json_output_path)
    segments = payload.get("segments", [])
    if not isinstance(segments, list) or not segments:
        raise RuntimeError("Forced aligner returned no segments")
    entries = []
    for index, segment in enumerate(segments, 1):
        entries.append(
            {
                "index": index,
                "start": _seconds_to_srt(segment.get("start", 0)),
                "end": _seconds_to_srt(segment.get("end", 0)),
                "text": str(segment.get("text", "")).strip(),
            }
        )
    ensure_dir(os.path.dirname(output_path) or ".")
    write_srt_entries(output_path, entries)
    result = read_srt_file(output_path)
    result["audio_duration"] = payload.get("audio_duration")
    return result


def run_forced_alignment(job):
    logs = []
    audio_path = os.path.abspath(os.path.expanduser(job.get("audio") or ""))
    output_path = os.path.abspath(os.path.expanduser(job.get("output") or ""))
    reference_text = job.get("reference_text") or ""
    if not audio_path:
        raise RuntimeError("Audio path is required for forced alignment")
    if not os.path.isfile(audio_path):
        raise RuntimeError("Audio file does not exist: %s" % audio_path)
    if not output_path:
        raise RuntimeError("Output path is required for forced alignment")

    aligner_path = _aligner_bin_path()
    model_dir = _detect_model_dir(job.get("model_dir"))
    language = _language_code(job.get("language"))
    romanize = job.get("romanize")
    if romanize is None:
        romanize = _default_romanize(language)
    segments = _text_to_segments(reference_text)

    batch_size = int(job.get("batch_size") or 4)
    threads = job.get("threads")

    worker_log(logs, "Running forced alignment")
    worker_log(logs, "Audio: %s" % audio_path)
    worker_log(logs, "Model: %s" % model_dir)
    worker_log(logs, "Language: %s%s" % (language, " + romanize" if romanize else ""))
    worker_log(logs, "Reference segments: %s" % len(segments))

    fd_input, json_input_path = tempfile.mkstemp(prefix="subtitle_agent_align_in_", suffix=".json")
    os.close(fd_input)
    fd_output, json_output_path = tempfile.mkstemp(prefix="subtitle_agent_align_out_", suffix=".json")
    os.close(fd_output)
    try:
        _write_json(json_input_path, {"segments": segments})
        cmd = [
            aligner_path,
            "--audio",
            audio_path,
            "--model",
            model_dir,
            "--json-input",
            json_input_path,
            "--json-output",
            json_output_path,
            "--language",
            language,
            "--batch-size",
            str(batch_size),
        ]
        if romanize:
            cmd.extend(["--romanize", "--pinyin-table", _pinyin_table_path()])
        if threads not in (None, ""):
            cmd.extend(["--threads", str(int(threads))])

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=3600,
            check=False,
        )
        if result.stdout.strip():
            for line in result.stdout.strip().splitlines():
                worker_log(logs, line)
        if result.stderr.strip():
            for line in result.stderr.strip().splitlines():
                worker_log(logs, line)
        if result.returncode != 0:
            raise RuntimeError("Forced aligner failed: %s" % ((result.stderr or result.stdout or "").strip() or "unknown error"))

        payload = _write_aligned_srt(json_output_path, output_path)
        payload.update(
            {
                "success": True,
                "logs": logs,
                "logs_streamed": True,
                "reference_segment_count": len(segments),
                "language": language,
                "romanize": bool(romanize),
                "model_dir": model_dir,
            }
        )
        return payload
    finally:
        for temp_path in (json_input_path, json_output_path):
            try:
                os.unlink(temp_path)
            except Exception:
                pass
