#!/usr/bin/env python3

import os
import time

from .bootstrap import REGION_URLS, ensure_dir, worker_log
from .srt_ops import parse_srt_content, read_srt_file, write_srt_entries, ms_to_srt


def init_dashscope(config):
    import dashscope

    api_key = (config.get("api_key") or os.environ.get("DASHSCOPE_API_KEY", "")).strip()
    if not api_key:
        raise RuntimeError("DashScope API key is missing")
    dashscope.api_key = api_key
    region = (config.get("region") or "cn").strip()
    dashscope.base_http_api_url = REGION_URLS.get(region, REGION_URLS["cn"])
    return dashscope


def upload_audio(audio_path, logs):
    from dashscope import Files

    worker_log(logs, "Uploading audio: %s" % os.path.basename(audio_path))
    response = Files.upload(file_path=audio_path, purpose="file_asr")
    file_id = response.get("output", {}).get("uploaded_files", [{}])[0].get("file_id", "")
    if not file_id:
        raise RuntimeError("Upload succeeded but file_id was missing")
    for _ in range(5):
        time.sleep(1)
        file_info = Files.get(file_id)
        if file_info:
            break
    else:
        raise RuntimeError("Uploaded file metadata was not ready")
    file_url = file_info.get("output", {}).get("url", "")
    if not file_url:
        raise RuntimeError("Failed to fetch uploaded file URL")
    return file_url


def transcribe_remote(file_url, language, config, logs):
    from dashscope.audio.asr import Transcription

    model = (config.get("model") or "").strip() or "fun-asr"
    max_retries = int(config.get("transcription_max_retries", 600))
    poll_interval = int(config.get("transcription_poll_interval", 2))
    worker_log(logs, "Submitting DashScope transcription (%s / %s)" % (model, language))
    task_response = Transcription.async_call(model=model, file_urls=[file_url], language_hints=[language])
    task_id = getattr(task_response, "output", {}).get("task_id", None)
    if not task_id:
        raise RuntimeError("DashScope transcription submission failed")
    for attempt in range(max_retries):
        time.sleep(poll_interval)
        result = Transcription.wait(task=task_id)
        status = getattr(result, "output", {}).get("task_status", "UNKNOWN")
        if status == "SUCCEEDED":
            worker_log(logs, "Remote transcription finished")
            return result
        if status == "FAILED":
            message = getattr(result, "output", {}).get("message", "unknown error")
            raise RuntimeError("Remote transcription failed: %s" % message)
        if attempt and attempt % max(1, 15 // max(poll_interval, 1)) == 0:
            worker_log(logs, "Waiting for remote transcription...")
    raise RuntimeError("Remote transcription timed out")


def result_to_srt(transcription_result, max_words=0):
    import requests

    output = transcription_result.get("output", {}) if isinstance(transcription_result, dict) else {}
    task_results = output.get("results", [])
    all_words = []
    for item in task_results:
        transcription_url = item.get("transcription_url", "")
        if not transcription_url:
            continue
        response = requests.get(transcription_url, timeout=30)
        response.raise_for_status()
        data = response.json()
        for transcript in data.get("transcripts", []):
            for sentence in transcript.get("sentences", []):
                words = sentence.get("words", [])
                if not words:
                    all_words.append({"begin_time": int(sentence.get("begin_time", 0)), "end_time": int(sentence.get("end_time", 0)), "text": sentence.get("text", "").strip(), "punct": ""})
                    continue
                for word in words:
                    all_words.append({"begin_time": int(word.get("begin_time", 0)), "end_time": int(word.get("end_time", 0)), "text": word.get("text", "").strip(), "punct": word.get("punctuation", "")})
    if not all_words:
        return "\n", 0
    lines = []
    punct_set = set("。！？，；：")
    buffer_text = ""
    buffer_start = 0
    buffer_end = 0
    buffer_len = 0

    def flush():
        nonlocal buffer_text, buffer_start, buffer_end, buffer_len
        text = buffer_text.strip().rstrip("，。！？；：、")
        if text:
            lines.append(str(len(lines) // 4 + 1))
            lines.append("%s --> %s" % (ms_to_srt(buffer_start), ms_to_srt(buffer_end)))
            lines.append(text)
            lines.append("")
        buffer_text = ""
        buffer_start = 0
        buffer_end = 0
        buffer_len = 0

    for word in all_words:
        punct = word.get("punct", "")
        if buffer_len == 0:
            buffer_start = word["begin_time"]
        buffer_text += word["text"] + punct
        buffer_end = word["end_time"]
        buffer_len += 1
        if punct and punct[-1] in punct_set:
            flush()
        elif max_words > 0 and buffer_len >= max_words:
            flush()
    flush()
    return "\n".join(lines), len(lines) // 4


def run_asr(job):
    config = {
        "api_key": job.get("dashscope_api_key", ""),
        "region": job.get("region", "cn"),
        "model": job.get("model", ""),
        "transcription_max_retries": job.get("transcription_max_retries", 600),
        "transcription_poll_interval": job.get("transcription_poll_interval", 2),
    }
    logs = []
    audio_path = os.path.abspath(job["audio"])
    output_path = os.path.abspath(job["output"])
    language = job.get("lang", "zh")
    max_words = int(job.get("max_words", 0))
    worker_log(logs, "Running remote ASR")
    init_dashscope(config)
    file_url = upload_audio(audio_path, logs)
    result = transcribe_remote(file_url, language, config, logs)
    srt_text, _ = result_to_srt(result, max_words=max_words)
    ensure_dir(os.path.dirname(output_path) or ".")
    write_srt_entries(output_path, parse_srt_content(srt_text))
    srt_data = read_srt_file(output_path)
    return {"success": True, "path": output_path, "count": len(srt_data["items"]), "items": srt_data["items"], "logs": logs, "logs_streamed": True}

