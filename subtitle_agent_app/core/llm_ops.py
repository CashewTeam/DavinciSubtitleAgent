#!/usr/bin/env python3

import json
import os
import re
import time

from .bootstrap import DEFAULT_OPTIMIZE_PROMPT, DEFAULT_PROOFREAD_PROMPT, DEFAULT_TRANSLATE_PROMPT, ensure_dir, write_json
from .srt_ops import read_srt_entries, read_srt_file, write_srt_entries


def _default_stream_event(event_type, **payload):
    payload["type"] = event_type
    print(json.dumps(payload, ensure_ascii=False), flush=True)


_STREAM_EVENT_HANDLER = _default_stream_event


def set_stream_event_handler(handler):
    global _STREAM_EVENT_HANDLER
    _STREAM_EVENT_HANDLER = handler or _default_stream_event


def get_stream_event_handler():
    return _STREAM_EVENT_HANDLER


def _stream_event(event_type, **payload):
    _STREAM_EVENT_HANDLER(event_type, **payload)


def safe_name(name):
    return re.sub(r"[^\w\-]+", "_", name or "").strip("_") or "subtitle_agent"


def format_exception_details(exc, max_depth=3):
    parts = []
    current = exc
    depth = 0
    while current is not None and depth < max_depth:
        text = str(current).strip()
        label = type(current).__name__
        parts.append("%s: %s" % (label, text) if text else label)
        current = current.__cause__ or current.__context__
        depth += 1
    return " | ".join(parts)


def require_llm_config(job):
    api_key = job.get("api_key") or os.environ.get("DASHSCOPE_API_KEY") or ""
    if not api_key:
        raise RuntimeError("dashscope_api_key is required for LLM features")
    try:
        from openai import OpenAI
    except ImportError:
        raise RuntimeError("openai is not installed. Run: pip install openai")
    return {
        "client": OpenAI(
            api_key=api_key,
            base_url=job.get("base_url") or "https://dashscope.aliyuncs.com/compatible-mode/v1",
            timeout=float(job.get("timeout_seconds") or 180),
            max_retries=int(job.get("connection_retries") or 3),
        ),
        "base_url": job.get("base_url") or "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": job.get("model") or "deepseek-v4-flash",
        "enable_thinking": bool(job.get("enable_thinking", True)),
        "timeout_seconds": float(job.get("timeout_seconds") or 180),
        "connection_retries": max(1, int(job.get("connection_retries") or 3)),
    }


def extract_json_object(text):
    text = (text or "").strip()
    if not text:
        raise RuntimeError("LLM response was empty")
    candidates = [text]
    fence_matches = re.findall(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    for match in fence_matches:
        match = (match or "").strip()
        if match:
            candidates.insert(0, match)
    decoder = json.JSONDecoder()
    parse_errors = []
    for candidate in candidates:
        for match in re.finditer(r"\{", candidate):
            start = match.start()
            try:
                parsed, _ = decoder.raw_decode(candidate[start:])
                if isinstance(parsed, dict):
                    return parsed
            except Exception as exc:
                parse_errors.append(str(exc))
        in_string = False
        escaped = False
        depth = 0
        start = None
        for index, char in enumerate(candidate):
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
                continue
            if char == "{":
                if depth == 0:
                    start = index
                depth += 1
            elif char == "}":
                if depth > 0:
                    depth -= 1
                    if depth == 0 and start is not None:
                        snippet = candidate[start : index + 1]
                        try:
                            parsed = json.loads(snippet)
                            if isinstance(parsed, dict):
                                return parsed
                        except Exception as exc:
                            parse_errors.append(str(exc))
                        start = None
    detail = parse_errors[-1] if parse_errors else "no JSON object found"
    preview = text[:400].replace("\n", "\\n")
    raise RuntimeError("Failed to parse LLM JSON object: %s. Preview: %s" % (detail, preview))


def validate_llm_srt_json(data):
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise RuntimeError("LLM JSON must be an object with an items list")
    normalized = []
    for item in data["items"]:
        if not isinstance(item, dict):
            continue
        if "index" not in item or "text" not in item:
            continue
        normalized.append({"index": int(item["index"]), "text": str(item["text"])})
    return {"items": normalized}


def validate_llm_replacements_json(data):
    if not isinstance(data, dict):
        raise RuntimeError("LLM proofread JSON must be an object with a replacements mapping")
    replacements = data.get("replacements")
    if not isinstance(replacements, dict):
        raise RuntimeError("LLM proofread JSON must contain a replacements object")
    normalized = []
    for wrong, correct in replacements.items():
        wrong_text = str(wrong or "").strip()
        correct_text = str(correct or "").strip()
        if not wrong_text or wrong_text == correct_text:
            continue
        normalized.append((wrong_text, correct_text))
    return {"replacements": dict(normalized)}


def normalized_replacement_items(replacements):
    normalized = []
    for wrong, correct in (replacements or {}).items():
        wrong_text = str(wrong or "").strip()
        correct_text = str(correct or "").strip()
        if not wrong_text or wrong_text == correct_text:
            continue
        normalized.append((wrong_text, correct_text))
    normalized.sort(key=lambda item: len(item[0]), reverse=True)
    return normalized


def apply_index_text_edits(input_path, output_path, edit_json):
    entries = read_srt_entries(input_path)
    edits = {int(item["index"]): item["text"] for item in edit_json.get("items", [])}
    changed_count = 0
    for entry in entries:
        index = int(entry["index"])
        if index in edits and entry["text"] != edits[index]:
            entry["text"] = edits[index]
            changed_count += 1
    write_srt_entries(output_path, entries)
    result = read_srt_file(output_path)
    result.update({"changed_count": changed_count})
    return result


def apply_replacements_to_srt(input_path, output_path, replacements_json):
    entries = read_srt_entries(input_path)
    replacements = normalized_replacement_items(replacements_json.get("replacements") or {})
    changed_count = 0
    for entry in entries:
        original_text = entry["text"]
        updated_text = original_text
        placeholders = []
        for index, (wrong, correct) in enumerate(replacements):
            placeholder = "__SUBTITLE_AGENT_REPL_%s__" % index
            if wrong in updated_text:
                updated_text = updated_text.replace(wrong, placeholder)
                placeholders.append((placeholder, correct))
        for placeholder, correct in placeholders:
            updated_text = updated_text.replace(placeholder, correct)
        if updated_text != original_text:
            entry["text"] = updated_text
            changed_count += 1
    write_srt_entries(output_path, entries)
    result = read_srt_file(output_path)
    result.update({"changed_count": changed_count, "replacement_count": len(replacements)})
    return result


def llm_stream_chat(job, messages):
    config = require_llm_config(job)
    _stream_event("status", message="连接 LLM：%s" % config["model"])
    _stream_event("status", message="LLM endpoint：%s，timeout=%ss" % (config["base_url"], int(config["timeout_seconds"])))
    try:
        import httpx
    except Exception:
        httpx = None
    try:
        from openai import APIConnectionError, APITimeoutError

        retryable = [APIConnectionError, APITimeoutError]
    except Exception:
        retryable = []
    if httpx is not None:
        retryable.extend([httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError, httpx.ConnectTimeout])
    retryable = tuple(retryable) if retryable else (Exception,)
    last_detail = ""
    for attempt in range(1, config["connection_retries"] + 1):
        try:
            stream = config["client"].chat.completions.create(
                model=config["model"],
                messages=messages,
                extra_body={"enable_thinking": config["enable_thinking"]},
                stream=True,
                stream_options={"include_usage": True},
            )
            answer_content = ""
            reasoning_length = 0
            for chunk in stream:
                if not getattr(chunk, "choices", None):
                    usage = getattr(chunk, "usage", None)
                    if usage is not None:
                        _stream_event("status", message="Token 消耗：%s" % usage)
                    continue
                delta = chunk.choices[0].delta
                reasoning = getattr(delta, "reasoning_content", None)
                if reasoning:
                    reasoning_length += len(reasoning)
                    _stream_event("reasoning_summary", message="思维链文本长度：%s 字符" % reasoning_length)
                content = getattr(delta, "content", None)
                if content:
                    answer_content += content
                    _stream_event("content_delta", text=content)
            return answer_content
        except retryable as exc:
            last_detail = format_exception_details(exc)
            if attempt < config["connection_retries"]:
                wait_seconds = min(5, 2 ** (attempt - 1))
                _stream_event("status", message="LLM 连接异常，第 %s/%s 次重试前等待 %ss：%s" % (attempt, config["connection_retries"], wait_seconds, last_detail))
                time.sleep(wait_seconds)
                continue
            raise RuntimeError("LLM connection failed after %s attempts. endpoint=%s model=%s detail=%s" % (config["connection_retries"], config["base_url"], config["model"], last_detail))
        except Exception as exc:
            detail = format_exception_details(exc)
            raise RuntimeError("LLM request failed. endpoint=%s model=%s detail=%s" % (config["base_url"], config["model"], detail))
    raise RuntimeError("LLM connection failed. endpoint=%s model=%s detail=%s" % (config["base_url"], config["model"], last_detail or "unknown error"))


def run_llm_srt_edit_stream(job):
    input_path = os.path.abspath(job["input"])
    output_path = os.path.abspath(job["output"])
    json_output = os.path.abspath(job["json_output"])
    mode = job.get("mode", "proofread")
    target_lang = job.get("target_lang", "zh-cn")
    srt_data = read_srt_file(input_path)
    mode_text = "翻译" if mode == "translate" else "校对"
    _stream_event("status", message="读取 SRT：%s（%s 条）" % (input_path, srt_data["count"]))
    if mode == "translate":
        instruction = (job.get("translate_prompt") or DEFAULT_TRANSLATE_PROMPT).replace("{target_lang}", target_lang)
        reference_section = ""
    else:
        instruction = job.get("proofread_prompt") or DEFAULT_PROOFREAD_PROMPT
        reference_text = (job.get("reference_text") or "").strip()
        reference_section = ""
        if reference_text:
            reference_section = (
                "\n\n参考文案如下。请将它作为校对依据，用来判断专有名词、英文大小写、"
                "术语、人物称呼、上下文语义和漏识别/误识别；但输出仍必须只针对 SRT 条目文本，"
                "不要新增、删除或移动字幕条目：\n%s"
                % reference_text
            )
    messages = [
        {
            "role": "system",
            "content": (
                "你是专业影视字幕编辑。"
                "当任务是校对时，必须只输出 JSON 对象，格式为 "
                "{\"replacements\":{\"错误文本\":\"正确文本\"}}。"
                "当任务是翻译时，必须只输出 JSON 对象，格式为 "
                "{\"items\":[{\"index\":1,\"text\":\"修改后的字幕文本\"}]}。"
                "不要输出 markdown 或解释。"
            ),
        },
        {"role": "user", "content": "%s%s\n\nSRT 内容如下：\n%s" % (instruction, reference_section, srt_data["content"])},
    ]
    _stream_event("status", message="调用 LLM 生成%s JSON" % mode_text)
    answer = llm_stream_chat(job, messages)
    _stream_event("status", message="解析 LLM JSON")
    if mode == "translate":
        edit_json = validate_llm_srt_json(extract_json_object(answer))
    else:
        edit_json = validate_llm_replacements_json(extract_json_object(answer))
    ensure_dir(os.path.dirname(json_output) or ".")
    write_json(json_output, edit_json)
    _stream_event("status", message="应用 JSON 到新 SRT")
    if mode == "translate":
        result = apply_index_text_edits(input_path, output_path, edit_json)
    else:
        result = apply_replacements_to_srt(input_path, output_path, edit_json)
    result.update({"json_path": json_output, "logs": ["LLM %s JSON written to %s" % (mode_text, json_output), "LLM %s SRT written to %s" % (mode_text, output_path)]})
    _stream_event("result", payload=result)


def run_llm_optimize_text_stream(job):
    text = (job.get("text") or "").strip()
    if not text:
        raise RuntimeError("Reference text is empty")
    _stream_event("status", message="调用 LLM 优化参考文案")
    prompt = job.get("optimize_prompt") or DEFAULT_OPTIMIZE_PROMPT
    messages = [{"role": "system", "content": prompt}, {"role": "user", "content": text}]
    optimized = llm_stream_chat(job, messages).strip()
    _stream_event("result", payload={"success": True, "text": optimized, "logs": ["Reference text optimized by LLM"]})

