#!/usr/bin/env python3

import argparse
import contextlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time


def _prepend_tool_paths():
    tool_paths = ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin"]
    current = os.environ.get("PATH", "")
    parts = [part for part in current.split(os.pathsep) if part] if current else []
    for path in reversed(tool_paths):
        if path not in parts:
            parts.insert(0, path)
    os.environ["PATH"] = os.pathsep.join(parts)


_prepend_tool_paths()

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
CONFIG_PATH = os.path.join(SCRIPT_DIR, "subtitle_agent_config.json")

LANG_MODELS = {
    "zh": "fun-asr",
    "en": "fun-asr",
    "yue": "fun-asr-mtl-2025-08-25",
    "ja": "fun-asr-mtl-2025-08-25",
    "ko": "fun-asr-mtl-2025-08-25",
    "th": "fun-asr-mtl-2025-08-25",
    "vi": "fun-asr-mtl-2025-08-25",
    "id": "fun-asr-mtl-2025-08-25",
}

REGION_URLS = {
    "cn": "https://dashscope.aliyuncs.com/api/v1",
    "intl": "https://dashscope-intl.aliyuncs.com/api/v1",
}

DEFAULT_PROOFREAD_PROMPT = (
    "请作为专业影视字幕校对编辑，对每条字幕进行精修：修正错别字、ASR 误识别、断句，字幕末尾多余标点符号需要去除；"
    "中英空格、英文大小写拼写错误、口语不顺和明显术语错误；保持原意、语气、人物称呼和专有名词一致；"
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

SRT_TIME_RE = re.compile(r"^(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})")
PUNCT_WHITESPACE = set("，。！？；：\n\r \t\u201c\u201d\u2018\u2019")
ALIGN_SPLIT_CHARS = set("，。！？；：\n\r")
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


def _worker_log(logs, message):
    logs.append(message)
    print(message, file=sys.stderr, flush=True)


def _configure_model_cache(cache_dir=None, logs=None):
    cache_dir = cache_dir or os.environ.get("MODELSCOPE_CACHE", "")
    if not str(cache_dir).strip():
        return ""
    cache_dir = os.path.abspath(os.path.expanduser(str(cache_dir).strip()))
    os.makedirs(cache_dir, exist_ok=True)
    os.environ["MODELSCOPE_CACHE"] = cache_dir
    os.environ["MODELSCOPE_HUB_CACHE"] = cache_dir
    os.environ["FUNASR_CACHE"] = cache_dir
    if logs is not None:
        _worker_log(logs, "Model cache directory: %s" % cache_dir)
    return cache_dir


def load_agent_config():
    return load_json(CONFIG_PATH, {})


def sanitize_name(name):
    return re.sub(r"[^\w\-]+", "_", name or "").strip("_") or "subtitle_agent"


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)
    return path


def _get_resolve():
    import DaVinciResolveScript as dvr

    return dvr.scriptapp("Resolve")


def _require_resolve():
    resolve = _get_resolve()
    if not resolve:
        raise RuntimeError("DaVinci Resolve is not running or scripting is disabled")
    return resolve


def _require_project(resolve=None):
    resolve = resolve or _require_resolve()
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        raise RuntimeError("No project is currently open")
    return project


def _require_timeline(project=None):
    project = project or _require_project()
    timeline = project.GetCurrentTimeline()
    if not timeline:
        raise RuntimeError("No timeline is currently active")
    return timeline


def get_resolve_context():
    resolve = _require_resolve()
    project = _require_project(resolve)
    timeline = _require_timeline(project)
    version = {
        "product": resolve.GetProductName(),
        "version_string": resolve.GetVersionString(),
        "version": resolve.GetVersion(),
    }
    timelines = list_timelines(project)
    context = {
        "version": version,
        "project_name": project.GetName(),
        "project_name_safe": sanitize_name(project.GetName()),
        "current_timeline": timeline.GetName(),
        "start_timecode": timeline.GetStartTimecode(),
        "timelines": timelines,
    }
    if not context["start_timecode"].startswith("00"):
        context["warning"] = (
            "Timeline start timecode is not 00:00:00:00. SRT timing may be misaligned outside Resolve."
        )
    return context


def list_timelines(project=None):
    project = project or _require_project()
    count = project.GetTimelineCount()
    timelines = []
    for index in range(1, count + 1):
        timeline = project.GetTimelineByIndex(index)
        if timeline:
            timelines.append(
                {
                    "index": index,
                    "name": timeline.GetName(),
                    "start_frame": timeline.GetStartFrame(),
                    "end_frame": timeline.GetEndFrame(),
                    "start_timecode": timeline.GetStartTimecode(),
                }
            )
    return timelines


def set_current_timeline(index):
    project = _require_project()
    timeline = project.GetTimelineByIndex(int(index))
    if not timeline:
        raise RuntimeError("Timeline index %s not found" % index)
    if not project.SetCurrentTimeline(timeline):
        raise RuntimeError("Failed to switch timeline")
    return {
        "index": int(index),
        "name": timeline.GetName(),
        "start_timecode": timeline.GetStartTimecode(),
    }


def fix_timecode():
    timeline = _require_timeline()
    old_tc = timeline.GetStartTimecode()
    result = timeline.SetStartTimecode("00:00:00:00")
    new_tc = timeline.GetStartTimecode()
    if not result or new_tc != "00:00:00:00":
        raise RuntimeError("Failed to set start timecode (was %s)" % old_tc)
    return {"success": True, "old_timecode": old_tc, "new_timecode": new_tc}


def _frames_to_srt_tc(frames, fps):
    total_secs = frames / fps
    hours = int(total_secs // 3600)
    minutes = int((total_secs % 3600) // 60)
    seconds = int(total_secs % 60)
    millis = int(round((total_secs - int(total_secs)) * 1000))
    if millis >= 1000:
        seconds += 1
        millis = 0
    return "%02d:%02d:%02d,%03d" % (hours, minutes, seconds, millis)


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


def _plain_subtitle_text(text):
    text = str(text or "")
    text = text.replace("\\N", "\n")
    text = ASS_OVERRIDE_RE.sub("", text)
    text = HTML_TAG_RE.sub("", text)
    return html.unescape(text).strip()


def export_subtitles_srt(output_path):
    timeline = _require_timeline()
    items = timeline.GetItemListInTrack("subtitle", 1) or []
    if not items:
        raise RuntimeError("No subtitle items found on the timeline")
    project = _require_project()
    fps_str = project.GetSetting("timelineFrameRate")
    fps = float(fps_str) if fps_str else 24.0
    lines = []
    for idx, item in enumerate(items, 1):
        lines.append(str(idx))
        lines.append(
            "%s --> %s"
            % (_frames_to_srt_tc(item.GetStart(), fps), _frames_to_srt_tc(item.GetEnd(), fps))
        )
        lines.append(_plain_subtitle_text(item.GetName()))
        lines.append("")
    output_path = os.path.abspath(output_path)
    ensure_dir(os.path.dirname(output_path) or ".")
    with open(output_path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    return read_srt_file(output_path)


def _delete_all_subtitle_tracks(timeline):
    count = timeline.GetTrackCount("subtitle")
    while count > 0:
        timeline.DeleteTrack("subtitle", count)
        count = timeline.GetTrackCount("subtitle")


def generate_subtitles(chars_per_line=24):
    resolve = _require_resolve()
    project = _require_project(resolve)
    timeline = _require_timeline(project)
    _delete_all_subtitle_tracks(timeline)
    timeline.AddTrack("subtitle")
    settings = {resolve.SUBTITLE_CHARS_PER_LINE: int(chars_per_line)}
    result = timeline.CreateSubtitlesFromAudio(settings)
    if not result:
        raise RuntimeError("Failed to generate subtitles from audio")
    items = timeline.GetItemListInTrack("subtitle", 1) or []
    return {
        "success": True,
        "count": len(items),
        "items": [{"start": item.GetStart(), "end": item.GetEnd(), "text": item.GetName()} for item in items],
    }


def _find_rendered_file(target_dir, base_name, extensions=None, since=None):
    if not os.path.isdir(target_dir):
        return None
    matches = []
    wanted = set(ext.lower() for ext in extensions) if extensions else None
    for name in os.listdir(target_dir):
        if not name.startswith(base_name):
            continue
        path = os.path.join(target_dir, name)
        if not os.path.isfile(path):
            continue
        ext = os.path.splitext(name)[1].lower()
        if wanted is not None and ext not in wanted:
            continue
        try:
            mtime = os.path.getmtime(path)
        except Exception:
            mtime = 0
        if since is not None and mtime + 2 < since:
            continue
        matches.append((mtime, path))
    if not matches:
        return None
    return sorted(matches)[-1][1]


def _ffmpeg_exe():
    found = shutil.which("ffmpeg")
    if found:
        return found
    for candidate in ("/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/usr/bin/ffmpeg"):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    raise RuntimeError("ffmpeg not found. Install ffmpeg or add it to PATH")


def _convert_to_wav(input_path, output_path):
    ensure_dir(os.path.dirname(os.path.abspath(output_path)) or ".")
    cmd = [
        _ffmpeg_exe(),
        "-y",
        "-i",
        input_path,
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        "48000",
        output_path,
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=900,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("ffmpeg WAV conversion failed: %s" % (result.stderr or "")[-800:])
    if not os.path.isfile(output_path):
        raise RuntimeError("ffmpeg completed but WAV output was not found: %s" % output_path)
    return output_path


def _start_render_and_wait(project):
    render_fn = getattr(project, "Render", None)
    if callable(render_fn):
        result = render_fn()
        if not result:
            raise RuntimeError("Failed to start render job")
    else:
        add_job = getattr(project, "AddRenderJob", None)
        start_rendering = getattr(project, "StartRendering", None)
        if not callable(add_job) or not callable(start_rendering):
            raise RuntimeError("No callable render API found on Resolve project")
        job_id = add_job()
        if not job_id:
            raise RuntimeError("Failed to add render job")
        try:
            started = start_rendering(job_id)
        except TypeError:
            started = start_rendering([job_id])
        if not started:
            raise RuntimeError("Failed to start render job: %s" % job_id)

    is_rendering = getattr(project, "IsRenderingInProgress", None)
    if callable(is_rendering):
        while is_rendering():
            time.sleep(1)


def export_audio(output_path):
    resolve = _require_resolve()
    project = _require_project(resolve)
    _require_timeline(project)

    output_path = os.path.abspath(output_path)
    target_dir = os.path.dirname(output_path)
    base_name = os.path.splitext(os.path.basename(output_path))[0]
    ensure_dir(target_dir)

    old_page = None
    try:
        old_page = resolve.GetCurrentPage()
        resolve.OpenPage("deliver")
    except Exception:
        old_page = None

    old_format = None
    try:
        fmt = project.GetCurrentRenderFormatAndCodec()
        if fmt:
            old_format = (fmt.get("format"), fmt.get("codec"))
    except Exception:
        old_format = None

    project.DeleteAllRenderJobs()
    render_started_at = time.time()

    base_settings = {
        "ExportVideo": False,
        "ExportAudio": True,
        "TargetDir": target_dir,
        "CustomName": base_name,
        "AudioBitDepth": 16,
        "AudioSampleRate": 48000,
        "SelectAllFrames": True,
    }
    attempts = []

    def remember(label, ok, error=None):
        attempts.append({"label": label, "ok": bool(ok), "error": str(error or "")})

    def try_render_with_current_format(format_name, codec_name, audio_codec):
        label = "SetCurrentRenderFormatAndCodec(%r, %r), AudioCodec=%r" % (
            format_name,
            codec_name,
            audio_codec,
        )
        try:
            if not project.SetCurrentRenderFormatAndCodec(format_name, codec_name):
                remember(label, False)
                return False
            settings = dict(base_settings)
            if audio_codec is not None:
                settings["AudioCodec"] = audio_codec
            if not project.SetRenderSettings(settings):
                remember(label + " SetRenderSettings", False)
                return False
            remember(label, True)
            return True
        except Exception as exc:
            remember(label, False, exc)
            return False

    def try_render_settings_only(format_name, audio_codec):
        label = "SetRenderSettings Format=%r, AudioCodec=%r" % (format_name, audio_codec)
        try:
            settings = dict(base_settings)
            settings["Format"] = format_name
            settings["AudioCodec"] = audio_codec
            ok = project.SetRenderSettings(settings)
            remember(label, ok)
            return bool(ok)
        except Exception as exc:
            remember(label, False, exc)
            return False

    def try_audio_only_preset(preset_name):
        label = "LoadRenderPreset(%r)" % preset_name
        try:
            if not project.LoadRenderPreset(preset_name):
                remember(label, False)
                return False
            settings = dict(base_settings)
            if project.SetRenderSettings(settings):
                remember(label, True)
                return True
            minimal_settings = {
                "TargetDir": target_dir,
                "CustomName": base_name,
                "SelectAllFrames": True,
            }
            ok = project.SetRenderSettings(minimal_settings)
            remember(label + " minimal SetRenderSettings", ok)
            return bool(ok)
        except Exception as exc:
            remember(label, False, exc)
            return False

    configured = False
    preset_attempts = [
        "Audio Only",
        "Audio Only - Wave",
        "Audio Only (WAV)",
        "WAV",
        "Wave",
    ]
    for preset_name in preset_attempts:
        if try_audio_only_preset(preset_name):
            configured = True
            break

    current_attempts = [
        ("wav", "pcm_s16le", "pcm_s16le"),
        ("Wave", "Linear PCM", "Linear PCM"),
        ("Wave", "LinearPCM", "LinearPCM"),
        ("wav", "LinearPCM", "LinearPCM"),
        ("wav", "Linear PCM", "Linear PCM"),
        ("wav", "", "LinearPCM"),
    ]
    if not configured:
        for format_name, codec_name, audio_codec in current_attempts:
            if try_render_with_current_format(format_name, codec_name, audio_codec):
                configured = True
                break

    if not configured:
        settings_attempts = [
            ("wav", "LinearPCM"),
            ("wav", "Linear PCM"),
            ("Wave", "LinearPCM"),
            ("Wave", "Linear PCM"),
            ("wav", "pcm_s16le"),
        ]
        for format_name, audio_codec in settings_attempts:
            if try_render_settings_only(format_name, audio_codec):
                configured = True
                break

    if not configured:
        diagnostics = {}
        try:
            diagnostics["formats"] = project.GetRenderFormats()
        except Exception as exc:
            diagnostics["formats_error"] = str(exc)
        for key in ("wav", "Wave"):
            try:
                diagnostics["codecs_%s" % key] = project.GetRenderCodecs(key)
            except Exception as exc:
                diagnostics["codecs_%s_error" % key] = str(exc)
        try:
            diagnostics["presets"] = project.GetRenderPresets()
        except Exception as exc:
            diagnostics["presets_error"] = str(exc)
        if old_format:
            try:
                project.SetCurrentRenderFormatAndCodec(old_format[0], old_format[1])
            except Exception:
                pass
        if old_page:
            try:
                resolve.OpenPage(old_page)
            except Exception:
                pass
        raise RuntimeError(
            "Failed to configure WAV audio export. Attempts: %s. Diagnostics: %s"
            % (json.dumps(attempts, ensure_ascii=False), json.dumps(diagnostics, ensure_ascii=False))
        )

    try:
        _start_render_and_wait(project)
    finally:
        if old_format:
            try:
                project.SetCurrentRenderFormatAndCodec(old_format[0], old_format[1])
            except Exception:
                pass
        if old_page:
            try:
                resolve.OpenPage(old_page)
            except Exception:
                pass

    source_path = None
    if os.path.isfile(output_path):
        try:
            if os.path.getmtime(output_path) + 2 >= render_started_at:
                source_path = output_path
        except Exception:
            source_path = output_path
    if source_path is None:
        source_path = _find_rendered_file(target_dir, base_name, [".wav"], render_started_at)
    converted = False
    if source_path is None:
        source_path = _find_rendered_file(
            target_dir,
            base_name,
            [".mp4", ".m4a", ".mov", ".aac", ".aif", ".aiff"],
            render_started_at,
        )
    if source_path and os.path.splitext(source_path)[1].lower() != ".wav":
        _convert_to_wav(source_path, output_path)
        converted = True
        source_path = output_path
    elif source_path and source_path != output_path:
        output_path = source_path

    if not os.path.isfile(output_path):
        raise RuntimeError("Audio export completed but output file was not found")

    return {
        "success": True,
        "path": output_path,
        "source_path": source_path,
        "converted": converted,
        "attempts": attempts,
    }


def run_export_audio(job):
    output_path = os.path.abspath(job["output"])
    result = export_audio(output_path)
    logs = []
    _worker_log(logs, "Audio exported by external Resolve scripting worker: %s" % result["path"])
    if result.get("converted"):
        _worker_log(logs, "Resolve rendered an AAC/MP4-style audio file; ffmpeg converted it to WAV.")
    result["logs"] = logs
    result["logs_streamed"] = True
    return result


def import_srt(path):
    resolve = _require_resolve()
    project = _require_project(resolve)
    media_pool = project.GetMediaPool()
    timeline = _require_timeline(project)
    root = media_pool.GetRootFolder()

    for clip in list(root.GetClipList() or []):
        if clip.GetName().lower().endswith(".srt"):
            media_pool.DeleteClips([clip])

    _delete_all_subtitle_tracks(timeline)

    imported = media_pool.ImportMedia([os.path.abspath(path)])
    if not imported:
        raise RuntimeError("Failed to import SRT file into Media Pool")
    subtitle_clip = imported[0]
    timeline.AddTrack("subtitle")
    result = media_pool.AppendToTimeline([subtitle_clip])
    if not result:
        raise RuntimeError("Failed to append subtitles to timeline")
    items = timeline.GetItemListInTrack("subtitle", 1) or []
    return {
        "success": True,
        "path": os.path.abspath(path),
        "count": len(items),
        "items": [{"start": item.GetStart(), "end": item.GetEnd(), "text": item.GetName()} for item in items],
    }


def _temp_json(prefix, payload):
    fd, path = tempfile.mkstemp(prefix=prefix, suffix=".json")
    os.close(fd)
    write_json(path, payload)
    return path


def _ms_to_srt(ms):
    hours = int(ms // 3600000)
    minutes = int((ms % 3600000) // 60000)
    seconds = int((ms % 60000) // 1000)
    millis = int(ms % 1000)
    return "%02d:%02d:%02d,%03d" % (hours, minutes, seconds, millis)


def _get_audio_info(path):
    cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_streams",
        "-select_streams",
        "a:0",
        path,
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("ffprobe failed: %s" % result.stderr.strip())
    info = json.loads(result.stdout or "{}")
    stream = info.get("streams", [{}])[0]
    return {
        "sample_rate": int(stream.get("sample_rate", 0) or 0),
        "channels": int(stream.get("channels", 0) or 0),
        "format": stream.get("codec_name", ""),
        "duration": float(stream.get("duration", 0) or 0),
    }


def _normalize_audio(path, config, logs):
    try:
        info = _get_audio_info(path)
    except Exception as exc:
        _worker_log(logs, "Audio probe skipped: %s" % exc)
        return path, None
    target_sr = int(config.get("audio_sample_rate", 16000))
    target_ch = int(config.get("audio_channels", 1))
    ffmpeg_timeout = int(config.get("ffmpeg_timeout", 300))

    needs_resample = info["sample_rate"] > target_sr
    needs_mono = info["channels"] > target_ch
    needs_wav = os.path.splitext(path)[1].lower() not in (".wav",)
    if not (needs_resample or needs_mono or needs_wav):
        return path, None

    _worker_log(logs, "Normalizing audio to %sHz/%sch WAV" % (target_sr, target_ch))
    output_path = os.path.splitext(path)[0] + "_16k.wav"
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        path,
        "-ar",
        str(target_sr),
        "-ac",
        str(target_ch),
        "-sample_fmt",
        "s16",
        "-map_metadata",
        "-1",
        output_path,
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=ffmpeg_timeout,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("ffmpeg normalization failed: %s" % result.stderr[:300].strip())
    return output_path, output_path


def _init_dashscope(config):
    import dashscope

    api_key = (config.get("api_key") or os.environ.get("DASHSCOPE_API_KEY", "")).strip()
    if not api_key:
        raise RuntimeError("DashScope API key is missing")
    dashscope.api_key = api_key
    region = (config.get("region") or "cn").strip()
    dashscope.base_http_api_url = REGION_URLS.get(region, REGION_URLS["cn"])
    return dashscope


def _upload_audio(audio_path, logs):
    from dashscope import Files

    _worker_log(logs, "Uploading audio: %s" % os.path.basename(audio_path))
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


def _transcribe_remote(file_url, language, config, logs):
    from dashscope.audio.asr import Transcription

    model = (config.get("model") or "").strip() or LANG_MODELS.get(language, "fun-asr")
    max_retries = int(config.get("transcription_max_retries", 600))
    poll_interval = int(config.get("transcription_poll_interval", 2))
    _worker_log(logs, "Submitting DashScope transcription (%s / %s)" % (model, language))
    task_response = Transcription.async_call(
        model=model,
        file_urls=[file_url],
        language_hints=[language],
    )
    task_id = getattr(task_response, "output", {}).get("task_id", None)
    if not task_id:
        raise RuntimeError("DashScope transcription submission failed")
    for attempt in range(max_retries):
        time.sleep(poll_interval)
        result = Transcription.wait(task=task_id)
        status = getattr(result, "output", {}).get("task_status", "UNKNOWN")
        if status == "SUCCEEDED":
            _worker_log(logs, "Remote transcription finished")
            return result
        if status == "FAILED":
            message = getattr(result, "output", {}).get("message", "unknown error")
            raise RuntimeError("Remote transcription failed: %s" % message)
        if attempt and attempt % max(1, 15 // max(poll_interval, 1)) == 0:
            _worker_log(logs, "Waiting for remote transcription...")
    raise RuntimeError("Remote transcription timed out")


def _result_to_srt(transcription_result, max_words=0):
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
                    all_words.append(
                        {
                            "begin_time": int(sentence.get("begin_time", 0)),
                            "end_time": int(sentence.get("end_time", 0)),
                            "text": sentence.get("text", "").strip(),
                            "punct": "",
                        }
                    )
                    continue
                for word in words:
                    all_words.append(
                        {
                            "begin_time": int(word.get("begin_time", 0)),
                            "end_time": int(word.get("end_time", 0)),
                            "text": word.get("text", "").strip(),
                            "punct": word.get("punctuation", ""),
                        }
                    )

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
            lines.append("%s --> %s" % (_ms_to_srt(buffer_start), _ms_to_srt(buffer_end)))
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


def _init_local_model(config, model_name=None, device="cpu", cache_dir=None):
    try:
        from funasr import AutoModel
    except ImportError:
        raise RuntimeError("funasr is not installed. Run: pip install funasr")
    if not model_name:
        model_name = (config.get("local_model_name") or "paraformer-zh").strip()
    kwargs = {"model": model_name, "device": device or "cpu"}
    if cache_dir:
        cache_dir = _configure_model_cache(cache_dir)
        kwargs["cache_dir"] = cache_dir
    if "paraformer" in model_name:
        kwargs["vad_model"] = "fsmn-vad"
        kwargs["punc_model"] = "ct-punc"
    return AutoModel(**kwargs)


def _transcribe_local(audio_path, model):
    result = model.generate(input=audio_path)
    if not result:
        raise RuntimeError("Local transcription returned no result")
    return result[0] if isinstance(result, list) else result


def _local_result_to_srt(local_result, max_words=0):
    timestamp_segs = local_result.get("timestamp", [])
    full_text = local_result.get("text", "").strip()
    if not timestamp_segs and not full_text:
        return "\n", 0
    if not timestamp_segs:
        return "1\n00:00:00,000 --> 00:00:01,000\n%s\n\n" % full_text, 1

    lines = []
    last_end_ms = 0

    def clean_segment_text(text):
        return (text or "").strip().rstrip("，。！？；：、,.")

    def split_segment_text(text):
        text = (text or "").strip()
        if not text:
            return []
        parts = []
        start = 0
        for match in re.finditer(r"[。！？，；：、,.]", text):
            end = match.end()
            part = clean_segment_text(text[start:end])
            if part:
                parts.append(part)
            start = end
        tail = clean_segment_text(text[start:])
        if tail:
            parts.append(tail)
        return parts or [clean_segment_text(text)]

    def flush_segment(start_ms, end_ms, text):
        nonlocal last_end_ms
        text = clean_segment_text(text)
        if not text:
            return
        start_ms = max(int(start_ms), last_end_ms)
        end_ms = max(int(end_ms), start_ms + 1)
        lines.append(str(len(lines) // 4 + 1))
        lines.append("%s --> %s" % (_ms_to_srt(start_ms), _ms_to_srt(end_ms)))
        lines.append(text)
        lines.append("")
        last_end_ms = end_ms

    def flush_split_segment(start_ms, end_ms, text):
        parts = split_segment_text(text)
        if not parts:
            return
        if len(parts) == 1:
            flush_segment(start_ms, end_ms, parts[0])
            return
        start_ms = int(start_ms)
        end_ms = int(max(end_ms, start_ms + len(parts)))
        duration = max(len(parts), end_ms - start_ms)
        total_chars = sum(max(1, len(part)) for part in parts)
        cursor = start_ms
        for index, part in enumerate(parts):
            if index == len(parts) - 1:
                part_end = end_ms
            else:
                part_duration = max(1, int(round(duration * max(1, len(part)) / float(total_chars))))
                part_end = min(end_ms - (len(parts) - index - 1), cursor + part_duration)
            if part_end <= cursor:
                part_end = cursor + 1
            flush_segment(cursor, part_end, part)
            cursor = part_end

    has_text = len(timestamp_segs[0]) >= 3 and isinstance(timestamp_segs[0][2], str) and timestamp_segs[0][2].strip()
    if has_text:
        for segment in timestamp_segs:
            flush_split_segment(segment[0], segment[1], str(segment[2] or "").strip())
    else:
        sentences = re.findall(r"[^。！？，；：、,.]+[。！？，；：、,.]?", full_text)
        total_ts = len(timestamp_segs)
        total_chars = len(full_text)
        cursor = 0
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence or total_chars == 0:
                continue
            sent_len = len(sentence)
            start_index = int(cursor * total_ts / total_chars)
            end_index = min(int((cursor + sent_len) * total_ts / total_chars), total_ts - 1)
            flush_segment(timestamp_segs[start_index][0], timestamp_segs[end_index][1], sentence)
            cursor += sent_len
    return "\n".join(lines), len(lines) // 4


def _build_char_timeline(ref_text, model_text, model_timestamps):
    model_tokens = model_text.split()
    clean_chars = [char for char in ref_text if char not in PUNCT_WHITESPACE]
    clean_to_tok = {}
    ref_cursor = 0
    token_count = min(len(model_tokens), len(model_timestamps))
    for tok_idx in range(token_count):
        token = model_tokens[tok_idx]
        token_len = len(token)
        matched = False
        search_end = len(clean_chars) - token_len + 1
        for start in range(ref_cursor, max(ref_cursor, search_end)):
            if start >= search_end:
                break
            if "".join(clean_chars[start : start + token_len]).lower() == token.lower():
                for offset in range(token_len):
                    clean_to_tok[start + offset] = tok_idx
                ref_cursor = start + token_len
                matched = True
                break
        if not matched and ref_cursor < len(clean_chars):
            clean_to_tok[ref_cursor] = tok_idx
            ref_cursor += 1

    timeline = []
    clean_pos = 0
    for char in ref_text:
        if char in PUNCT_WHITESPACE:
            if timeline:
                timeline.append((char, timeline[-1][1], timeline[-1][2]))
            else:
                timeline.append((char, 0, 0))
        else:
            tok_idx = clean_to_tok.get(clean_pos)
            if tok_idx is not None and tok_idx < len(model_timestamps):
                start_ms, end_ms = model_timestamps[tok_idx]
                timeline.append((char, start_ms, end_ms))
            elif timeline:
                timeline.append((char, timeline[-1][1], timeline[-1][2]))
            else:
                timeline.append((char, 0, 0))
            clean_pos += 1
    return timeline


def _clean_align_segment_text(text):
    text = re.sub(r"\s+", " ", text or "").strip()
    text = re.sub(r"([\u4e00-\u9fff\u3400-\u4dbf\uff00-\uffef])\s+([a-zA-Z0-9])", r"\1\2", text)
    text = re.sub(r"([a-zA-Z0-9])\s+([\u4e00-\u9fff\u3400-\u4dbf\uff00-\uffef])", r"\1\2", text)
    return text.rstrip("，。！？；：、")


def _join_align_text(parts):
    text = "".join(part for part in parts if part)
    return _clean_align_segment_text(text)


def _distribute_align_parts(parts, start_ms, end_ms):
    cleaned = [_clean_align_segment_text(part) for part in parts]
    cleaned = [part for part in cleaned if part]
    if not cleaned:
        return []
    start_ms = int(max(0, start_ms))
    end_ms = int(max(end_ms, start_ms + len(cleaned)))
    total_chars = sum(max(1, len(part)) for part in cleaned)
    duration = max(len(cleaned), end_ms - start_ms)
    cursor = start_ms
    distributed = []
    for index, text in enumerate(cleaned):
        if index == len(cleaned) - 1:
            part_end = end_ms
        else:
            part_duration = max(1, int(round(duration * max(1, len(text)) / float(total_chars))))
            part_end = min(end_ms - (len(cleaned) - index - 1), cursor + part_duration)
        if part_end <= cursor:
            part_end = cursor + 1
        distributed.append((text, cursor, part_end))
        cursor = part_end
    return distributed


def _merge_untimed_align_segments(segments):
    merged = []
    pending = []
    for text, start_ms, end_ms in segments:
        if end_ms <= start_ms:
            pending.append(text)
            continue
        if pending:
            window_start = merged[-1][2] if merged else 0
            merged.extend(_distribute_align_parts(pending + [text], window_start, end_ms))
            pending = []
            continue
        merged.append((text, start_ms, end_ms))
    if pending:
        trailing_text = _join_align_text(pending)
        if merged and trailing_text:
            last_text, start_ms, end_ms = merged[-1]
            merged[-1] = (_join_align_text([last_text, trailing_text]), start_ms, end_ms)
        elif trailing_text:
            merged.append((trailing_text, 0, 1000))
    return _spread_duplicate_time_segments(merged)


def _spread_duplicate_time_segments(segments):
    spread = []
    index = 0
    while index < len(segments):
        text, start_ms, end_ms = segments[index]
        group = [(text, start_ms, end_ms)]
        index += 1
        while index < len(segments) and segments[index][1] == start_ms and segments[index][2] == end_ms:
            group.append(segments[index])
            index += 1
        if len(group) == 1:
            spread.extend(group)
        else:
            spread.extend(_distribute_align_parts([item[0] for item in group], start_ms, end_ms))
    return spread


def _build_srt_segments(ref_text, result, max_chars=0):
    item = result[0] if isinstance(result, list) and result else result
    if not isinstance(item, dict):
        raise RuntimeError("Unsupported alignment result format")
    model_text = item.get("text", "")
    model_timestamps = item.get("timestamp", [])
    if not model_timestamps:
        return [(ref_text, 0, 0)]
    char_timeline = _build_char_timeline(ref_text, model_text, model_timestamps)
    raw_segments = []
    buffer_chars = []
    buffer_start = 0
    for index, (char, start_ms, end_ms) in enumerate(char_timeline):
        if not buffer_chars:
            buffer_start = start_ms
        buffer_chars.append(char)
        should_split = False
        if char in ALIGN_SPLIT_CHARS:
            should_split = True
        elif max_chars > 0 and len(buffer_chars) >= max_chars:
            should_split = True
        elif index == len(char_timeline) - 1:
            should_split = True
        if should_split:
            text = _clean_align_segment_text("".join(buffer_chars))
            if text:
                raw_segments.append((text, buffer_start, end_ms))
            buffer_chars = []
    return _merge_untimed_align_segments(raw_segments)


def _read_srt_entries(path):
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


def _write_srt_entries(path, entries):
    lines = []
    for entry in entries:
        lines.append(str(entry["index"]))
        lines.append("%s --> %s" % (entry["start"], entry["end"]))
        lines.append(entry["text"])
        lines.append("")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))


def _load_corrections(path):
    if not path:
        return {}
    data = load_json(path, {})
    if not isinstance(data, dict):
        raise RuntimeError("Corrections file must be a JSON object")
    return data


def _apply_corrections_to_text(text, corrections):
    for wrong, correct in corrections.items():
        text = text.replace(wrong, correct)
    return text


def _zhconv_convert(text, lang):
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


def _fix_cjk_spacing(text):
    text = re.sub(r"([\u4e00-\u9fff\u3400-\u4dbf\uff00-\uffef])\s+([a-zA-Z0-9])", r"\1\2", text)
    text = re.sub(r"([a-zA-Z0-9])\s+([\u4e00-\u9fff\u3400-\u4dbf\uff00-\uffef])", r"\1\2", text)
    return text


def _fix_punctuation(text):
    text = re.sub(r"，,", "，", text)
    text = re.sub(r",，", "，", text)
    text = re.sub(r"[.][.]+", "…", text)
    text = re.sub(r"…\.", "…", text)
    text = re.sub(r"。\.", "。", text)
    return text.replace('"', "「")


def run_asr(job):
    config = {
        "api_key": job.get("dashscope_api_key", ""),
        "region": job.get("region", "cn"),
        "model": job.get("model", ""),
        "max_words": job.get("max_words", 0),
        "audio_sample_rate": job.get("audio_sample_rate", 16000),
        "audio_channels": job.get("audio_channels", 1),
        "ffmpeg_timeout": job.get("ffmpeg_timeout", 300),
        "transcription_max_retries": job.get("transcription_max_retries", 600),
        "transcription_poll_interval": job.get("transcription_poll_interval", 2),
        "local_model_name": job.get("model_name", "paraformer-zh"),
    }
    logs = []
    audio_path = os.path.abspath(job["audio"])
    output_path = os.path.abspath(job["output"])
    language = job.get("lang", "zh")
    max_words = int(job.get("max_words", 0))
    local_mode = bool(job.get("local"))
    temp_audio = None
    try:
        if local_mode:
            _worker_log(logs, "Running local ASR")
            cache_dir = _configure_model_cache(job.get("cache_dir"), logs)
            normalized_audio, temp_audio = _normalize_audio(audio_path, config, logs)
            _worker_log(logs, "Loading local ASR model")
            model = _init_local_model(
                config,
                model_name=job.get("model_name"),
                device=job.get("device", "cpu"),
                cache_dir=cache_dir,
            )
            _worker_log(logs, "Transcribing with local ASR")
            local_result = _transcribe_local(normalized_audio, model)
            _worker_log(logs, "Converting local ASR result to SRT")
            srt_text, count = _local_result_to_srt(local_result, max_words=max_words)
        else:
            _worker_log(logs, "Running remote ASR")
            _init_dashscope(config)
            normalized_audio, temp_audio = _normalize_audio(audio_path, config, logs)
            file_url = _upload_audio(normalized_audio, logs)
            result = _transcribe_remote(file_url, language, config, logs)
            srt_text, count = _result_to_srt(result, max_words=max_words)
        with open(output_path, "w", encoding="utf-8") as handle:
            handle.write(srt_text)
        srt_data = read_srt_file(output_path)
        return {
            "success": True,
            "path": output_path,
            "count": count,
            "items": srt_data["items"],
            "logs": logs,
            "logs_streamed": True,
        }
    finally:
        if temp_audio and os.path.exists(temp_audio):
            try:
                os.remove(temp_audio)
            except OSError:
                pass


def run_align(job):
    audio_path = os.path.abspath(job["audio"])
    text_path = os.path.abspath(job["text"])
    output_path = os.path.abspath(job["output"])
    model_name = job.get("model", "fa-zh")
    device = job.get("device", "cpu")
    cache_dir = job.get("cache_dir", "")
    max_chars = int(job.get("max_chars", 0))
    logs = []
    cache_dir = _configure_model_cache(cache_dir, logs)

    if not os.path.isfile(audio_path):
        raise RuntimeError("Audio file does not exist: %s" % audio_path)
    if not os.path.isfile(text_path):
        raise RuntimeError("Reference text file does not exist: %s" % text_path)

    with open(text_path, "r", encoding="utf-8") as handle:
        ref_text = handle.read().strip()
    if not ref_text:
        raise RuntimeError("Reference text is empty")

    try:
        from funasr import AutoModel
    except ImportError:
        raise RuntimeError("funasr is not installed. Run: pip install funasr torch")

    _worker_log(logs, "Loading align model: %s" % model_name)
    model_kwargs = {"model": model_name, "device": device}
    if cache_dir:
        model_kwargs["cache_dir"] = cache_dir
    model = AutoModel(**model_kwargs)
    _worker_log(logs, "Running forced alignment")
    result = model.generate(input=(audio_path, text_path), data_type=("sound", "text"))
    _worker_log(logs, "Building SRT segments")
    segments = _build_srt_segments(ref_text, result, max_chars=max_chars)
    if not segments:
        raise RuntimeError("Alignment returned no subtitle segments")

    lines = []
    for idx, (text, start_ms, end_ms) in enumerate(segments, 1):
        if end_ms == 0 and start_ms == 0 and len(segments) == 1:
            lines.extend([str(idx), "00:00:00,000 --> 00:00:00,000", text, ""])
        elif end_ms > start_ms:
            lines.extend([str(idx), "%s --> %s" % (_ms_to_srt(start_ms), _ms_to_srt(end_ms)), text, ""])
    with open(output_path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    srt_data = read_srt_file(output_path)
    return {
        "success": True,
        "path": output_path,
        "count": srt_data["count"],
        "items": srt_data["items"],
        "logs": logs,
        "logs_streamed": True,
    }


def run_read_srt(job):
    result = read_srt_file(os.path.abspath(job["path"]))
    result["logs"] = ["Loaded SRT: %s" % result["path"]]
    return result


def run_convert_srt(job):
    input_path = os.path.abspath(job["input"])
    output_path = os.path.abspath(job["output"])
    lang = job.get("lang", "zh-cn")
    corrections = _load_corrections(job.get("corrections"))
    entries = _read_srt_entries(input_path)
    logs = ["Converting SRT to %s" % lang]
    changed_count = 0
    original_count = len(entries)
    for entry in entries:
        before = entry["text"]
        text = before
        if corrections:
            text = _apply_corrections_to_text(text, corrections)
        if lang:
            text = _zhconv_convert(text, lang)
        text = _fix_cjk_spacing(text)
        text = _fix_punctuation(text)
        entry["text"] = text
        if text != before:
            changed_count += 1
    _write_srt_entries(output_path, entries)
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
    corrections = _load_corrections(job.get("corrections"))
    entries = _read_srt_entries(input_path)
    changed_count = 0
    for entry in entries:
        before = entry["text"]
        entry["text"] = _apply_corrections_to_text(entry["text"], corrections)
        if entry["text"] != before:
            changed_count += 1
    _write_srt_entries(output_path, entries)
    result = read_srt_file(output_path)
    result.update({"changed_count": changed_count, "logs": ["Applied text replacements"]})
    return result


def _stream_event(event_type, **payload):
    payload["type"] = event_type
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def _require_llm_config(job):
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
        ),
        "model": job.get("model") or "deepseek-v4-flash",
        "enable_thinking": bool(job.get("enable_thinking", True)),
    }


def _extract_json_object(text):
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise RuntimeError("LLM response did not contain a JSON object")
    return json.loads(text[start : end + 1])


def _validate_llm_srt_json(data):
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


def _apply_index_text_edits(input_path, output_path, edit_json):
    entries = _read_srt_entries(input_path)
    edits = {int(item["index"]): item["text"] for item in edit_json.get("items", [])}
    changed_count = 0
    for entry in entries:
        index = int(entry["index"])
        if index in edits and entry["text"] != edits[index]:
            entry["text"] = edits[index]
            changed_count += 1
    _write_srt_entries(output_path, entries)
    result = read_srt_file(output_path)
    result.update({"changed_count": changed_count})
    return result


def _llm_stream_chat(job, messages):
    config = _require_llm_config(job)
    _stream_event("status", message="连接 LLM：%s" % config["model"])
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
                "你是专业影视字幕编辑。必须只输出 JSON 对象，格式为 "
                "{\"items\":[{\"index\":1,\"text\":\"修改后的字幕文本\"}]}。"
                "只包含需要改动或确认后的条目，不输出 markdown。"
            ),
        },
        {
            "role": "user",
            "content": "%s%s\n\nSRT 内容如下：\n%s" % (instruction, reference_section, srt_data["content"]),
        },
    ]
    _stream_event("status", message="调用 LLM 生成%s JSON" % mode_text)
    answer = _llm_stream_chat(job, messages)
    _stream_event("status", message="解析 LLM JSON")
    edit_json = _validate_llm_srt_json(_extract_json_object(answer))
    ensure_dir(os.path.dirname(json_output) or ".")
    write_json(json_output, edit_json)
    _stream_event("status", message="应用 JSON 到新 SRT")
    result = _apply_index_text_edits(input_path, output_path, edit_json)
    result.update(
        {
            "json_path": json_output,
            "logs": [
                "LLM %s JSON written to %s" % (mode_text, json_output),
                "LLM %s SRT written to %s" % (mode_text, output_path),
            ],
        }
    )
    _stream_event("result", payload=result)


def run_llm_optimize_text_stream(job):
    text = (job.get("text") or "").strip()
    if not text:
        raise RuntimeError("Reference text is empty")
    _stream_event("status", message="调用 LLM 优化参考文案")
    prompt = job.get("optimize_prompt") or DEFAULT_OPTIMIZE_PROMPT
    messages = [
        {
            "role": "system",
            "content": prompt,
        },
        {"role": "user", "content": text},
    ]
    optimized = _llm_stream_chat(job, messages).strip()
    _stream_event("result", payload={"success": True, "text": optimized, "logs": ["Reference text optimized by LLM"]})


def run_worker_job(job):
    action = job.get("action")
    if action == "export_audio":
        return run_export_audio(job)
    if action == "asr":
        return run_asr(job)
    if action == "align":
        return run_align(job)
    if action == "read_srt":
        return run_read_srt(job)
    if action == "convert_srt":
        return run_convert_srt(job)
    if action == "apply_corrections":
        return run_apply_corrections(job)
    raise RuntimeError("Unknown worker action: %s" % action)


def _cli_worker(job_json_path):
    try:
        job = load_json(job_json_path, {})
        action = job.get("action")
        if action == "llm_srt_edit":
            run_llm_srt_edit_stream(job)
            return 0
        if action == "llm_optimize_text":
            run_llm_optimize_text_stream(job)
            return 0
        with contextlib.redirect_stdout(sys.stderr):
            result = run_worker_job(job)
        print(json.dumps(result, ensure_ascii=False))
    except Exception as exc:
        if "job" in locals() and job.get("action") in ("llm_srt_edit", "llm_optimize_text"):
            _stream_event("error", message=str(exc))
        else:
            print(json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    return 0


def main():
    parser = argparse.ArgumentParser(description="Subtitle Agent Core")
    subparsers = parser.add_subparsers(dest="command")
    worker_parser = subparsers.add_parser("worker", help="Run a worker job from JSON")
    worker_parser.add_argument("job_json")
    args = parser.parse_args()

    if args.command == "worker":
        return _cli_worker(args.job_json)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
